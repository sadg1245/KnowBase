"""搜索与 RAG 对话端点。"""

import json
import time
import uuid
from functools import lru_cache, partial
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings
from app.config import Settings
from app.models.conversation import Conversation
from app.models.user import User
from app.models.workspace import Workspace
from app.services.conversation_service import ConversationService
from app.services.hybrid_retrieval import HybridRetrievalService, RetrievalCandidate
from app.services.ownership import owned_workspace
from app.services.learning_answer import build_follow_up_suggestions
from app.services.learning_answer_service import (
    DETERMINISTIC_RETRIEVAL_ERROR,
    build_learning_prompt,
    deterministic_empty_answer,
    merged_evidence_status,
    parse_layered_answer,
    retrieval_available,
)
from app.schemas.schemas import (
    ChatRequest,
    ChatResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SourceItem,
)


router = APIRouter(tags=["search"])


def serialize_source(candidate: RetrievalCandidate) -> dict[str, object]:
    """Serialize one retrieval candidate consistently for SSE and persistence."""
    return {
        "content": candidate.content,
        "source_file": candidate.source_file,
        "page_num": candidate.page_num,
        "score": round(candidate.rerank_score, 4),
        "document_id": candidate.document_id,
        "heading": candidate.heading,
        "chunk_id": candidate.chunk_id,
    }


def _document_where(document_ids: list[str]) -> dict | None:
    """Build a Chroma filter compatible with current and legacy metadata."""
    if not document_ids:
        return None
    ids = list(dict.fromkeys(document_ids))
    return {
        "$or": [
            {"doc_id": {"$in": ids}},
            {"document_id": {"$in": ids}},
        ]
    }


async def _persist_stream_message(db: AsyncSession, message: Conversation) -> None:
    """Persist a chat message without holding SQLite's write lock across SSE."""
    db.add(message)
    await db.flush()
    await db.commit()


# ---------------------------------------------------------------------------
# 核心模块的安全导入（可能尚不存在）
# ---------------------------------------------------------------------------

def _get_chroma_client():
    """返回向量库客户端；失败时给出面向用户的提示，技术原因写入日志。"""
    try:
        from app.core.chroma import get_chroma_client

        return get_chroma_client()
    except Exception as exc:
        logger.error("Vector store unavailable: {}", exc)
        raise HTTPException(
            status_code=503,
            detail="检索服务暂时不可用，请稍后重试。",
        ) from exc


@lru_cache(maxsize=1)
def _get_embedding_function():
    """返回嵌入函数，优先使用 sentence-transformers。"""
    try:
        from sentence_transformers import SentenceTransformer

        settings = get_settings()

        model = SentenceTransformer(settings.DEFAULT_EMBEDDING)

        def embed(texts: list[str]) -> list[list[float]]:
            embeddings = model.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()

        return embed
    except Exception as exc:
        logger.error("Embedding model is unavailable: {}", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Embedding model is unavailable: {exc}",
        ) from exc


async def _call_llm_streaming(prompt: str, settings: Settings):
    """通过 litellm 调用配置的 LLM 并以 SSE 分块方式生成响应。"""
    try:
        import litellm

        api_key = None
        provider = settings.DEFAULT_LLM_PROVIDER.lower()
        model = settings.DEFAULT_LLM_MODEL

        if provider == "deepseek":
            api_key = settings.DEEPSEEK_API_KEY
        elif provider == "openai":
            api_key = settings.OPENAI_API_KEY
        elif provider == "dashscope":
            api_key = settings.DASHSCOPE_API_KEY
        elif provider == "zhipu":
            api_key = settings.ZHIPU_API_KEY
        elif provider == "ollama":
            api_key = "ollama"  # ollama 不需要真实的密钥

        # 根据 provider 映射 litellm 模型字符串和 base_url
        api_base = None
        if provider == "ollama":
            litellm_model = f"ollama/{model}"
            api_base = settings.OLLAMA_BASE_URL
        elif provider == "deepseek":
            litellm_model = f"deepseek/{model}"
            api_base = "https://api.deepseek.com/v1"
        elif provider in ("qwen", "dashscope"):
            litellm_model = f"openai/{model}"
            api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        elif provider in ("glm", "zhipu"):
            litellm_model = f"openai/{model}"
            api_base = "https://open.bigmodel.cn/api/paas/v4"
        else:
            litellm_model = model

        kwargs = {
            "model": litellm_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        response = await litellm.acompletion(**kwargs)

        full_text = ""
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                token = delta.content
                full_text += token
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'done': True, 'full_text': full_text}, ensure_ascii=False)}\n\n"

    except Exception as exc:
        logger.error("LLM streaming call failed: {}", exc)
        yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# POST /api/search — RAG 搜索
# ---------------------------------------------------------------------------


async def _vector_recall(
    *,
    query: str,
    workspace_id: str | None,
    document_ids: list[str],
    top_k: int,
    owned_workspace_ids: list[str] | None = None,
) -> list[dict]:
    """Return vector candidates in the same shape used by hybrid retrieval."""
    embed_fn = _get_embedding_function()
    query_embedding = embed_fn([query])[0]
    chroma_client = _get_chroma_client()
    if workspace_id:
        collection_names = [f"ws_{workspace_id}".replace("-", "_")]
    else:
        collection_names = [
            f"ws_{value}".replace("-", "_") for value in (owned_workspace_ids or [])
        ]
    all_results: list[dict] = []
    for collection_name in collection_names:
        collection = chroma_client.get_collection(name=collection_name)
        query_kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        document_where = _document_where(document_ids)
        if document_where:
            query_kwargs["where"] = document_where
        result = collection.query(**query_kwargs)
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        for index, content in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            distance = distances[index] if index < len(distances) else 1.0
            all_results.append({
                "chunk_id": ids[index] if index < len(ids) else f"{collection_name}-{index}",
                "content": content,
                "source_file": metadata.get("source_file", metadata.get("filename", "unknown")),
                "page_num": metadata.get("page_num"),
                "score": round(max(0.0, 1.0 - distance), 4),
                "document_id": metadata.get("doc_id", metadata.get("document_id")),
                "heading": metadata.get("heading"),
            })
    all_results.sort(key=lambda item: item["score"], reverse=True)
    return all_results[:top_k]


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(
    payload: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Keep the legacy search endpoint as vector-only diagnostic search."""
    owned_ids = await _owned_workspace_ids(db, current_user)
    if payload.workspace_id:
        await owned_workspace(db, payload.workspace_id, current_user)
    results = await _vector_recall(
        query=payload.query,
        workspace_id=payload.workspace_id,
        document_ids=payload.document_ids,
        top_k=payload.top_k,
        owned_workspace_ids=owned_ids,
    )
    return {"results": results}


async def _owned_workspace_ids(db: AsyncSession, user: User) -> list[str]:
    return list((await db.execute(
        select(Workspace.id).where(Workspace.owner_id == user.id)
    )).scalars().all())


# ---------------------------------------------------------------------------
# POST /api/chat — 带 SSE 流式输出的 RAG 对话
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Persistent learning chat with hybrid evidence retrieval and SSE events."""
    if not payload.workspace_id:
        raise HTTPException(400, "Please choose a knowledge base before starting a learning session")
    await owned_workspace(db, payload.workspace_id, current_user)

    service = ConversationService(db, user_id=current_user.id)
    session_id = payload.session_id or payload.conversation_id
    session = await service.get_session(session_id) if session_id else None
    if session_id and session is None:
        raise HTTPException(404, "Learning session not found")
    mode = "simple" if payload.mode == "explain" else payload.mode
    if session is None:
        session = await service.create_session(
            workspace_id=payload.workspace_id,
            document_ids=payload.document_ids,
            mode=mode,
            strict_sources=payload.strict_sources,
        )
    else:
        session = await service.update_session(
            session.id,
            workspace_id=payload.workspace_id,
            selected_document_ids=payload.document_ids,
            preferred_mode=mode,
            strict_sources=payload.strict_sources,
        )
    assert session is not None

    user_msg = Conversation(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        session_id=session.id,
        workspace_id=payload.workspace_id,
        role="user",
        content=payload.question,
        mode=mode,
        generation_status="complete",
    )
    db.add(user_msg)
    await db.flush()
    await service.record_question(session, user_msg)
    title_changed = await service.touch_session(session, payload.question)
    await db.commit()

    owned_ids = await _owned_workspace_ids(db, current_user)
    retrieval = await HybridRetrievalService(
        db, partial(_vector_recall, owned_workspace_ids=owned_ids)
    ).retrieve(
        query=payload.question,
        workspace_id=payload.workspace_id,
        document_ids=payload.document_ids,
        session_id=session.id,
        user_message_id=user_msg.id,
        vector_top_k=settings.RAG_VECTOR_TOP_K,
        keyword_top_k=settings.RAG_KEYWORD_TOP_K,
        selected_top_k=settings.RAG_SELECTED_TOP_K,
        supported_threshold=settings.RAG_SUPPORTED_THRESHOLD,
        second_threshold=settings.RAG_SECOND_THRESHOLD,
        limited_threshold=settings.RAG_LIMITED_THRESHOLD,
    )
    await db.commit()

    source_items = [serialize_source(item) for item in retrieval.items]
    context_chunks = [
        f"[资料{index}] 来源：{item['source_file']}"
        + (f"，第 {item['page_num']} 页" if item.get("page_num") else "")
        + (f"，章节：{item['heading']}" if item.get("heading") else "")
        + f"\n{item['content']}"
        for index, item in enumerate(source_items, 1)
    ]
    history = await service.messages(session.id)
    history_lines = [
        f"{item.role}：{item.content}" for item in history[-settings.CONVERSATION_HISTORY_LIMIT:]
    ]
    full_prompt = build_learning_prompt(
        question=payload.question,
        mode=mode,
        context_blocks=context_chunks,
        profile_block="",
        memory_block="",
        history_lines=history_lines,
    )
    suggestions = build_follow_up_suggestions(payload.question, mode)

    def event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def event_generator():
        full_answer = ""
        assistant_msg: Conversation | None = None
        try:
            yield event({"session": {"id": session.id, "title": session.title, "title_changed": title_changed}})
            retrievers_ok = retrieval_available(
                vector_succeeded=retrieval.vector_succeeded,
                keyword_succeeded=retrieval.keyword_succeeded,
            )
            yield event({
                "evidence": {
                    "status": retrieval.evidence_status,
                    "vector_succeeded": retrieval.vector_succeeded,
                    "keyword_succeeded": retrieval.keyword_succeeded,
                    "degradation_reason": retrieval.degradation_reason,
                    "top_score": round(retrieval.top_score, 4),
                    "answer_policy": "source_first",
                    "model_fallback": retrievers_ok and retrieval.evidence_status != "supported",
                    "profile_injected": False,
                    "memory_hits": [],
                    "memory_degraded_reason": None,
                }
            })

            if not retrievers_ok:
                streamed = DETERMINISTIC_RETRIEVAL_ERROR
                yield event({"token": streamed})
                parsed = parse_layered_answer(streamed, len(source_items))
            else:
                streamed = ""
                async for chunk in _call_llm_streaming(full_prompt, settings):
                    data_text = chunk.removeprefix("data: ").strip()
                    data_obj = json.loads(data_text)
                    if "error" in data_obj:
                        raise RuntimeError(data_obj["error"])
                    token = data_obj.get("token", "")
                    if token:
                        streamed += token
                        yield event({"token": token})
                    if data_obj.get("full_text"):
                        streamed = data_obj["full_text"]
                parsed = parse_layered_answer(streamed, len(source_items))
                if not parsed.content.strip():
                    parsed = parse_layered_answer(deterministic_empty_answer(), len(source_items))
                if parsed.content != streamed.strip():
                    yield event({"replace": parsed.content})
            full_answer = parsed.content
            answer_status = merged_evidence_status(
                retrieval.evidence_status, parsed, retrievers_ok=retrievers_ok
            )

            assistant_msg = Conversation(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                session_id=session.id,
                workspace_id=payload.workspace_id,
                role="assistant",
                content=full_answer,
                sources=source_items,
                mode=mode,
                evidence_status=answer_status,
                retrieval_run_id=retrieval.run_id,
                follow_up_questions=suggestions,
                generation_status="complete",
                answer_policy="source_first",
                used_memory_ids=[],
                profile_summary=None,
            )
            await _persist_stream_message(db, assistant_msg)
            yield event({"sources": source_items})
            yield event({"suggestions": suggestions})
            yield event({
                "done": True,
                "message_id": assistant_msg.id,
                "session_id": session.id,
                "conversation_id": session.id,
                "confidence": round(retrieval.top_score, 4),
                "generation_status": "complete",
                "answer_layers": parsed.answer_layers,
            })
        except Exception as exc:
            logger.error("Chat streaming failed: {}", exc)
            if full_answer:
                assistant_msg = Conversation(
                    id=str(uuid.uuid4()),
                    user_id=current_user.id,
                    session_id=session.id,
                    workspace_id=payload.workspace_id,
                    role="assistant",
                    content=full_answer,
                    sources=source_items,
                    mode=mode,
                    evidence_status="error",
                    retrieval_run_id=retrieval.run_id,
                    generation_status="partial",
                    answer_policy="source_first",
                )
                await _persist_stream_message(db, assistant_msg)
            yield event({"error": str(exc), "retryable": True, "message_id": assistant_msg.id if assistant_msg else None})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

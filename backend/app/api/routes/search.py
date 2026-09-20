"""搜索与 RAG 对话端点。"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings
from app.config import Settings
from app.core.embedding import get_embedding_service
from app.models.conversation import Conversation
from app.models.user import User
from app.services.conversation_service import ConversationService
from app.services.hybrid_retrieval import (
    build_metadata_where,
    HybridRetrievalService,
    RetrievalCandidate,
    RetrievalRequest,
)
from app.services.ownership import owned_workspace, owned_workspace_ids
from app.services.scoped_retrieval import retrieve_with_expansion
from app.rag.indexing.multivector import logical_chunk_id
from app.schemas.scope import RetrievalScope
from app.services.scope_resolver import ScopeResolver


async def debug_retrieval(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """检索调试视图：逐条候选的分项打分、画像 Bonus 与命中向量种类。

    默认关闭（`RAG_DEBUG_ENDPOINT_ENABLED=false`）；开启后可用于核对
    「范围 → 召回 → 融合 → 重排 → 画像加权」的每一步是否按预期工作。
    """
    if not settings.RAG_DEBUG_ENDPOINT_ENABLED:
        raise HTTPException(404, "Retrieval debug endpoint is disabled")
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(422, "query is required")
    workspace_id = payload.get("workspace_id")
    document_ids = [str(value) for value in (payload.get("document_ids") or [])]
    top_k = max(1, min(50, int(payload.get("top_k") or 5)))
    if workspace_id:
        await owned_workspace(db, workspace_id, current_user)

    owned_ids = await _owned_workspace_ids(db, current_user)
    resolver = ScopeResolver(db, user=current_user, owned_workspaces=owned_ids)
    scope = RetrievalScope(mode="strict", workspace_ids=[workspace_id] if workspace_id else [],
                           document_ids=document_ids)
    resolved = await resolver.resolve(
        query=query, scope=scope, workspace_id=workspace_id
    )
    service = HybridRetrievalService(db, _vector_recall)
    result = await service.retrieve_scoped(RetrievalRequest(
        query=query,
        scope=resolved,
        owned_workspace_ids=owned_ids,
        selected_top_k=top_k,
        vector_top_k=settings.RAG_VECTOR_TOP_K,
        keyword_top_k=settings.RAG_KEYWORD_TOP_K,
        supported_threshold=settings.RAG_SUPPORTED_THRESHOLD,
        second_threshold=settings.RAG_SECOND_THRESHOLD,
        limited_threshold=settings.RAG_LIMITED_THRESHOLD,
    ))
    await db.commit()
    return {
        "query": query,
        "scope": {
            "mode": resolved.mode,
            "workspace_ids": list(resolved.hard_workspace_ids),
            "document_ids": list(resolved.hard_document_ids),
            "resolution_reason": list(resolved.resolution_reason),
        },
        "evidence_status": result.evidence_status,
        "degradation_reason": result.degradation_reason,
        "run_id": result.run_id,
        "hits": [
            {
                "chunk_id": item.chunk_id,
                "source_file": item.source_file,
                "page_num": item.page_num,
                "heading": item.heading,
                "vector_rank": item.vector_rank,
                "keyword_rank": item.keyword_rank,
                "vector_score": round(item.vector_score, 4),
                "keyword_score": round(item.keyword_score, 4),
                "fusion_score": round(item.fusion_score, 6),
                "rerank_score": round(item.rerank_score, 6),
                "profile_bonus": round(item.profile_bonus, 6),
                "vector_kinds": list(item.vector_kinds),
                "content_type": item.content_type,
                "difficulty": item.difficulty,
                "final_rank": item.final_rank,
                "content_preview": (item.content or "")[:160],
            }
            for item in result.items
        ],
    }


def _index_stale_reasons(workspace_ids: list[str]) -> list[str]:
    """索引指纹自检（设计文档 §15.2）：不一致时返回原因，检索照常进行。"""
    if not workspace_ids:
        return []
    try:
        from app.config import settings as _settings
        from app.rag.indexing import current_fingerprint, fingerprint_gap, read_fingerprint

        chroma = _get_chroma_client()
        current = current_fingerprint(_settings, get_embedding_service())
    except Exception:
        logger.warning("Index fingerprint self-check unavailable; skipping stale hints.")
        return []
    reasons: list[str] = []
    for workspace_id in workspace_ids:
        collection_name = f"ws_{workspace_id}".replace("-", "_")
        try:
            collection = chroma.get_collection(name=collection_name)
        except Exception:
            continue
        try:
            # 空 collection（资料已删除或尚未入库）不需要重建提示
            if collection.count() == 0:
                continue
        except Exception:
            pass
        for gap in fingerprint_gap(read_fingerprint(collection), current):
            reasons.append(f"{workspace_id}:{gap}")
    return reasons
from app.services.scope_resolver import ScopeResolver, scope_from_session
from app.schemas.scope import RetrievalScope
from app.services.learner_profile import LearnerProfileService, format_profile_block
from app.services.learning_memory import LearningMemoryService, format_memory_block
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

# 检索调试端点默认关闭，注册放在 router 创建之后
router.add_api_route("/debug/retrieval", debug_retrieval, methods=["POST"])


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


_SCOPE_KEYS = (
    "workspace_ids",
    "document_ids",
    "knowledge_point_ids",
    "allow_workspace_expansion",
)


def _scope_from_dict(payload: dict, *, default_mode: str) -> RetrievalScope:
    mode = str(payload.get("mode") or payload.get("scope_mode") or default_mode)
    config = {key: payload[key] for key in _SCOPE_KEYS if key in payload}
    return RetrievalScope.from_config(mode, config)


def _scope_from_payload(payload, session, *, default_mode: str) -> RetrievalScope:
    """确定本次请求的学习范围。

    优先级：请求级 override > 请求级 scope > 兼容字段（文件）> 会话范围 > 默认模式。
    文档约束优先于知识库约束，与迁移前语义一致。
    """
    if payload.scope_override:
        override = _scope_from_dict(dict(payload.scope_override), default_mode=default_mode)
        if payload.workspace_id and not override.workspace_ids:
            override.workspace_ids = [payload.workspace_id]
        if payload.document_ids and not override.document_ids:
            override.document_ids = list(payload.document_ids)
        return override

    if payload.scope_mode or payload.scope_config:
        config = dict(payload.scope_config or {})
        if payload.workspace_id and not config.get("workspace_ids"):
            config["workspace_ids"] = [payload.workspace_id]
        if payload.document_ids and not config.get("document_ids"):
            config["document_ids"] = list(payload.document_ids)
        return RetrievalScope.from_config(payload.scope_mode, config)

    if payload.document_ids:
        return RetrievalScope(
            mode="strict",
            document_ids=list(payload.document_ids),
            workspace_ids=[payload.workspace_id] if payload.workspace_id else [],
        )

    session_scope = scope_from_session(session)
    if session_scope is not None:
        if payload.workspace_id and payload.workspace_id not in session_scope.workspace_ids:
            session_scope.workspace_ids = [payload.workspace_id]
        return session_scope

    if payload.workspace_id:
        return RetrievalScope(mode="strict", workspace_ids=[payload.workspace_id])
    return RetrievalScope(mode=default_mode)


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
    workspace_ids: list[str],
    document_ids: list[str],
    top_k: int,
    filters: dict | None = None,
) -> list[dict]:
    """Return vector candidates in the same shape used by hybrid retrieval."""
    workspace_ids = [value for value in dict.fromkeys(workspace_ids) if value]
    if not workspace_ids:
        return []
    query_embedding = await get_embedding_service().embed_query(query)
    chroma_client = _get_chroma_client()
    collection_names = {
        f"ws_{value}".replace("-", "_"): value for value in workspace_ids
    }
    all_results: list[dict] = []
    for collection_name, collection_workspace_id in collection_names.items():
        try:
            collection = chroma_client.get_collection(name=collection_name)
        except Exception:
            # 该知识库还没有建立 collection（例如尚未入库任何文档）
            continue
        query_kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        where_clauses = [
            clause
            for clause in (_document_where(document_ids), build_metadata_where(filters))
            if clause
        ]
        if len(where_clauses) == 1:
            query_kwargs["where"] = where_clauses[0]
        elif where_clauses:
            query_kwargs["where"] = {"$and": where_clauses}
        result = collection.query(**query_kwargs)
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        merged: dict[str, dict] = {}
        for index, content in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            distance = distances[index] if index < len(distances) else 1.0
            vector_id = ids[index] if index < len(ids) else f"{collection_name}-{index}"
            logical_id = logical_chunk_id(vector_id, metadata)
            kind = str(metadata.get("vector_kind") or "content")
            score = round(max(0.0, 1.0 - distance), 4)
            key = f"{collection_workspace_id}:{logical_id}"
            entry = merged.get(key)
            if entry is None:
                merged[key] = {
                    "chunk_id": logical_id,
                    "content": content,
                    "source_file": metadata.get("source_file", metadata.get("filename", "unknown")),
                    "page_num": metadata.get("page_num"),
                    "score": score,
                    "document_id": metadata.get("doc_id", metadata.get("document_id")),
                    "heading": metadata.get("heading"),
                    "workspace_id": collection_workspace_id,
                    "vector_kinds": [kind],
                    "content_type": metadata.get("content_type"),
                    "difficulty": metadata.get("difficulty"),
                    "_content_kind": kind == "content",
                }
                continue
            if kind not in entry["vector_kinds"]:
                entry["vector_kinds"].append(kind)
            if score > entry["score"]:
                entry["score"] = score
            # 同一逻辑块被多种 kind 命中时，证据正文必须来自 content 向量
            if kind == "content" and not entry["_content_kind"]:
                entry["content"] = content
                entry["_content_kind"] = True
        all_results.extend(merged.values())
    for entry in all_results:
        entry.pop("_content_kind", None)
        entry["vector_kinds"] = sorted(set(entry["vector_kinds"]))
    all_results.sort(key=lambda item: item["score"], reverse=True)
    limit = top_k if len(collection_names) == 1 else top_k * len(collection_names)
    return all_results[:limit]


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
    return await owned_workspace_ids(db, user)


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
    if payload.workspace_id:
        await owned_workspace(db, payload.workspace_id, current_user)

    service = ConversationService(db, user_id=current_user.id)
    session_id = payload.session_id or payload.conversation_id
    session = await service.get_session(session_id) if session_id else None
    if session_id and session is None:
        raise HTTPException(404, "Learning session not found")
    mode = "simple" if payload.mode == "explain" else payload.mode
    scope = _scope_from_payload(payload, session, default_mode=settings.SCOPE_DEFAULT_MODE)
    scope_explicit = bool(
        payload.scope_mode or payload.scope_config or payload.scope_override
    )
    if session is None:
        session = await service.create_session(
            workspace_id=payload.workspace_id,
            document_ids=payload.document_ids,
            mode=mode,
            strict_sources=payload.strict_sources,
            scope_mode=scope.mode,
            scope_config=scope.config_payload(),
        )
    else:
        changes: dict = {
            "selected_document_ids": list(payload.document_ids),
            "preferred_mode": mode,
            "strict_sources": payload.strict_sources,
        }
        if payload.workspace_id is not None:
            changes["workspace_id"] = payload.workspace_id
        if scope_explicit:
            changes["scope_mode"] = scope.mode
            changes["scope_config"] = scope.config_payload()
        session = await service.update_session(
            session.id,
            **changes,
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
    resolver = ScopeResolver(db, user=current_user, owned_workspaces=owned_ids)
    profile = await LearnerProfileService(db, current_user.id).build(
        workspace_id=payload.workspace_id,
        question=payload.question,
        owned_workspace_ids=owned_ids,
    )
    resolved_scope = await resolver.resolve(
        query=payload.question,
        scope=scope,
        session=session,
        workspace_id=payload.workspace_id,
        profile=profile,
    )
    profile_hints = [
        point.title for point in (profile.weak_points or []) if point.title
    ]
    difficulty_preference = await LearnerProfileService(
        db, current_user.id
    ).difficulty_preference(
        workspace_id=payload.workspace_id,
        knowledge_point_ids=[point.knowledge_point_id for point in (profile.weak_points or [])],
    )
    from app.rag.query.analyzer import analyze_query
    from app.rag.query.router import plan_query

    query_plan = plan_query(
        analyze_query(payload.question),
        mode="practice" if mode in {"practice", "exam"} else "explain",
    )
    metadata_filter = (
        {"exclude_content_types": query_plan.exclude_content_types}
        if query_plan.exclude_content_types
        else None
    )

    retrieval_service = HybridRetrievalService(db, _vector_recall)
    outcome = await retrieve_with_expansion(
        service=retrieval_service,
        resolver=resolver,
        base_request=RetrievalRequest(
            query=payload.question,
            scope=resolved_scope,
            owned_workspace_ids=owned_ids,
            session_id=session.id,
            user_message_id=user_msg.id,
            profile_hints=profile_hints,
            preference_content_types=difficulty_preference.preferred_content_types,
            difficulty_range=(
                (difficulty_preference.min_difficulty, difficulty_preference.max_difficulty)
                if difficulty_preference.min_difficulty and difficulty_preference.max_difficulty
                else None
            ),
            metadata_filter=metadata_filter,
            vector_top_k=settings.RAG_VECTOR_TOP_K,
            keyword_top_k=settings.RAG_KEYWORD_TOP_K,
            selected_top_k=settings.RAG_SELECTED_TOP_K,
            supported_threshold=settings.RAG_SUPPORTED_THRESHOLD,
            second_threshold=settings.RAG_SECOND_THRESHOLD,
            limited_threshold=settings.RAG_LIMITED_THRESHOLD,
        ),
        initial_scope=resolved_scope,
        input_scope=scope,
        max_rounds=settings.SCOPE_MAX_EXPANSION_ROUNDS,
        latency_budget_ms=settings.SCOPE_EXPANSION_LATENCY_BUDGET_MS,
    )
    retrieval = outcome.result
    resolved_scope = outcome.scope
    expansion_trace = outcome.trace
    await db.commit()

    from app.rag.retrieval.orchestrator import prepare_retrieval_context

    prepared = await prepare_retrieval_context(
        db,
        retrieval.items,
        question=payload.question,
        mode="practice" if mode in {"practice", "exam"} else "explain",
        plan=query_plan,
        serializer=serialize_source,
    )
    source_items = prepared.sources
    context_chunks = prepared.context_chunks
    context_notes = prepared.notes
    history = await service.messages(session.id)
    history_lines = [
        f"{item.role}：{item.content}" for item in history[-settings.CONVERSATION_HISTORY_LIMIT:]
    ]
    profile_block = format_profile_block(profile)
    memory_service = LearningMemoryService(db, current_user.id)
    recall = await memory_service.recall(
        question=payload.question, workspace_id=payload.workspace_id
    )
    memory_block = format_memory_block(recall.hits)
    await memory_service.record_usage([hit.memory for hit in recall.hits])
    await db.commit()

    full_prompt = build_learning_prompt(
        question=payload.question,
        mode=mode,
        context_blocks=context_chunks,
        profile_block=profile_block,
        memory_block=memory_block,
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
            yield event({
                "scope": {
                    "mode": resolved_scope.mode,
                    "workspace_ids": list(resolved_scope.hard_workspace_ids),
                    "document_ids": list(resolved_scope.hard_document_ids),
                    "expansion_rounds": retrieval.expansion_rounds,
                    "expanded_scope": retrieval.expanded_scope,
                    "dropped_ids": list(resolved_scope.dropped_ids),
                    "resolution_reason": list(resolved_scope.resolution_reason),
                    "expansion": expansion_trace,
                }
            })
            retrievers_ok = retrieval_available(
                vector_succeeded=retrieval.vector_succeeded,
                keyword_succeeded=retrieval.keyword_succeeded,
            )
            stale_reasons = _index_stale_reasons(resolved_scope.hard_workspace_ids)
            yield event({
                "evidence": {
                    "status": retrieval.evidence_status,
                    "vector_succeeded": retrieval.vector_succeeded,
                    "keyword_succeeded": retrieval.keyword_succeeded,
                    "degradation_reason": retrieval.degradation_reason,
                    "top_score": round(retrieval.top_score, 4),
                    "answer_policy": "source_first",
                    "model_fallback": retrievers_ok and retrieval.evidence_status != "supported",
                    "scope_mode": resolved_scope.mode,
                    "expanded_scope": retrieval.expanded_scope,
                    "profile_injected": bool(profile_block),
                    "memory_hits": [hit.memory.id for hit in recall.hits],
                    "memory_degraded_reason": recall.degraded_reason,
                    # 新增可选键：索引指纹不一致时提示重建，不改变既有字段语义
                    "index_stale": bool(stale_reasons),
                    "index_stale_reasons": stale_reasons,
                    "query_intent": prepared.plan.analysis.intent,
                    "rerank_degraded": prepared.rerank_degraded,
                    "context_notes": context_notes[:5],
                    "retrieval_run_id": retrieval.run_id,
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
                used_memory_ids=[hit.memory.id for hit in recall.hits],
                profile_summary=profile_block[:500],
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

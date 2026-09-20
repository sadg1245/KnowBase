"""阶段 3：chunk 富化——规则路径、LLM 路径、失败降级与补跑端点。"""

import unittest

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.deps import get_current_user, get_db
from app.main import app
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.rag.chunking.base import Chunk
from app.rag.enrichment import MetadataEnricher
from tests.support import create_user, create_workspace


def chunk(chunk_id: str, content: str, *, level: str = "child", content_type: str = "concept") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc",
        workspace_id="ws",
        content=content,
        chunk_level=level,
        content_type=content_type,
    )


class MetadataEnricherTests(unittest.IsolatedAsyncioTestCase):
    async def test_rule_path_fills_keywords_without_any_model_call(self):
        target = chunk("c1", "条件概率是指已知 B 发生时 A 发生的概率，用于贝叶斯推断。" * 3)
        calls: list[str] = []

        async def completion(prompt: str) -> str:
            calls.append(prompt)
            return "[]"

        enricher = MetadataEnricher(completion=completion, enabled=False)
        result = await enricher.enrich([target])

        self.assertEqual(result.enriched, 1)
        self.assertEqual(result.calls, 0)
        self.assertEqual(calls, [])
        self.assertTrue(target.metadata["keywords"])
        self.assertEqual(target.metadata["enrichment_status"], "skipped")

    async def test_llm_path_batches_and_overrides_rule_values(self):
        children = [chunk(f"c{i}", f"第 {i} 段讲条件概率与贝叶斯公式。") for i in range(3)]
        parents = [chunk("p1", "整节上下文", level="parent")]
        prompts: list[str] = []

        async def completion(prompt: str) -> str:
            prompts.append(prompt)
            payload = [
                {
                    "summary": f"摘要 {index}",
                    "subject": "概率论",
                    "knowledge_points": [f"知识点 {index}"],
                    "keywords": ["条件概率"],
                    "difficulty": 3,
                    "content_type": "definition",
                    "questions": [f"什么是条件概率 {index}？", f"如何推导 {index}？"],
                }
                for index in range(3)
            ]
            import json

            return json.dumps(payload, ensure_ascii=False)

        enricher = MetadataEnricher(completion=completion, enabled=True, batch_size=10)
        result = await enricher.enrich(children + parents)

        self.assertEqual(result.calls, 1)          # 3 个 child 合并为一次调用
        self.assertEqual(len(prompts), 1)
        self.assertIn("不可信学习材料", prompts[0])
        self.assertEqual(result.enriched, 3)
        self.assertEqual(result.skipped, 1)        # parent 不调用模型
        self.assertEqual(children[0].content_type, "definition")
        self.assertEqual(children[0].metadata["summary"], "摘要 0")
        self.assertEqual(children[0].metadata["difficulty"], 3)
        self.assertEqual(len(children[0].metadata["questions"]), 2)
        self.assertEqual(children[0].metadata["enrichment_status"], "ready")
        self.assertEqual(parents[0].metadata["enrichment_status"], "skipped")

    async def test_invalid_llm_output_marks_failed_and_keeps_rule_values(self):
        children = [chunk("c1", "条件概率是指已知 B 发生时 A 发生的概率。")]

        async def broken(prompt: str) -> str:
            return "not json at all"

        enricher = MetadataEnricher(completion=broken, enabled=True)
        result = await enricher.enrich(children)

        self.assertEqual(result.failed, 1)
        self.assertEqual(children[0].metadata["enrichment_status"], "failed")
        self.assertTrue(children[0].metadata["keywords"])       # 规则兜底仍生效
        self.assertIn("enrichment_error", children[0].metadata)

    async def test_count_mismatch_is_treated_as_failure(self):
        children = [chunk("c1", "甲。"), chunk("c2", "乙。")]

        async def short(prompt: str) -> str:
            return '[{"summary": "only one"}]'

        enricher = MetadataEnricher(completion=short, enabled=True)
        result = await enricher.enrich(children)

        self.assertEqual(result.failed, 2)
        self.assertTrue(all(item.metadata["enrichment_status"] == "failed" for item in children))


class EnrichDocumentEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(self.db, self.user, name="富化", slug="enrich")
        self.document = Document(
            workspace_id=self.workspace.id,
            filename="notes.md",
            file_path="notes.md",
            file_type="md",
            status="ready",
            document_type="notes",
        )
        self.db.add(self.document)
        await self.db.flush()
        self.db.add(DocumentChunk(
            id="doc_chunk_0",
            workspace_id=self.workspace.id,
            document_id=self.document.id,
            source_file="notes.md",
            chunk_index=0,
            content="条件概率是指已知 B 发生时 A 发生的概率。",
            tokenized_content="条件概率",
            chunk_level="child",
            content_type="concept",
            enrichment_status="failed",
        ))
        await self.db.commit()

        async def database():
            yield self.db
            await self.db.commit()

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    async def test_enrich_endpoint_retries_failed_chunks_with_rules(self):
        response = await self.client.post(f"/api/documents/{self.document.id}/enrich")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["enriched"], 1)
        self.assertEqual(body["failed"], 0)
        row = (
            await self.db.execute(select(DocumentChunk).where(DocumentChunk.id == "doc_chunk_0"))
        ).scalar_one()
        self.assertEqual(row.enrichment_status, "skipped")   # 未开启 LLM 时规则富化
        self.assertTrue(row.keywords)

    async def test_enrich_endpoint_rejects_foreign_document(self):
        other = await create_user(self.db, username="other-enrich")
        foreign = Document(
            workspace_id=(await create_workspace(self.db, other, name="别人的", slug="other-enrich")).id,
            filename="x.md",
            file_path="x.md",
            file_type="md",
            status="ready",
        )
        self.db.add(foreign)
        await self.db.commit()

        response = await self.client.post(f"/api/documents/{foreign.id}/enrich")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

"""阶段 2：分类、结构树与知识单元必须落库，并且重新索引是幂等的。"""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.collector.pipeline import DocumentPipeline
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.models.document import Document
from app.models.rag import KnowledgeUnit, StructureNode
from tests.support import create_user, create_workspace

SOURCE = """# 第 1 章 概率论

## 1.1 定义

条件概率是指已知 B 发生时 A 发生的概率。

$$P(A|B)=\\frac{P(AB)}{P(B)}$$

## 1.2 例题

例 1：抛两次硬币，求条件概率。

```python
p = ab / b
```

习题：请自行推导贝叶斯公式。
"""


class _FakeEmbedding:
    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeVectorStore:
    async def replace_document(self, **_kwargs):
        return None


class _Splitter:
    def split_documents(self, documents):
        return [
            {"content": doc["content"], "metadata": dict(doc.get("metadata") or {})}
            for doc in documents
        ]


class DocumentAnalysisPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await run_compat_migrations(conn)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "chapter.md")
        Path(self.path).write_text(SOURCE, encoding="utf-8")
        async with self.sessions() as db:
            user = await create_user(db)
            workspace = await create_workspace(db, user, name="结构", slug="analysis-persist")
            document = Document(
                workspace_id=workspace.id,
                filename="chapter.md",
                file_path=self.path,
                file_type="md",
                status="pending",
            )
            db.add(document)
            await db.commit()
            self.document_id = document.id
            self.workspace_id = workspace.id

    async def asyncTearDown(self):
        self.tmp.cleanup()
        await self.engine.dispose()

    async def _run(self):
        pipeline = DocumentPipeline(_FakeEmbedding(), _FakeVectorStore(), _Splitter())
        async with self.sessions() as db:
            return await pipeline.process_document(
                self.document_id, self.path, "md", self.workspace_id, db
            )

    async def _document(self) -> Document:
        async with self.sessions() as db:
            return (
                await db.execute(select(Document).where(Document.id == self.document_id))
            ).scalar_one()

    async def _nodes(self) -> list[StructureNode]:
        async with self.sessions() as db:
            return list((
                await db.execute(
                    select(StructureNode)
                    .where(StructureNode.document_id == self.document_id)
                    .order_by(StructureNode.order_index)
                )
            ).scalars().all())

    async def _units(self) -> list[KnowledgeUnit]:
        async with self.sessions() as db:
            return list((
                await db.execute(
                    select(KnowledgeUnit)
                    .where(KnowledgeUnit.document_id == self.document_id)
                    .order_by(KnowledgeUnit.id)
                )
            ).scalars().all())

    async def test_pipeline_persists_classification_structure_and_units(self):
        result = await self._run()

        self.assertEqual(result["status"], "ready")
        document = await self._document()
        self.assertEqual(document.document_type, "textbook")
        self.assertGreaterEqual(document.classification_confidence or 0, 0.8)
        self.assertTrue(document.classification_meta.get("reasons"))

        nodes = await self._nodes()
        kinds = [node.node_type for node in nodes]
        self.assertEqual(kinds[0], "document")
        self.assertIn("chapter", kinds)
        self.assertEqual(kinds.count("section"), 2)
        self.assertIn("formula", kinds)
        self.assertTrue(all(node.workspace_id == self.workspace_id for node in nodes))
        chapter = next(node for node in nodes if node.node_type == "chapter")
        self.assertEqual(chapter.title, "第 1 章 概率论")
        self.assertEqual(chapter.parent_node_id, nodes[0].id)

        units = await self._units()
        types = {unit.unit_type for unit in units}
        self.assertIn("chapter", types)
        self.assertIn("section", types)
        self.assertIn("definition", types)
        self.assertIn("formula", types)
        self.assertIn("code", types)
        chapter_unit = next(unit for unit in units if unit.unit_type == "chapter")
        section_units = [unit for unit in units if unit.unit_type == "section"]
        self.assertTrue(all(unit.parent_id == chapter_unit.id for unit in section_units))
        definition = next(unit for unit in units if unit.unit_type == "definition")
        self.assertEqual(definition.section, "1.1 定义")
        self.assertTrue(all(unit.content.strip() for unit in units))

    async def test_reindex_rebuilds_rows_without_duplicates(self):
        await self._run()
        first_nodes = {node.id for node in await self._nodes()}
        first_units = {unit.id for unit in await self._units()}

        await self._run()
        second_nodes = await self._nodes()
        second_units = await self._units()

        # 重新索引是整篇重建：id 稳定、数量不翻倍
        self.assertEqual({node.id for node in second_nodes}, first_nodes)
        self.assertEqual({unit.id for unit in second_units}, first_units)
        self.assertEqual(len(second_nodes), len(first_nodes))
        self.assertEqual(len(second_units), len(first_units))


if __name__ == "__main__":
    unittest.main()

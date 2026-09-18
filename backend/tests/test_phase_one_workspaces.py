"""第一阶段：学习领域、知识库扩展字段、统计聚合与封面。"""

import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.config import settings
from app.models.base import Base
from app.models.document import Document
from app.models.learning import KnowledgePoint, StudyActivity
from tests.support import create_user, create_workspace, login, wire_test_app


NOW = datetime.now(timezone.utc)


def png_bytes(width: int = 32, height: int = 32) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 120, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


class KnowledgeBaseAndDomainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.alice = await create_user(self.db, username="alice")
        self.bob = await create_user(self.db, username="bob")
        await self.db.commit()

        self.media = tempfile.TemporaryDirectory()
        self.original_media_dir = settings.MEDIA_DIR
        settings.MEDIA_DIR = self.media.name

        self.app, self.client = wire_test_app(self.sessions, self.db)
        self.alice_headers = await login(self.client, "alice")
        self.bob_headers = await login(self.client, "bob")

    async def asyncTearDown(self):
        settings.MEDIA_DIR = self.original_media_dir
        self.app.dependency_overrides.clear()
        if hasattr(self.app.state, "session_factory"):
            del self.app.state.session_factory
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()
        self.media.cleanup()

    async def test_learning_domain_crud_and_conflicts(self):
        created = await self.client.post(
            "/api/learning-domains", headers=self.alice_headers,
            json={"name": "数学", "description": "分析与代数", "color": "#123456"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        domain_id = created.json()["id"]

        duplicate = await self.client.post(
            "/api/learning-domains", headers=self.alice_headers, json={"name": "数学"}
        )
        self.assertEqual(duplicate.status_code, 409)

        # 同一名称在不同用户下允许存在。
        other = await self.client.post(
            "/api/learning-domains", headers=self.bob_headers, json={"name": "数学"}
        )
        self.assertEqual(other.status_code, 201, other.text)

        listed = await self.client.get("/api/learning-domains", headers=self.alice_headers)
        self.assertEqual([row["name"] for row in listed.json()], ["数学"])

        renamed = await self.client.patch(
            f"/api/learning-domains/{domain_id}",
            headers=self.alice_headers, json={"name": "高等数学"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["name"], "高等数学")

        foreign = await self.client.patch(
            f"/api/learning-domains/{domain_id}",
            headers=self.bob_headers, json={"name": "偷来的"},
        )
        self.assertEqual(foreign.status_code, 404)

        workspace = await self.client.post(
            "/api/workspaces", headers=self.alice_headers,
            json={"name": "线性代数", "domain_id": domain_id},
        )
        self.assertEqual(workspace.status_code, 201, workspace.text)
        self.assertEqual(workspace.json()["domain"], "高等数学")

        detail = await self.client.get("/api/learning-domains", headers=self.alice_headers)
        self.assertEqual(detail.json()[0]["workspace_count"], 1)

        deleted = await self.client.delete(
            f"/api/learning-domains/{domain_id}", headers=self.alice_headers
        )
        self.assertEqual(deleted.status_code, 204)
        after = await self.client.get(
            f"/api/workspaces/{workspace.json()['id']}", headers=self.alice_headers
        )
        self.assertEqual(after.json()["domain"], "未分类")
        self.assertIsNone(after.json()["domain_id"])
        kept = await self.client.get("/api/workspaces", headers=self.alice_headers)
        self.assertEqual(len(kept.json()), 1)

    async def test_workspace_slug_is_unique_per_owner_only(self):
        first = await self.client.post(
            "/api/workspaces", headers=self.alice_headers, json={"name": "Algorithms"}
        )
        second = await self.client.post(
            "/api/workspaces", headers=self.alice_headers, json={"name": "Algorithms"}
        )
        self.assertEqual(first.json()["slug"], "algorithms")
        self.assertEqual(second.json()["slug"], "algorithms-1")

        bob = await self.client.post(
            "/api/workspaces", headers=self.bob_headers, json={"name": "Algorithms"}
        )
        self.assertEqual(bob.status_code, 201, bob.text)
        self.assertEqual(bob.json()["slug"], "algorithms")

    async def test_learning_status_and_archive_are_independent(self):
        created = await self.client.post(
            "/api/workspaces", headers=self.alice_headers,
            json={"name": "状态", "learning_status": "learning"},
        )
        workspace_id = created.json()["id"]
        self.assertEqual(created.json()["learning_status"], "learning")
        self.assertFalse(created.json()["archived"])

        completed = await self.client.put(
            f"/api/workspaces/{workspace_id}", headers=self.alice_headers,
            json={"learning_status": "completed"},
        )
        self.assertEqual(completed.json()["learning_status"], "completed")
        self.assertFalse(completed.json()["archived"])

        archived = await self.client.put(
            f"/api/workspaces/{workspace_id}", headers=self.alice_headers,
            json={"archived": True},
        )
        self.assertTrue(archived.json()["archived"])
        self.assertEqual(archived.json()["learning_status"], "completed")

        default_list = await self.client.get("/api/workspaces", headers=self.alice_headers)
        self.assertEqual(default_list.json(), [])
        archived_list = await self.client.get(
            "/api/workspaces?archived_only=true", headers=self.alice_headers
        )
        self.assertEqual([row["id"] for row in archived_list.json()], [workspace_id])
        inclusive = await self.client.get(
            "/api/workspaces?include_archived=true", headers=self.alice_headers
        )
        self.assertEqual([row["id"] for row in inclusive.json()], [workspace_id])

        invalid = await self.client.put(
            f"/api/workspaces/{workspace_id}", headers=self.alice_headers,
            json={"learning_status": "nonsense"},
        )
        self.assertEqual(invalid.status_code, 422)

    async def test_workspace_statistics_come_from_real_records(self):
        created = await self.client.post(
            "/api/workspaces", headers=self.alice_headers, json={"name": "统计"}
        )
        workspace_id = created.json()["id"]

        self.db.add_all([
            Document(workspace_id=workspace_id, filename="a.pdf", file_path="a.pdf", file_type=".pdf"),
            Document(workspace_id=workspace_id, filename="b.pdf", file_path="b.pdf", file_type=".pdf"),
        ])
        self.db.add_all([
            KnowledgePoint(workspace_id=workspace_id, title="A", mastery=0.4),
            KnowledgePoint(workspace_id=workspace_id, title="B", mastery=0.8),
        ])
        self.db.add_all([
            StudyActivity(
                user_id=self.alice.id, workspace_id=workspace_id, activity_type="document_read",
                title="阅读", duration_seconds=600, occurred_at=NOW - timedelta(days=1),
            ),
            StudyActivity(
                user_id=self.alice.id, workspace_id=workspace_id, activity_type="mastery_changed",
                title="内部证据", duration_seconds=0, occurred_at=NOW,
            ),
        ])
        await self.db.commit()

        detail = await self.client.get(
            f"/api/workspaces/{workspace_id}", headers=self.alice_headers
        )
        payload = detail.json()
        self.assertEqual(payload["document_count"], 2)
        self.assertEqual(payload["knowledge_point_count"], 2)
        self.assertEqual(payload["learning_progress"], 60)
        # 只有真实学习活动会计入最近学习时间，内部证据不算。
        self.assertTrue(payload["last_studied_at"])

        empty = await self.client.post(
            "/api/workspaces", headers=self.alice_headers, json={"name": "空"}
        )
        empty_detail = await self.client.get(
            f"/api/workspaces/{empty.json()['id']}", headers=self.alice_headers
        )
        self.assertEqual(empty_detail.json()["document_count"], 0)
        self.assertEqual(empty_detail.json()["knowledge_point_count"], 0)
        self.assertEqual(empty_detail.json()["learning_progress"], 0)
        self.assertIsNone(empty_detail.json()["last_studied_at"])

    async def test_cover_upload_url_replace_and_cleanup(self):
        created = await self.client.post(
            "/api/workspaces", headers=self.alice_headers,
            json={"name": "封面", "cover_url": "https://example.com/cover.png"},
        )
        workspace_id = created.json()["id"]
        self.assertEqual(created.json()["cover_kind"], "url")
        self.assertEqual(created.json()["cover_url"], "https://example.com/cover.png")

        uploaded = await self.client.post(
            f"/api/workspaces/{workspace_id}/cover",
            headers=self.alice_headers,
            files={"file": ("cover.png", png_bytes(), "image/png")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["cover_kind"], "upload")
        relative = uploaded.json()["cover_url"].removeprefix("/api/media/")
        stored = os.path.join(self.media.name, relative)
        self.assertTrue(os.path.isfile(stored))

        served = await self.client.get(uploaded.json()["cover_url"])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["content-type"], "image/png")

        cleared = await self.client.delete(
            f"/api/workspaces/{workspace_id}/cover", headers=self.alice_headers
        )
        self.assertEqual(cleared.json()["cover_kind"], "none")
        self.assertIsNone(cleared.json()["cover_url"])
        self.assertFalse(os.path.isfile(stored))

        again = await self.client.post(
            f"/api/workspaces/{workspace_id}/cover",
            headers=self.alice_headers,
            files={"file": ("cover.png", png_bytes(), "image/png")},
        )
        stored = os.path.join(
            self.media.name, again.json()["cover_url"].removeprefix("/api/media/")
        )
        deleted = await self.client.delete(
            f"/api/workspaces/{workspace_id}", headers=self.alice_headers
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(os.path.isfile(stored))

    async def test_cover_upload_rejects_bad_input_and_foreign_workspaces(self):
        created = await self.client.post(
            "/api/workspaces", headers=self.alice_headers, json={"name": "校验"}
        )
        workspace_id = created.json()["id"]

        not_an_image = await self.client.post(
            f"/api/workspaces/{workspace_id}/cover",
            headers=self.alice_headers,
            files={"file": ("cover.png", b"not an image", "image/png")},
        )
        self.assertEqual(not_an_image.status_code, 422)

        mismatch = await self.client.post(
            f"/api/workspaces/{workspace_id}/cover",
            headers=self.alice_headers,
            files={"file": ("cover.gif", png_bytes(), "image/gif")},
        )
        self.assertEqual(mismatch.status_code, 422)

        too_small = await self.client.post(
            f"/api/workspaces/{workspace_id}/cover",
            headers=self.alice_headers,
            files={"file": ("tiny.png", png_bytes(4, 4), "image/png")},
        )
        self.assertEqual(too_small.status_code, 422)

        traversal = await self.client.post(
            f"/api/workspaces/{workspace_id}/cover",
            headers=self.alice_headers,
            files={"file": ("../../evil.png", png_bytes(), "image/png")},
        )
        self.assertEqual(traversal.status_code, 200, traversal.text)
        stored = traversal.json()["cover_url"].removeprefix("/api/media/")
        self.assertNotIn("..", stored)
        self.assertEqual(len(os.path.basename(stored)), len("0123456789abcdef" * 2) + 4)

        foreign = await self.client.post(
            f"/api/workspaces/{workspace_id}/cover",
            headers=self.bob_headers,
            files={"file": ("cover.png", png_bytes(), "image/png")},
        )
        self.assertEqual(foreign.status_code, 404)

        insecure_url = await self.client.put(
            f"/api/workspaces/{workspace_id}", headers=self.alice_headers,
            json={"cover_url": "http://example.com/cover.png"},
        )
        self.assertEqual(insecure_url.status_code, 422)

    async def test_foreign_workspace_updates_and_deletes_are_not_found(self):
        workspace = await create_workspace(
            self.db, self.bob, name="Bob KB", slug="bob-kb"
        )
        await self.db.commit()
        for method, payload in (("put", {"name": "stolen"}), ("delete", None)):
            with self.subTest(method=method):
                response = await self.client.request(
                    method, f"/api/workspaces/{workspace.id}",
                    headers=self.alice_headers, json=payload,
                )
                self.assertEqual(response.status_code, 404)

    async def test_avatar_upload_replaces_and_clears_local_files(self):
        uploaded = await self.client.post(
            "/api/me/avatar",
            headers=self.alice_headers,
            files={"file": ("me.png", png_bytes(), "image/png")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["avatar_kind"], "upload")
        first = os.path.join(
            self.media.name, uploaded.json()["avatar_url"].removeprefix("/api/media/")
        )
        self.assertTrue(os.path.isfile(first))

        replaced = await self.client.post(
            "/api/me/avatar",
            headers=self.alice_headers,
            files={"file": ("me.png", png_bytes(48, 48), "image/png")},
        )
        second = os.path.join(
            self.media.name, replaced.json()["avatar_url"].removeprefix("/api/media/")
        )
        self.assertTrue(os.path.isfile(second))
        self.assertFalse(os.path.isfile(first))

        rejected = await self.client.post(
            "/api/me/avatar",
            headers=self.alice_headers,
            files={"file": ("me.txt", b"plain text", "text/plain")},
        )
        self.assertEqual(rejected.status_code, 422)

        cleared = await self.client.delete("/api/me/avatar", headers=self.alice_headers)
        self.assertEqual(cleared.json()["avatar_kind"], "none")
        self.assertFalse(os.path.isfile(second))


if __name__ == "__main__":
    unittest.main()

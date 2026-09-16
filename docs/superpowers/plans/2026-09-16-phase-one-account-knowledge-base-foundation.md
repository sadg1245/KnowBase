# Personal Account and Knowledge Base Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single-account login experience backed by multi-user ownership, expand compatible workspaces into personal knowledge bases with domains, covers, statistics, and editable tags, and migrate existing installations safely with Alembic.

**Architecture:** Keep `Workspace`, `workspaces`, and `/api/workspaces` as compatibility contracts while adding explicit `User`, `LearningPreference`, and `LearningDomain` models. Resolve the authenticated user in FastAPI dependencies, pass that identity into every private query and service, and keep Feishu's service token bound to the single configured user. Replace startup DDL with an Alembic baseline plus an inspected legacy bootstrap path, then add focused APIs and minimal additions to the existing React/Ant Design screens.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, SQLite/PostgreSQL, Pillow, pytest/unittest, React 18, TypeScript, Ant Design, Axios, Node test runner, Vite.

**Spec:** `docs/superpowers/specs/2026-09-16-phase-one-account-knowledge-base-foundation-design.md`

## Global Constraints

- Only one account can be created through the first-version product UI; database keys, ownership constraints, and queries must support future multiple users.
- Keep internal `Workspace`, `workspaces`, and `/api/workspaces` compatibility; all user-visible copy remains “知识库”.
- Do not redesign existing pages or navigation; add only the approved fields and account actions using existing Ant Design patterns.
- Never authorize from a client-supplied `user_id`; identity comes from a validated bearer token or a service token mapped to the single user.
- Return 404 for resources outside the current user's scope.
- Preserve existing record IDs, document paths, Chroma collection names, conversations, and learning records during migration.
- Local covers and avatars accept allow-listed image formats only, use random server filenames, and never expose arbitrary filesystem paths.
- External image URLs must use HTTPS and are stored without server-side fetching.
- Every behavior change follows red-green-refactor; run the named failing test before editing production code.
- Do not stage or modify the user's unrelated untracked files: `PROMPT.docx`, `PROMPT.md`, `index.html`, or `vcpp-build-tools-page.png`.

---

### Task 1: Introduce Alembic and Replace Startup Schema Mutation

**Files:**
- Create: `alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/20260916_0001_current_schema_baseline.py`
- Create: `backend/app/core/migration_bootstrap.py`
- Create: `backend/tests/test_alembic_migrations.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `backend/requirements.txt`
- Modify: `backend/app/main.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: `python -m app.core.migration_bootstrap` exits successfully only when the database is at Alembic head.
- Produces: Alembic baseline revision `20260916_0001` representing the complete schema before account-foundation changes.
- Consumes: `app.models.Base.metadata` and `settings.DATABASE_URL`.

- [ ] **Step 1: Add migration tests that fail because Alembic is not configured**

```python
# backend/tests/test_alembic_migrations.py
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]


class AlembicMigrationTests(unittest.TestCase):
    def run_bootstrap(self, database_path: Path) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database_path.as_posix()}"}
        return subprocess.run(
            [sys.executable, "-m", "app.core.migration_bootstrap"],
            cwd=ROOT / "backend",
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_empty_database_upgrades_to_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fresh.db"
            result = self.run_bootstrap(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            inspector = inspect(create_engine(f"sqlite:///{path.as_posix()}"))
            self.assertIn("alembic_version", inspector.get_table_names())
            self.assertIn("workspaces", inspector.get_table_names())
            self.assertIn("report_suggestions", inspector.get_table_names())

    def test_unknown_legacy_shape_is_rejected_without_stamping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.db"
            engine = create_engine(f"sqlite:///{path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY)"))
            result = self.run_bootstrap(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("legacy schema validation failed", result.stderr.lower())
            self.assertNotIn("alembic_version", inspect(engine).get_table_names())
```

- [ ] **Step 2: Run the migration tests and verify the expected import/configuration failure**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_alembic_migrations.py -q`

Expected: FAIL because `app.core.migration_bootstrap`, Alembic configuration, or the baseline revision does not exist.

- [ ] **Step 3: Add dependencies and Alembic async configuration**

Add `alembic==1.13.3` to both dependency manifests, run `uv lock`, and configure `backend/alembic/env.py` to:

```python
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401
from app.config import settings
from app.models.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=settings.DATABASE_URL.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(
            lambda sync_connection: context.configure(
                connection=sync_connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=sync_connection.dialect.name == "sqlite",
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda _: context.run_migrations())
    await engine.dispose()
```

Call `asyncio.run(run_async_migrations())` in online mode. Keep `alembic.ini` at repository root with `script_location = backend/alembic` and prepend `backend` to `sys.path` in `env.py` based on the file location, not the process working directory.

- [ ] **Step 4: Generate and review the current-schema baseline**

Create a temporary empty database and run:

```powershell
$env:DATABASE_URL='sqlite+aiosqlite:///./data/sqlite/alembic-baseline.db'
uv run alembic revision --autogenerate -m "current schema baseline" --rev-id 20260916_0001
```

The baseline `upgrade()` must create every table currently registered in `Base.metadata`, including all phase-six columns and indexes now supplied by `run_compat_migrations`. The baseline `downgrade()` must drop tables in reverse foreign-key order. Remove the temporary database after reviewing the generated revision.

- [ ] **Step 5: Implement inspected legacy bootstrap**

Implement `backend/app/core/migration_bootstrap.py` with these exact public functions:

```python
CURRENT_BASELINE = "20260916_0001"
LEGACY_CORE_COLUMNS = {
    "workspaces": {"id", "name", "slug", "learning_goal", "domain", "archived"},
    "documents": {"id", "workspace_id", "filename", "file_path", "tags"},
    "conversations": {"id", "user_id", "workspace_id", "content"},
    "user_profiles": {"id", "display_name", "password_hash", "timezone_name"},
}


def validate_legacy_schema(connection) -> list[str]:
    """Return human-readable missing-table/column errors; return [] only for the accepted current legacy shape."""


def bootstrap_and_upgrade() -> None:
    """Create a fresh schema or validate+stamp the accepted legacy schema, then upgrade to head."""
```

Use a synchronous URL derived from `DATABASE_URL` only for inspection. Behavior:

1. No user tables: run `alembic upgrade head`.
2. `alembic_version` exists: run `alembic upgrade head`.
3. Legacy tables without `alembic_version`: validate `LEGACY_CORE_COLUMNS`; on any error print `Legacy schema validation failed: <comma-separated validation errors>` to stderr and exit non-zero; otherwise stamp `20260916_0001` and upgrade.

The module's `if __name__ == "__main__"` calls `bootstrap_and_upgrade()`.

- [ ] **Step 6: Remove runtime DDL from the API lifespan and wire deployment commands**

Remove `Base.metadata.create_all()` and `run_compat_migrations()` from `backend/app/main.py`. Keep `run_compat_migrations` temporarily importable only until its data/index operations have equivalents in the baseline; mark it deprecated and remove the startup call.

Update local instructions to run:

```bash
cd backend
python -m app.core.migration_bootstrap
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Update the backend Docker command to run the same bootstrap before Uvicorn. Ensure the worker and Feishu services depend on a healthy backend so only one service performs the schema upgrade during normal Compose startup. In `docker-compose.dev.yml`, preserve reload behavior after the bootstrap command.

- [ ] **Step 7: Run migration tests and existing migration compatibility tests**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_alembic_migrations.py backend/tests/test_phase_four_models.py backend/tests/test_phase_five_models.py backend/tests/test_phase_six_models.py -q`

Expected: PASS. If old tests explicitly call `run_compat_migrations`, migrate their fixture expectation to the matching Alembic revision instead of retaining startup DDL.

- [ ] **Step 8: Commit the Alembic foundation**

```bash
git add alembic.ini backend/alembic backend/app/core/migration_bootstrap.py backend/app/main.py backend/tests/test_alembic_migrations.py backend/requirements.txt pyproject.toml uv.lock docker-compose.yml docker-compose.dev.yml README.md
git commit -m "feat: establish alembic migration baseline"
```

---

### Task 2: Add User, Learning Preference, and Single-Account Authentication

**Files:**
- Create: `backend/app/models/user.py`
- Create: `backend/app/schemas/account.py`
- Create: `backend/tests/test_account_api.py`
- Create: `backend/alembic/versions/20260916_0002_accounts.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/auth.py`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/routes/auth.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Modify: `backend/tests/test_regressions.py`

**Interfaces:**
- Produces: `User`, `LearningPreference`, and later-imported `LearningDomain` ORM classes.
- Produces: `decode_token(token: str) -> str | None`.
- Produces: `get_current_user(request, db) -> User` and `get_service_or_current_user(request, db) -> User` dependencies.
- Produces: `/api/auth/status`, `/api/auth/setup`, `/api/auth/login`, `/api/auth/logout`, `/api/me`, `/api/me/preferences`.

- [ ] **Step 1: Write failing account API and token-subject tests**

```python
# backend/tests/test_account_api.py
class AccountApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_creates_only_one_account_and_login_returns_subject(self):
        first = await setup(
            AccountSetup(username="owner", password="correct horse battery staple", display_name="学习者"),
            self.db,
        )
        self.assertEqual(decode_token(first.token), first.user.id)
        with self.assertRaises(HTTPException) as duplicate:
            await setup(AccountSetup(username="other", password="another valid password"), self.db)
        self.assertEqual(duplicate.exception.status_code, 409)
        logged_in = await login(AccountLogin(username="owner", password="correct horse battery staple"), self.db)
        self.assertEqual(logged_in.user.username, "owner")

    async def test_client_cannot_authenticate_as_missing_or_inactive_subject(self):
        request = bearer_request(create_token("missing-user"))
        with self.assertRaises(HTTPException) as missing:
            await get_current_user(request, self.db)
        self.assertEqual(missing.exception.status_code, 401)
```

Also update the regression token test to assert `decode_token(create_token("personal-vault")) == "personal-vault"` and `decode_token(tampered) is None`.

- [ ] **Step 2: Run the account tests and verify they fail for missing models/schemas**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_account_api.py backend/tests/test_regressions.py -q`

Expected: FAIL because the account models, schemas, `decode_token`, and current-user dependency do not exist.

- [ ] **Step 3: Define account models and request/response schemas**

Implement these model contracts in `backend/app/models/user.py`:

```python
class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=_uuid)
    username = Column(String(80), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=True)
    display_name = Column(String(80), nullable=False, default="学习者")
    avatar_kind = Column(String(10), nullable=False, default="none")
    avatar_value = Column(String(1024), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)


class LearningPreference(Base):
    __tablename__ = "learning_preferences"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    daily_goal_minutes = Column(Integer, nullable=False, default=25)
    daily_review_target = Column(Integer, nullable=False, default=10)
    weekly_goal_days = Column(Integer, nullable=False, default=5)
    timezone_name = Column(String(100), nullable=False, default="Asia/Shanghai")
    preferred_mode = Column(String(30), nullable=False, default="explain")
    reminder_time = Column(String(5), nullable=True, default="20:00")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)
```

Define Pydantic schemas `AccountSetup`, `AccountLogin`, `UserResponse`, `SessionResponse`, `UserUpdate`, `LearningPreferenceResponse`, and `LearningPreferenceUpdate`. Username is 3–80 characters and matches `^[A-Za-z0-9_.-]+$`; passwords are 8–200 characters; nickname is 1–80 characters.

- [ ] **Step 4: Add the account migration with legacy profile preservation**

Create revision `20260916_0002` with `down_revision = "20260916_0001"`. It must:

1. Create `users` and `learning_preferences`.
2. Read the earliest `user_profiles` row when present.
3. Insert a user using the same ID, username `owner`, existing `password_hash`, `display_name`, and timestamps.
4. Insert the preference row from the existing goal, timezone, mode, and reminder fields.
5. If no profile exists, insert an `owner` row with `password_hash = NULL` and default preferences; setup completes this placeholder rather than inserting a second user.

The downgrade keeps `user_profiles` intact and drops only the two new tables.

- [ ] **Step 5: Return the token subject and add current-user dependencies**

Refactor `backend/app/core/auth.py`:

```python
def decode_token(token: str) -> str | None:
    """Return a valid, unexpired subject; return None for malformed, tampered, or expired tokens."""


def verify_token(token: str) -> bool:
    return decode_token(token) is not None
```

In `backend/app/api/deps.py`, require an `Authorization` header whose value starts with `Bearer `, parse the remaining token, load `User` by subject, verify `is_active`, and return 401 for every failure. `get_service_or_current_user` uses constant-time comparison for `SERVICE_TOKEN`; when it matches, it loads the only active user and returns 503 if no configured user exists. Never return an unrestricted sentinel identity.

- [ ] **Step 6: Replace middleware-only authentication with route dependencies**

Remove `protect_private_api` from `backend/app/main.py`. Add router-level dependencies or explicit `Depends(get_current_user)` to all private routers, leaving only health, auth status, setup, and login public. Keep `logout` authenticated and return HTTP 204.

Set authentication on by default. Remove `AUTH_ENABLED` from normal production behavior; if tests need bypass, use FastAPI dependency overrides rather than a runtime flag. Add startup validation that rejects the default `JWT_SECRET` outside an explicit `ENVIRONMENT=development|test` setting.

- [ ] **Step 7: Implement setup, login, current user, and preferences**

Setup must run in one transaction, lock/check the user count, and either complete the single placeholder user or reject with 409. Login uses a uniform 401 message for unknown usernames and bad passwords. `/api/me` and preference routes operate only on `current_user.id`.

Keep `/api/auth/status` compatible with existing `enabled` and `configured` keys while adding `requires_setup`. Do not return password hashes.

- [ ] **Step 8: Run account tests and auth regressions**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_account_api.py backend/tests/test_regressions.py -q`

Expected: PASS with no warnings or leaked credential values.

- [ ] **Step 9: Commit the account foundation**

```bash
git add backend/app/models/user.py backend/app/models/__init__.py backend/app/schemas/account.py backend/app/core/auth.py backend/app/api/deps.py backend/app/api/routes/auth.py backend/app/main.py backend/app/config.py backend/alembic/versions/20260916_0002_accounts.py backend/tests/test_account_api.py backend/tests/test_regressions.py .env.example
git commit -m "feat: add single-account authentication foundation"
```

---

### Task 3: Migrate Ownership and Enforce Private Data Scopes

**Files:**
- Create: `backend/app/services/ownership.py`
- Create: `backend/tests/test_ownership_isolation.py`
- Create: `backend/alembic/versions/20260916_0003_data_ownership.py`
- Modify: `backend/app/models/workspace.py`
- Modify: `backend/app/models/chat.py`
- Modify: `backend/app/models/conversation.py`
- Modify: `backend/app/models/learning.py`
- Modify: `backend/app/models/assessment.py`
- Modify: `backend/app/api/routes/workspaces.py`
- Modify: `backend/app/api/routes/documents.py`
- Modify: `backend/app/api/routes/search.py`
- Modify: `backend/app/api/routes/settings.py`
- Modify: `backend/app/api/routes/learning.py`
- Modify: `backend/app/api/routes/learning_insights.py`
- Modify: `backend/app/api/routes/chat_sessions.py`
- Modify: `backend/app/api/routes/assessments.py`
- Modify: `backend/app/services/activity_service.py`
- Modify: `backend/app/services/assessment_service.py`
- Modify: `backend/app/services/assessment_workflows.py`
- Modify: `backend/app/services/conversation_service.py`
- Modify: `backend/app/services/dashboard_service.py`
- Modify: `backend/app/services/document_jobs.py`
- Modify: `backend/app/services/goal_service.py`
- Modify: `backend/app/services/hybrid_retrieval.py`
- Modify: `backend/app/services/learning_content.py`
- Modify: `backend/app/services/report_service.py`
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/services/study_session_service.py`
- Modify: `backend/app/services/weakness_service.py`
- Modify: `backend/app/collector/tasks.py`
- Modify: `backend/app/collector/pipeline.py`
- Create: `backend/tests/account_fixtures.py`
- Modify: `backend/tests/test_activity_sessions.py`
- Modify: `backend/tests/test_assessment_api.py`
- Modify: `backend/tests/test_assessment_service.py`
- Modify: `backend/tests/test_content_filter.py`
- Modify: `backend/tests/test_conversation_service.py`
- Modify: `backend/tests/test_dashboard_service.py`
- Modify: `backend/tests/test_document_jobs.py`
- Modify: `backend/tests/test_document_management.py`
- Modify: `backend/tests/test_flashcard_api.py`
- Modify: `backend/tests/test_goal_service.py`
- Modify: `backend/tests/test_hybrid_retrieval.py`
- Modify: `backend/tests/test_learning_content.py`
- Modify: `backend/tests/test_learning_insights_api.py`
- Modify: `backend/tests/test_phase_five_models.py`
- Modify: `backend/tests/test_phase_four_models.py`
- Modify: `backend/tests/test_phase_two_models.py`
- Modify: `backend/tests/test_phase_two_parsers.py`
- Modify: `backend/tests/test_report_ai_service.py`
- Modify: `backend/tests/test_report_service.py`
- Modify: `backend/tests/test_review_service.py`
- Modify: `backend/tests/test_review_summary.py`
- Modify: `backend/tests/test_weakness_service.py`

**Interfaces:**
- Produces: `require_workspace(db, user_id, workspace_id) -> Workspace`.
- Produces: `require_document(db, user_id, document_id) -> Document`.
- Produces: `workspace_ids_for_user(user_id: str) -> Select[tuple[str]]`, returning a SQLAlchemy subquery selecting owned workspace IDs.
- Consumes: `User.id` from Task 2.

- [ ] **Step 1: Write failing two-user isolation tests across representative resource families**

```python
# backend/tests/test_ownership_isolation.py
class OwnershipIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_user_cannot_read_or_mutate_first_users_resources(self):
        owner, stranger = await self.users()
        workspace, document, point, card, session, activity = await self.private_graph(owner)

        for operation in (
            lambda: require_workspace(self.db, stranger.id, workspace.id),
            lambda: require_document(self.db, stranger.id, document.id),
            lambda: get_owned_knowledge_point(self.db, stranger.id, point.id),
            lambda: ConversationService(self.db, stranger.id).get_session(session.id),
        ):
            with self.assertRaises(HTTPException) as hidden:
                await operation()
            self.assertEqual(hidden.exception.status_code, 404)

        export = await export_learning_data(self.db, owner)
        self.assertEqual({row["id"] for row in export["knowledge_bases"]}, {workspace.id})
        stranger_export = await export_learning_data(self.db, stranger)
        self.assertEqual(stranger_export["knowledge_bases"], [])

    async def test_client_user_id_is_never_used_as_authority(self):
        owner, stranger = await self.users()
        request = ChatRequest(question="hello", user_id=owner.id)
        resolved = authenticated_chat_identity(request, stranger)
        self.assertEqual(resolved, stranger.id)
```

Add tests for list/read/update/delete on workspaces and documents, chat sessions, cards/reviews, assessments, dashboard/report/export, and search scope. Each foreign ID must produce 404 or an empty list as appropriate.

- [ ] **Step 2: Run isolation tests and verify cross-user access currently succeeds or defaults to `default`**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_ownership_isolation.py -q`

Expected: FAIL for missing ownership columns/helpers and existing unscoped queries.

- [ ] **Step 3: Add ownership columns and foreign keys in ORM models**

Add non-null `Workspace.owner_id -> users.id`. Convert existing string `user_id` columns in `Conversation`, `ChatSession`, and `ChatFeedback` to 36-character user foreign keys. Add direct non-null `user_id` to `StudyActivity`, `StudySession`, `LearningGoal`, and `ReportSuggestion`; add it to `LearningNote` and `RetrievalRun` when they can exist without a workspace. Records with a required workspace continue to use workspace ownership as the authoritative relationship.

Replace global/partial unique indexes that would collide across users:

- Workspace: unique `(owner_id, slug)`.
- Active study session context: unique `(user_id, context_type, context_id)` where active.
- Global learning goal metric: unique `(user_id, metric)` where global.
- Workspace learning goal metric remains unique per workspace.
- Report suggestion snapshot: include `user_id`.
- Chat feedback: unique `(user_id, message_id)`.

- [ ] **Step 4: Add Alembic ownership migration and invariant checks**

Revision `20260916_0003` must:

1. Select the single migrated user ID and fail if it is absent or ambiguous.
2. Add nullable ownership columns.
3. Backfill every legacy row to that user, replacing legacy `default` and Feishu string IDs where those values were previously used as authorization identifiers.
4. Validate `COUNT(*) WHERE user_id/owner_id IS NULL = 0` for required columns.
5. Rebuild affected SQLite tables in batch mode to add foreign keys and non-null constraints.
6. Replace global indexes with per-user indexes.
7. Preserve all record IDs, workspace IDs, file paths, and relationship values.

Add a fixture database containing at least one row in each affected table and assert pre/post counts and IDs in `test_alembic_migrations.py`.

- [ ] **Step 5: Implement central ownership helpers**

```python
# backend/app/services/ownership.py
async def require_workspace(db: AsyncSession, user_id: str, workspace_id: str) -> Workspace:
    row = await db.scalar(select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.owner_id == user_id,
    ))
    if row is None:
        raise HTTPException(404, "Knowledge base not found")
    return row


async def require_document(db: AsyncSession, user_id: str, document_id: str) -> Document:
    row = await db.scalar(
        select(Document)
        .join(Workspace, Workspace.id == Document.workspace_id)
        .where(Document.id == document_id, Workspace.owner_id == user_id)
    )
    if row is None:
        raise HTTPException(404, "Document not found")
    return row
```

Add these focused helpers where routes cannot express the join clearly: `require_knowledge_point(db, user_id, point_id)`, `require_flashcard(db, user_id, card_id)`, `require_quiz_set(db, user_id, quiz_set_id)`, `require_quiz_run(db, user_id, run_id)`, `require_quiz_question(db, user_id, question_id)`, and `require_message(db, user_id, message_id)`. Each returns its ORM object and raises the same scoped 404; none returns an authorization boolean.

- [ ] **Step 6: Thread `current_user.id` through routes and services**

Update every private route signature to accept `current_user: User = Depends(get_current_user)` or `Depends(get_service_or_current_user)` for approved service-token endpoints. Required examples:

```python
@router.get("")
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await db.execute(
        select(Workspace)
        .where(Workspace.owner_id == current_user.id)
        .order_by(Workspace.created_at.desc())
    )
    return rows.scalars().all()
```

```python
service = ConversationService(db, current_user.id)
```

Search/chat must validate the optional workspace and document scope before sending IDs to RAG. Dashboard, reports, goals, review, weakness, assessments, and export must receive a `user_id` parameter and filter all base queries. Background document jobs receive the authenticated owner ID in their queued payload and revalidate the workspace/document relationship when the job starts.

- [ ] **Step 7: Remove client authority fields and defaults**

Remove `user_id` from new `ConversationCreate` and `ChatRequest` inputs. If compatibility parsing keeps the key temporarily, mark it excluded/deprecated and overwrite it from `current_user.id`. Remove every `user_id="default"` service default and every hard-coded `"default"` query.

Update frontend calls and the Feishu client so they no longer rely on a user ID body field. Do not expose `user_id` in responses unless needed for compatibility; it must always equal the authenticated owner.

- [ ] **Step 8: Run isolation tests, targeted domain tests, then the complete backend suite**

Run:

```bash
PYTHONPATH=backend python -m pytest backend/tests/test_ownership_isolation.py backend/tests/test_document_management.py backend/tests/test_conversation_service.py backend/tests/test_assessment_api.py backend/tests/test_learning_insights_api.py -q
PYTHONPATH=backend python -m pytest backend/tests -q
```

Expected: PASS. Any fixture that omitted a user must explicitly create one; do not make `owner_id` nullable or add an implicit production owner to satisfy tests.

- [ ] **Step 9: Commit ownership isolation**

```bash
git add backend/app/models backend/app/api backend/app/services backend/app/collector backend/app/schemas backend/alembic/versions/20260916_0003_data_ownership.py backend/tests
git commit -m "feat: enforce private data ownership"
```

---

### Task 4: Add Learning Domains and Knowledge Base Metadata/Statistics

**Files:**
- Create: `backend/app/api/routes/learning_domains.py`
- Create: `backend/app/schemas/knowledge_base.py`
- Create: `backend/tests/test_knowledge_base_foundation.py`
- Create: `backend/alembic/versions/20260916_0004_knowledge_base_metadata.py`
- Modify: `backend/app/models/user.py`
- Modify: `backend/app/models/workspace.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/routes/workspaces.py`
- Modify: `backend/app/schemas/schemas.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `LearningDomain` ORM model and domain CRUD under `/api/learning-domains`.
- Produces: knowledge-base response fields `domain`, `domain_id`, `cover_url`, `learning_status`, `knowledge_point_count`, `learning_progress`, and `last_studied_at`.
- Consumes: authenticated ownership from Task 3.

- [ ] **Step 1: Write failing domain and aggregate tests**

```python
class KnowledgeBaseFoundationTests(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_response_contains_real_learning_aggregates(self):
        user = await self.user("owner")
        domain = LearningDomain(user_id=user.id, name="编程", color="#1f7a8c")
        workspace = Workspace(owner_id=user.id, name="Python", slug="python", domain=domain)
        self.db.add_all([domain, workspace])
        await self.db.flush()
        self.db.add_all([
            KnowledgePoint(workspace_id=workspace.id, title="A", mastery=0.25),
            KnowledgePoint(workspace_id=workspace.id, title="B", mastery=0.75),
            StudyActivity(user_id=user.id, workspace_id=workspace.id, activity_type="document_read", title="Read"),
        ])
        await self.db.flush()

        item = await get_workspace(workspace.id, self.db, user)
        self.assertEqual(item["domain"], "编程")
        self.assertEqual(item["knowledge_point_count"], 2)
        self.assertEqual(item["learning_progress"], 0.5)
        self.assertIsNotNone(item["last_studied_at"])

    async def test_deleting_domain_unclassifies_but_does_not_delete_workspace(self):
        user = await self.user("owner")
        domain = LearningDomain(user_id=user.id, name="编程", color="#1f7a8c")
        workspace = Workspace(owner_id=user.id, name="Python", slug="python", domain=domain)
        self.db.add_all([domain, workspace])
        await self.db.flush()
        await delete_learning_domain(domain.id, self.db, user)
        await self.db.refresh(workspace)
        self.assertIsNone(workspace.domain_id)
        self.assertIsNotNone(await self.db.get(Workspace, workspace.id))
```

Also test per-user domain-name uniqueness, cross-user 404, manual learning statuses, archived filtering, and per-user slug uniqueness.

- [ ] **Step 2: Run the tests and verify missing model/field failures**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_knowledge_base_foundation.py -q`

Expected: FAIL because `LearningDomain`, workspace fields, and aggregate responses do not exist.

- [ ] **Step 3: Add models and migration**

Define `LearningDomain` with `(user_id, name)` uniqueness. Add `domain_id`, `cover_kind`, `cover_value`, and `learning_status` to `Workspace`; add a check constraint or request validation for the four allowed statuses.

Revision `20260916_0004` must create domains, convert each non-empty/non-`未分类` legacy `Workspace.domain` value into one per-user domain, and backfill `domain_id`. Keep the legacy `domain` column for response compatibility. Replace the global slug unique constraint with `(owner_id, slug)`.

- [ ] **Step 4: Implement domain CRUD with ownership semantics**

Create schemas:

```python
class LearningDomainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    color: str = Field(default="#1f7a8c", pattern=r"^#[0-9A-Fa-f]{6}$")


class LearningDomainUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
```

Normalize surrounding whitespace. Map same-user duplicate names to 409. Delete in a transaction after setting that user's affected workspaces to `domain_id = NULL`; cross-user IDs return 404.

- [ ] **Step 5: Extend workspace schemas and CRUD**

Add `domain_id` and `learning_status` to create/update schemas. Set `owner_id=current_user.id` at creation. `_ensure_unique_slug` must filter by owner. Validate a supplied domain with both `LearningDomain.id` and `LearningDomain.user_id`.

Default list behavior returns `archived=false`; accept `include_archived: bool = False`. Preserve the existing response keys and add new ones.

- [ ] **Step 6: Build aggregate query without N+1 queries**

Use grouped subqueries for document count, knowledge-point count/average mastery, and maximum activity time. The response contract is:

```python
{
    "document_count": int(document_count or 0),
    "knowledge_point_count": int(point_count or 0),
    "learning_progress": float(average_mastery or 0.0),
    "last_studied_at": last_studied_at,
}
```

Use `StudyActivity.occurred_at`, not `created_at`, for recent learning. Ensure every aggregate is scoped through the selected user-owned workspace.

- [ ] **Step 7: Run knowledge-base and existing workspace/document tests**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_knowledge_base_foundation.py backend/tests/test_document_management.py backend/tests/test_learning_content.py -q`

Expected: PASS.

- [ ] **Step 8: Commit domains and knowledge-base metadata**

```bash
git add backend/app/models backend/app/api/routes/learning_domains.py backend/app/api/routes/workspaces.py backend/app/schemas backend/app/main.py backend/alembic/versions/20260916_0004_knowledge_base_metadata.py backend/tests/test_knowledge_base_foundation.py
git commit -m "feat: add learning domains and knowledge base metadata"
```

---

### Task 5: Add Safe Avatar and Knowledge Base Cover Storage

**Files:**
- Create: `backend/app/services/image_storage.py`
- Create: `backend/tests/test_image_storage.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/routes/auth.py`
- Modify: `backend/app/api/routes/workspaces.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/account.py`
- Modify: `backend/app/schemas/knowledge_base.py`
- Modify: `backend/requirements.txt`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.env.example`

**Interfaces:**
- Produces: `store_image(upload, namespace, owner_id) -> StoredImage`.
- Produces: `delete_managed_image(kind, value, namespace, owner_id) -> None`.
- Produces: `build_media_url(relative_path) -> str`, containing a short-lived path-scoped HMAC token.
- Produces: `/api/media/{namespace}/{owner_id}/{filename}?expires=<unix>&signature=<hmac>` through a constrained file response route.
- Consumes: `User.avatar_*` and `Workspace.cover_*`.

- [ ] **Step 1: Write failing image validation and lifecycle tests**

```python
class ImageStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_png_upload_uses_random_managed_name_and_replacement_removes_old_file(self):
        first = await store_image(self.png_upload("original.png"), "covers", self.user_id)
        self.assertNotIn("original", first.relative_path)
        self.assertTrue((self.root / first.relative_path).is_file())
        second = await store_image(self.png_upload("next.png"), "covers", self.user_id)
        delete_managed_image("upload", first.relative_path, "covers", self.user_id)
        self.assertFalse((self.root / first.relative_path).exists())
        self.assertTrue((self.root / second.relative_path).exists())

    async def test_disguised_non_image_and_http_url_are_rejected(self):
        with self.assertRaises(ImageValidationError):
            await store_image(self.upload(b"not an image", "fake.png", "image/png"), "covers", self.user_id)
        with self.assertRaises(ValueError):
            validate_external_image_url("http://internal.example/cover.png")
```

Add API tests for cross-user cover upload, avatar update, clear, replacement cleanup, knowledge-base deletion cleanup, expired media URLs, path/signature mismatch, and path traversal.

- [ ] **Step 2: Run image tests and verify missing storage failures**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_image_storage.py -q`

Expected: FAIL because the storage service and routes do not exist.

- [ ] **Step 3: Add Pillow and image configuration**

Add `Pillow==11.0.0` to dependency manifests and lock. Add:

```python
MEDIA_DIR: str = "./data/media"
IMAGE_MAX_SIZE_MB: int = 5
IMAGE_MAX_PIXELS: int = 20_000_000
```

to settings and `.env.example`. Create media directories during normal startup without creating database schema.

- [ ] **Step 4: Implement the focused storage service**

```python
@dataclass(frozen=True)
class StoredImage:
    relative_path: str
    mime_type: str


async def store_image(upload: UploadFile, namespace: Literal["avatars", "covers"], owner_id: str) -> StoredImage:
    """Validate size and decoded format, then atomically move a random file into the managed owner directory."""


def delete_managed_image(kind: str, value: str | None, namespace: str, owner_id: str) -> None:
    """Delete only a resolved path contained by MEDIA_DIR/namespace/owner_id."""


def validate_external_image_url(value: str) -> str:
    """Return a normalized HTTPS URL or raise ValueError."""


def build_media_url(relative_path: str, *, now: int | None = None) -> str:
    """Return a one-hour URL signed with JWT_SECRET over path and expiry."""
```

Allow decoded JPEG, PNG, WEBP, and GIF. Set `Image.MAX_IMAGE_PIXELS`, call `verify()`, reopen the file before save, and use `uuid4().hex` with a server-selected extension. Write to a temporary file in the destination directory and atomically rename.

- [ ] **Step 5: Add constrained media responses and upload endpoints**

Do not mount the entire data directory. Add a route that validates namespace, owner ID, a UUID-style filename, expiry, and a constant-time HMAC signature over `relative_path + "\n" + expires`. Resolve the path under `MEDIA_DIR`; return 404 for traversal/missing files and 403 for invalid or expired signatures. API responses call `build_media_url` so normal `<img>` elements can render local media without exposing the bearer token. A signature is valid only for the exact path and for at most one hour.

Add authenticated endpoints:

- `POST /api/me/avatar`
- `DELETE /api/me/avatar`
- `POST /api/workspaces/{workspace_id}/cover`
- `DELETE /api/workspaces/{workspace_id}/cover`

For replacement: store new file, update and flush database, then delete old managed file. On database failure, delete the newly stored file. URL updates use PATCH fields and never call the filesystem delete function for `kind=url`.

- [ ] **Step 6: Run image and workspace tests**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_image_storage.py backend/tests/test_knowledge_base_foundation.py -q`

Expected: PASS.

- [ ] **Step 7: Commit media support**

```bash
git add backend/app/services/image_storage.py backend/app/api/routes/auth.py backend/app/api/routes/workspaces.py backend/app/config.py backend/app/main.py backend/app/schemas backend/tests/test_image_storage.py backend/requirements.txt pyproject.toml uv.lock .env.example
git commit -m "feat: support profile avatars and knowledge base covers"
```

---

### Task 6: Normalize Editable Document and Knowledge Point Tags

**Files:**
- Create: `backend/app/services/tag_service.py`
- Create: `backend/tests/test_editable_tags.py`
- Modify: `backend/app/schemas/schemas.py`
- Modify: `backend/app/schemas/learning.py`
- Modify: `backend/app/api/routes/documents.py`
- Modify: `backend/app/api/routes/learning.py`
- Modify: `backend/app/services/learning_content.py`
- Modify: `backend/app/models/document.py`
- Modify: `backend/app/models/learning.py`
- Create: `backend/alembic/versions/20260916_0005_tag_sources.py`

**Interfaces:**
- Produces: `normalize_tags(values: Sequence[str], *, max_tags=30, max_length=50) -> list[str]`.
- Produces: authenticated document and knowledge-point updates that share tag validation.
- Consumes: ownership helpers from Task 3.

- [ ] **Step 1: Write failing normalization and manual-preservation tests**

```python
class EditableTagTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_tags_trims_deduplicates_and_preserves_order(self):
        self.assertEqual(normalize_tags([" Python ", "", "python", "算法"]), ["Python", "算法"])

    def test_normalize_tags_rejects_too_many_or_too_long_values(self):
        with self.assertRaises(TagValidationError):
            normalize_tags([str(index) for index in range(31)])
        with self.assertRaises(TagValidationError):
            normalize_tags(["x" * 51])

    async def test_regenerating_learning_content_preserves_manual_document_tags(self):
        document = await self.document(tags=["人工标签"])
        await apply_generated_learning_content(document, {"tags": ["AI 标签"], "summary": "summary"})
        self.assertEqual(document.tags, ["人工标签"])
```

Also test knowledge-point tag edits under correct ownership and a second user's 404.

- [ ] **Step 2: Run tag tests and verify missing service/preservation behavior**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_editable_tags.py -q`

Expected: FAIL because normalization is duplicated/partial and generated content can overwrite tags.

- [ ] **Step 3: Implement one tag normalizer**

Deduplicate case-insensitively with `casefold()` while preserving the first spelling and order. Raise a domain-specific exception for non-strings, overlong values, or more than 30 normalized tags; map it to HTTP 422 in routes.

- [ ] **Step 4: Use the service in document and knowledge-point updates**

Replace local document normalization with `normalize_tags`. Add `tags: list[str] | None` to `KnowledgePointUpdate` and update only after loading the point through the current user's ownership scope.

Add `tags_source` (`ai | manual`) to both `Document` and `KnowledgePoint`. Revision `20260916_0005` adds non-null `tags_source` columns with server default `ai`; existing rows remain `ai` because the legacy schema contains no reliable edit audit. Every document or knowledge-point tag update API sets `tags_source = "manual"`, including an explicit update to an empty tag list. AI generation sets `tags_source = "ai"` only when it is allowed to populate tags.

- [ ] **Step 5: Protect manual tags during regeneration**

Centralize generated learning assignment in a function with this behavior:

```python
if not entity.tags or entity.tags_source != "manual":
    entity.tags = normalize_tags(generated.get("tags", []))
    entity.tags_source = "ai"
```

All other generated learning fields continue updating normally. An explicit future overwrite option is out of scope.

- [ ] **Step 6: Run tag and learning-content tests**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_editable_tags.py backend/tests/test_document_management.py backend/tests/test_learning_content.py -q`

Expected: PASS.

- [ ] **Step 7: Commit editable tags**

```bash
git add backend/app/services/tag_service.py backend/app/services/learning_content.py backend/app/api/routes/documents.py backend/app/api/routes/learning.py backend/app/schemas backend/app/models backend/alembic/versions/20260916_0005_tag_sources.py backend/tests/test_editable_tags.py
git commit -m "feat: preserve user-edited learning tags"
```

---

### Task 7: Extend the Existing Frontend Without Redesigning It

**Files:**
- Create: `frontend/src/features/account/session.ts`
- Create: `frontend/src/features/knowledge/knowledgeBaseForms.ts`
- Create: `frontend/tests/accountSession.test.ts`
- Create: `frontend/tests/knowledgeBaseForms.test.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/pages/Workspaces.tsx`
- Modify: `frontend/src/pages/KnowledgeBase.tsx`
- Modify: `frontend/src/components/knowledge/KnowledgePointManager.tsx`
- Modify: `frontend/src/styles/app.css`
- Modify: `frontend/tests/documentScope.test.ts`
- Modify: `frontend/tests/goalEditor.test.tsx`
- Modify: `frontend/tests/knowledgeBaseDetail.test.tsx`
- Modify: `frontend/tests/learningChatPresets.test.ts`
- Modify: `frontend/tests/practiceComponents.test.tsx`
- Modify: `frontend/tests/practiceScope.test.ts`
- Modify: `frontend/tests/quickQuestion.test.tsx`
- Modify: `frontend/tests/uploadWorkspaceSelection.test.ts`
- Modify: `frontend/tests/workspaceDeletion.test.ts`

**Interfaces:**
- Produces: typed account, preference, domain, cover, and knowledge-base API clients.
- Produces: pure session and form adapters testable without DOM redesign.
- Consumes: APIs from Tasks 2, 4, 5, and 6.

- [ ] **Step 1: Write failing pure frontend behavior tests**

```typescript
// frontend/tests/accountSession.test.ts
test('logout removes the personal session before returning to login', () => {
  const storage = new Map<string, string>([['knowbase_session', 'token']]);
  clearSession({ removeItem: key => storage.delete(key) });
  assert.equal(storage.has('knowbase_session'), false);
});

// frontend/tests/knowledgeBaseForms.test.ts
test('workspace form payload keeps compatibility names and new metadata', () => {
  assert.deepEqual(toWorkspacePayload({
    name: 'Python', description: '', learningGoal: '完成项目',
    domainId: 'domain-1', learningStatus: 'learning', coverUrl: '',
  }), {
    name: 'Python', description: '', learning_goal: '完成项目',
    domain_id: 'domain-1', learning_status: 'learning',
  });
});
```

Add tests for setup/login state selection, avatar/cover URL presentation, archived list toggle, tag-string parsing, and unchanged Chinese “知识库” copy.

- [ ] **Step 2: Run frontend tests and verify missing modules/types**

Run: `cd frontend && npm test`

Expected: FAIL for missing session/form adapters and API fields.

- [ ] **Step 3: Extend API types and calls**

Add types `CurrentUser`, `LearningPreference`, `LearningDomain`, `LearningStatus`, and extended `Workspace`. Add calls:

```typescript
getAuthStatus, setupAccount, loginAccount, logoutAccount, getCurrentUser, updateCurrentUser,
uploadAvatar, deleteAvatar, getLearningPreferences, updateLearningPreferences,
getLearningDomains, createLearningDomain, updateLearningDomain, deleteLearningDomain,
uploadWorkspaceCover, deleteWorkspaceCover
```

Retain `getWorkspaces`, `createWorkspace`, and `updateKnowledgeBase` names for compatibility. Ensure fetch-based streaming uses the same token helper as Axios.

- [ ] **Step 4: Update the existing authentication shell**

Keep the current full-screen lock/setup shell and visual treatment. When `requires_setup` is true, show username, password, and nickname; otherwise show username and password. Store only the access token, fetch `/api/me` after authentication, and add a logout action to the existing account/avatar area. A 401 event clears the session once and returns to the login state without a reload loop.

- [ ] **Step 5: Add profile fields to the existing Settings page**

In the current learning-preference tab, add nickname and avatar above the existing goals/timezone/mode fields. Use `Upload` with `beforeUpload={() => false}` and an explicit save/upload action; show current avatar or initials. Keep all existing tabs and layout.

- [ ] **Step 6: Extend the existing knowledge-base cards and modal**

Keep the current responsive grid and card actions. Add a cover area within each card, domain badge, progress text/bar, knowledge-point count, status, and recent-study time without introducing a new page layout.

Extend the current create/edit modal with:

- domain select plus inline “新建领域” action,
- learning-status select,
- existing learning goal,
- cover upload or HTTPS URL,
- archive toggle only when editing.

Load domains once with the workspace list. Preserve current deletion confirmation and navigation behavior.

- [ ] **Step 7: Add knowledge-point tag editing in the existing manager**

Extend the existing point editor/modal with a tag input using comma-separated display or Ant Design tags mode. Reuse document tag parsing rules in `knowledgeBaseForms.ts`: trim, remove empties, case-insensitive dedupe, and cap visible client validation at 30 tags/50 characters. The backend remains authoritative.

- [ ] **Step 8: Run frontend tests and production build**

Run:

```bash
cd frontend
npm test
npm run build
```

Expected: all tests PASS and TypeScript/Vite build completes without errors.

- [ ] **Step 9: Commit the minimal frontend extension**

```bash
git add frontend/src frontend/tests
git commit -m "feat: expose personal knowledge base controls"
```

---

### Task 8: Bind Feishu, Complete Upgrade Regression, and Document Operations

**Files:**
- Create: `backend/tests/test_phase_one_acceptance.py`
- Modify: `feishu-bot/bot/commands.py`
- Modify: `feishu-bot/tests/test_commands.py`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml`

**Interfaces:**
- Produces: service-token requests scoped to the configured single account.
- Produces: one acceptance test proving migration preservation and key user flows.
- Consumes: all prior tasks.

- [ ] **Step 1: Write failing end-to-end acceptance contracts**

Create `backend/tests/test_phase_one_acceptance.py` with an ASGI client and dependency-overridden SQLite database. Cover this exact flow:

1. Setup owner account and log in.
2. Create a learning domain.
3. Create a knowledge base in that domain with learning goal/status.
4. Upload a cover.
5. Upload a small text/Markdown document through the existing endpoint.
6. Edit document tags and a knowledge-point's tags.
7. List knowledge bases and assert counts/progress/cover/domain.
8. Archive, include archived, restore, and delete the knowledge base.
9. Create a second database user directly and assert it cannot see or modify the owner's records.
10. Call an approved endpoint with the service token and assert it sees only the bound account.

- [ ] **Step 2: Run the acceptance test and verify any remaining integration gaps**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_phase_one_acceptance.py -q`

Expected: FAIL only for integration gaps left between completed tasks; do not weaken assertions.

- [ ] **Step 3: Bind Feishu requests to the service-token identity**

Ensure the bot sends only `X-KnowBase-Service-Token` for service calls and does not send a Feishu open ID as an application `user_id`. Preserve a Feishu sender ID only as non-authoritative audit metadata where an existing request schema supports it.

Backend service-token resolution must select the single active configured user. If there are zero or multiple active users, return 503 with a deployment error rather than querying the entire database.

- [ ] **Step 4: Finish operational documentation**

Document:

- backup of the SQLite/PostgreSQL database plus `data/uploads` and `data/media`,
- `python -m app.core.migration_bootstrap`,
- `alembic current`, `alembic history`, and `alembic upgrade head`,
- first account setup and the fact that registration closes afterward,
- required production `JWT_SECRET` and `SERVICE_TOKEN`,
- avatar/cover limits and media directory,
- recovery from a failed revision using backup restore,
- compatibility statement for `/api/workspaces` and internal Workspace naming.

Update old README text that claims startup `create_all`/compat migrations perform upgrades.

- [ ] **Step 5: Run the acceptance test again**

Run: `PYTHONPATH=backend python -m pytest backend/tests/test_phase_one_acceptance.py -q`

Expected: PASS.

- [ ] **Step 6: Run the complete verification matrix**

Run:

```bash
PYTHONPATH=backend python -m pytest backend/tests -q
cd frontend && npm test
cd frontend && npm run build
```

Then create two temporary databases and run:

```bash
DATABASE_URL=sqlite+aiosqlite:///./data/sqlite/verify-fresh.db python -m app.core.migration_bootstrap
DATABASE_URL=sqlite+aiosqlite:///./data/sqlite/verify-upgrade.db python -m app.core.migration_bootstrap
```

The second file must start from the checked-in legacy migration fixture, not another fresh database. Compare record counts, IDs, document paths, workspace IDs, and conversation links before and after upgrade. Delete only these two explicitly named verification databases after confirming their resolved paths are inside `data/sqlite`.

- [ ] **Step 7: Manually verify unchanged UI structure and critical workflows**

Using the existing desktop and mobile breakpoints, verify:

- dashboard and sidebar layout are unchanged,
- the sidebar still says “我的知识库”,
- setup/login/logout work,
- nickname/avatar/preferences save,
- knowledge-base create/edit/archive/delete work with domain and cover,
- document upload and retrieval work,
- learning chat streams successfully,
- knowledge-point and document tags remain editable,
- Feishu can query the bound user's knowledge base.

Record observed results in the final handoff; do not add screenshot artifacts unless a failure needs evidence.

- [ ] **Step 8: Commit acceptance and operations updates**

```bash
git add backend/tests/test_phase_one_acceptance.py feishu-bot README.md .env.example docker-compose.yml docker-compose.dev.yml
git commit -m "test: verify account knowledge base upgrade"
```

---

## Final Review Checklist

- [ ] Every new production function was introduced after a test failed for the intended missing behavior.
- [ ] `alembic current` reports head on a fresh database and on the upgraded legacy fixture.
- [ ] No production startup path calls `Base.metadata.create_all()` or `run_compat_migrations()`.
- [ ] No route or service uses a client-provided `user_id` as authorization.
- [ ] `rg -n 'user_id ?= ?"default"|select\(Workspace\)(?!.*owner_id)' backend/app` has no authorization bypasses; manually inspect regex false positives.
- [ ] Every workspace/document/point/card/chat/assessment/report/export route has an authenticated owner scope.
- [ ] Service-token access resolves exactly one active user.
- [ ] Existing record IDs, file paths, Chroma collection names, and conversation links survive migration.
- [ ] Covers and avatars reject disguised files, HTTP URLs, traversal, and cross-user access.
- [ ] Existing pages retain their layout and user-visible “知识库” terminology.
- [ ] Full backend tests, frontend tests, and production build pass with clean output.

# Phase Six Learning Dashboard and Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 执行状态：本计划的复选框未回填（TDD 步骤留痕），不代表未执行。
> 实际实现状态见 `docs/2026-09-18-knowbase-project-design.md` §13 与对应阶段测试。

**Goal:** Build a timezone-correct learning homepage, auditable activity ledger, measurable learning goals, and traceable day/week/month reports with cached AI advice.

**Architecture:** Extend the existing learning domain with append-only activity evidence, server-validated active study sessions, generic measurable goals, and cached report suggestions. Keep FastAPI routes thin by adding focused services; integrate activity creation at existing business transaction boundaries; expose typed React view models and small components for the dashboard and report UI.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2 async, Pydantic 2, SQLite/PostgreSQL, pytest/unittest, React 18, TypeScript 5.6, Ant Design 5, Node test runner, Vite 6.

**Spec:** `docs/superpowers/specs/2026-09-15-phase-six-learning-dashboard-reports-design.md`

## Global Constraints

- Preserve existing learning, review, assessment, chat, export, and legacy `GET /api/learning/report?days=` behavior.
- Store timestamps in UTC and construct natural day/week/month boundaries from `UserProfile.timezone_name` using IANA time zones.
- Count only visible, recently interactive page time; heartbeats run every 30 seconds and a server-accepted increment is capped at 60 seconds.
- New user-visible activities are exactly `document_read`, `question_asked`, `conversation_completed`, `card_created`, `review_completed`, `quiz_completed`, `knowledge_mastered`, and `goal_changed`.
- Internal `mastery_changed` and `weakness_changed` evidence is excluded from learning-frequency and recent-activity counts.
- Domain activity and the corresponding business result must be persisted in the same database transaction and use a stable idempotency key.
- AI failures must not block deterministic report statistics and must be stored as retryable failures, never replaced with fixed text presented as AI output.
- Do not infer historical source links, goal deadlines, mastery deltas, or weakness deltas that are absent from legacy records.
- Use tests before production changes for every task.

---

## File Structure

### Backend files to create

- `backend/app/schemas/insights.py`: request/response enums and validation for sessions, activities, goals, report periods, evidence, and suggestions.
- `backend/app/services/period_service.py`: timezone validation, natural-period UTC bounds, daily buckets, and previous-period bounds.
- `backend/app/services/activity_service.py`: typed idempotent activity append and compatibility mapping.
- `backend/app/services/study_session_service.py`: active-session lifecycle and settlement.
- `backend/app/services/goal_service.py`: goal persistence, compatibility synchronization, and progress calculation.
- `backend/app/services/dashboard_service.py`: today tasks, dashboard statistics, learning queues, streak, and explainable workspace ranking.
- `backend/app/services/report_service.py`: deterministic period aggregation, comparisons, and evidence queries.
- `backend/app/services/report_ai_service.py`: report snapshot hashing and cached AI suggestion generation.
- `backend/app/api/routes/learning_insights.py`: phase-six session, activity, goal, dashboard, report, evidence, and suggestion endpoints.
- `backend/tests/test_phase_six_models.py`: metadata and SQLite compatibility migration contracts.
- `backend/tests/test_period_service.py`: IANA period boundary tests.
- `backend/tests/test_activity_sessions.py`: activity idempotency and session lifecycle tests.
- `backend/tests/test_activity_integrations.py`: eight automatic domain-event integration tests.
- `backend/tests/test_goal_service.py`: goal validation, synchronization, history, and progress tests.
- `backend/tests/test_dashboard_service.py`: task generation, streak, queue, and recommendation tests.
- `backend/tests/test_report_service.py`: period metrics, comparisons, and evidence trace tests.
- `backend/tests/test_report_ai_service.py`: hash/cache/failure/retry tests.
- `backend/tests/test_learning_insights_api.py`: route validation and response-shape integration tests.

### Backend files to modify

- `backend/app/models/learning.py`: extend `UserProfile` and `StudyActivity`; add `StudySession`, `LearningGoal`, and `ReportSuggestion`.
- `backend/app/models/__init__.py`: register/export the three new models.
- `backend/app/core/migrations.py`: add phase-six columns, indexes, backfill, and default goals for SQLite upgrades.
- `backend/app/main.py`: register `learning_insights.router` before the broad legacy learning router.
- `backend/app/api/routes/learning.py`: call the activity/goal/dashboard/report services from legacy endpoints and preserve compatible responses.
- `backend/app/api/routes/chat_sessions.py`: append card-created events for cards created from messages.
- `backend/app/services/conversation_service.py`: append question and conversation-completed events at successful persistence points.
- `backend/app/services/review_service.py`: replace legacy review activities with typed review events and mastery evidence.
- `backend/app/services/assessment_service.py`: append one typed quiz event per submitted run and mastery evidence.
- `backend/app/services/assessment_workflows.py`: preserve task completion activity compatibility without double counting.
- `backend/app/services/weakness_service.py`: append weakness-change evidence only when the score/category changes.

### Frontend files to create

- `frontend/src/features/activity/activeStudySession.ts`: deterministic browser-agnostic active-time state machine.
- `frontend/src/hooks/useActiveStudySession.ts`: visibility/activity listeners and session API orchestration.
- `frontend/src/features/dashboard/dashboardViewModel.ts`: task grouping, progress, labels, and navigation decisions.
- `frontend/src/components/dashboard/QuickQuestion.tsx`: scoped quick-question entry.
- `frontend/src/components/dashboard/TodayPlan.tsx`: today-task list with derived/persisted actions.
- `frontend/src/components/dashboard/LearningQueue.tsx`: due cards, mistakes, and workspace recommendation panels.
- `frontend/src/components/dashboard/ActivityTimeline.tsx`: recent auditable activity list.
- `frontend/src/features/report/reportViewModel.ts`: period labels, metrics, comparisons, and chart data.
- `frontend/src/components/report/GoalEditor.tsx`: global and workspace goal form.
- `frontend/src/components/report/EvidenceDrawer.tsx`: cursor-paginated metric evidence.
- `frontend/src/components/report/ReportTrend.tsx`: accessible duration/frequency trend.
- `frontend/src/components/report/WeaknessChanges.tsx`: added/improved/worsened/resolved groups.
- `frontend/tests/activeStudySession.test.ts`: timer state-machine tests.
- `frontend/tests/dashboardViewModel.test.ts`: task and progress view-model tests.
- `frontend/tests/quickQuestion.test.tsx`: navigation-state and URL privacy test.
- `frontend/tests/reportViewModel.test.ts`: period/comparison/zero-baseline tests.
- `frontend/tests/goalEditor.test.tsx`: form boundaries and payload tests.
- `frontend/tests/learningInsightsComponents.test.tsx`: dashboard/report loading, empty, failure, and evidence states.

### Frontend files to modify

- `frontend/src/services/api.ts`: phase-six types and client functions.
- `frontend/src/pages/DocumentDetail.tsx`: activate document-reading session tracking.
- `frontend/src/pages/LearningChat.tsx`: consume quick-question navigation state and track conversation study sessions.
- `frontend/src/pages/Dashboard.tsx`: compose the new homepage sections.
- `frontend/src/pages/LearningReport.tsx`: natural-period report, goals, evidence, and AI advice.
- `frontend/src/pages/Settings.tsx`: timezone and weekly target compatibility fields plus report-goal link.
- `frontend/src/styles/app.css`: responsive dashboard/report/session states and accessible charts.
- `README.md`: document phase-six behavior and verification commands.

---

### Task 1: Persistence, Schemas, and Natural Periods

**Files:**
- Modify: `backend/app/models/learning.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/migrations.py`
- Create: `backend/app/schemas/insights.py`
- Create: `backend/app/services/period_service.py`
- Create: `backend/tests/test_phase_six_models.py`
- Create: `backend/tests/test_period_service.py`

**Interfaces:**
- Produces: `StudySession`, `LearningGoal`, `ReportSuggestion` ORM models.
- Produces: `PeriodBounds(period_type, timezone_name, local_start, local_end, utc_start, utc_end)`.
- Produces: `period_bounds(period_type: Literal['day','week','month'], anchor_date: date, timezone_name: str) -> PeriodBounds`.
- Produces: `previous_period(bounds: PeriodBounds) -> PeriodBounds` and `daily_buckets(bounds: PeriodBounds) -> list[date]`.

- [ ] **Step 1: Write failing metadata, validation, and migration tests**

```python
def test_phase_six_tables_and_activity_columns_are_registered(self):
    self.assertTrue({"study_sessions", "learning_goals", "report_suggestions"} <= set(Base.metadata.tables))
    activity = Base.metadata.tables["study_activities"]
    self.assertTrue({"event_key", "source_type", "source_id", "occurred_at", "schema_version"} <= set(activity.c))

def test_goal_scope_constraint_rejects_global_workspace_id(self):
    with self.assertRaises(ValidationError):
        GoalUpdate(scope_type="global", workspace_id="ws", metric="daily_minutes", target_value=25)

async def test_phase_six_sqlite_migration_is_idempotent_and_backfills_occurred_at(self):
    # Create legacy user_profiles/study_activities tables, run migration twice,
    # then assert the new columns and occurred_at == created_at.
```

```python
def test_shanghai_day_bounds_convert_to_utc():
    bounds = period_bounds("day", date(2026, 9, 15), "Asia/Shanghai")
    assert bounds.utc_start == datetime(2026, 9, 14, 16, tzinfo=timezone.utc)
    assert bounds.utc_end == datetime(2026, 9, 15, 16, tzinfo=timezone.utc)

def test_new_york_spring_dst_day_has_23_hours():
    bounds = period_bounds("day", date(2026, 3, 8), "America/New_York")
    assert bounds.utc_end - bounds.utc_start == timedelta(hours=23)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_phase_six_models.py backend/tests/test_period_service.py -v`

Expected: collection/import failure for missing phase-six models, schemas, and `period_service`.

- [ ] **Step 3: Add models, enums, constraints, and SQLite compatibility migration**

Implement the exact fields and constraints from the spec. Use nullable unique `StudyActivity.event_key`, indexed `(activity_type, occurred_at)`, and a partial unique index on `(StudySession.context_type, context_id)` with predicate `status = 'active'` for both SQLite and PostgreSQL. Add unique goal scope/metric and report-suggestion cache constraints. Add `timezone_name='Asia/Shanghai'` and `weekly_goal_days=5` compatibility defaults to `UserProfile`.

Migration order must be: add nullable activity columns, backfill `occurred_at`, create indexes, then create a global goal from the first profile only when no matching goal exists. Never infer workspace goals.

- [ ] **Step 4: Implement timezone-safe period helpers**

```python
def period_bounds(period_type: PeriodType, anchor_date: date, timezone_name: str) -> PeriodBounds:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise InvalidTimezone(timezone_name) from exc
    local_start = _local_start(period_type, anchor_date, zone)
    local_end = _next_start(period_type, local_start)
    return PeriodBounds(
        period_type=period_type,
        timezone_name=timezone_name,
        local_start=local_start,
        local_end=local_end,
        utc_start=local_start.astimezone(timezone.utc),
        utc_end=local_end.astimezone(timezone.utc),
    )
```

- [ ] **Step 5: Run focused and compatibility tests and verify GREEN**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_phase_six_models.py backend/tests/test_period_service.py backend/tests/test_phase_five_models.py backend/tests/test_phase_four_models.py -v`

Expected: all selected tests pass with no warnings introduced by phase-six code.

- [ ] **Step 6: Commit the persistence foundation**

```powershell
git add backend/app/models/learning.py backend/app/models/__init__.py backend/app/core/migrations.py backend/app/schemas/insights.py backend/app/services/period_service.py backend/tests/test_phase_six_models.py backend/tests/test_period_service.py
git commit -m "feat: add learning insight persistence foundation"
```

### Task 2: Idempotent Activity Ledger and Active Study Sessions

**Files:**
- Create: `backend/app/services/activity_service.py`
- Create: `backend/app/services/study_session_service.py`
- Create: `backend/app/api/routes/learning_insights.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_activity_sessions.py`
- Create: `backend/tests/test_learning_insights_api.py`

**Interfaces:**
- Consumes: `StudyActivity`, `StudySession`, `PeriodBounds`, phase-six session schemas.
- Produces: `append_activity(db, *, event_key, activity_type, title, workspace_id=None, source_type, source_id, duration_seconds=0, payload=None, occurred_at=None) -> StudyActivity`.
- Produces: `start_session(db, request, now)`, `heartbeat_session(db, session_id, sequence, now)`, `finish_session(db, session_id, sequence, now)`.
- Produces routes: `/study-sessions/start`, `/study-sessions/{id}/heartbeat`, `/study-sessions/{id}/finish`, and cursor-paginated `/activities`.

- [ ] **Step 1: Write failing activity idempotency and session lifecycle tests**

```python
async def test_append_activity_returns_existing_row_for_duplicate_event_key(db):
    first = await append_activity(db, event_key="activity:card:1", activity_type="card_created",
        title="创建卡片", source_type="flashcard", source_id="1")
    second = await append_activity(db, event_key="activity:card:1", activity_type="card_created",
        title="ignored", source_type="flashcard", source_id="1")
    assert second.id == first.id
    assert await db.scalar(select(func.count(StudyActivity.id))) == 1

async def test_heartbeat_counts_only_ordered_capped_active_intervals(db):
    session = await start_session(db, request, NOW)
    await heartbeat_session(db, session.id, 1, NOW + timedelta(seconds=30))
    await heartbeat_session(db, session.id, 1, NOW + timedelta(seconds=31))
    result = await heartbeat_session(db, session.id, 2, NOW + timedelta(seconds=150))
    assert result.active_seconds == 90  # first 30 + capped 60; duplicate adds zero
```

Also assert invalid context ownership, completed-session heartbeat 409 mapping, repeated finish returning one activity, zero-duration completion, and stale-session expiry.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_activity_sessions.py backend/tests/test_learning_insights_api.py -v`

Expected: missing service/router imports.

- [ ] **Step 3: Implement typed idempotent activity append**

Validate user-visible and internal event types centrally. On an existing `event_key`, return the existing row without modifying its title, payload, or duration. Map legacy `review` to `review_completed` and legacy `quiz` to `quiz_completed` only during aggregation, not by rewriting stored rows.

- [ ] **Step 4: Implement session start, heartbeat, finish, and expiry**

Use server timestamps for accumulation. `sequence <= last_sequence` is an idempotent no-op. Accepted delta is `min(60, max(0, now-last_heartbeat_at))`. Finish writes `document_read` for document context and `conversation_completed` for conversation context using `activity:study-session:<id>`; repeated finish returns the same activity.

- [ ] **Step 5: Add thin routes and route registration**

Translate service errors to 404/409/422 without embedding business logic in route functions. Register the router at prefix `/api/learning`; keep the existing learning and assessment routers registered.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_activity_sessions.py backend/tests/test_learning_insights_api.py backend/tests/test_regressions.py -v`

Expected: all selected tests pass.

- [ ] **Step 7: Commit the activity/session slice**

```powershell
git add backend/app/services/activity_service.py backend/app/services/study_session_service.py backend/app/api/routes/learning_insights.py backend/app/main.py backend/tests/test_activity_sessions.py backend/tests/test_learning_insights_api.py
git commit -m "feat: track active learning sessions"
```

### Task 3: Automatic Domain Activity Recording

**Files:**
- Modify: `backend/app/api/routes/chat_sessions.py`
- Modify: `backend/app/api/routes/learning.py`
- Modify: `backend/app/services/conversation_service.py`
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/services/assessment_service.py`
- Modify: `backend/app/services/assessment_workflows.py`
- Modify: `backend/app/services/weakness_service.py`
- Create: `backend/tests/test_activity_integrations.py`
- Modify: `backend/tests/test_conversation_service.py`
- Modify: `backend/tests/test_review_service.py`
- Modify: `backend/tests/test_assessment_service.py`

**Interfaces:**
- Consumes: `append_activity(db, *, event_key, activity_type, title, workspace_id=None, source_type, source_id, duration_seconds=0, payload=None, occurred_at=None) -> StudyActivity` from Task 2.
- Produces: stable automatic activity records at each successful business transaction boundary.
- Produces: `append_mastery_change(db, point, *, before_mastery, before_status, reason, source_type, source_id) -> list[StudyActivity]`.
- Produces: `append_weakness_change(db, state, *, before_score, before_category, reason) -> StudyActivity | None`.

- [ ] **Step 1: Write one failing integration test per required behavior**

```python
async def assert_one_event(db, activity_type, source_type, source_id):
    rows = (await db.execute(select(StudyActivity).where(
        StudyActivity.activity_type == activity_type,
        StudyActivity.source_type == source_type,
        StudyActivity.source_id == source_id,
    ))).scalars().all()
    assert len(rows) == 1

async def test_card_review_and_quiz_successes_create_typed_events(self):
    card_response = await self.request("POST", "/cards", json={
        "workspace_id": self.workspace.id, "front": "Q", "back": "A"
    })
    card = card_response.json()
    review_response = await self.request("POST", f"/cards/{card['id']}/review", json={
        "rating": 3, "duration_seconds": 20
    })
    paper, question = await self.paper()
    run = await self.started(paper)
    quiz_response = await self.request(
        "POST", f"/quiz-runs/{run['id']}/questions/{question.id}/submit",
        json={"answer": "Three", "duration_seconds": 15},
    )
    await assert_one_event(self.db, "card_created", "flashcard", card["id"])
    await assert_one_event(
        self.db, "review_completed", "review_log",
        review_response.json()["change"]["review_id"],
    )
    await assert_one_event(self.db, "quiz_completed", "quiz_run", quiz_response.json()["run"]["id"])
```

Add separate tests for question persistence, conversation settlement, message-derived card, manual card, knowledge threshold crossing, repeated mastery after regression, goal event deferred to Task 4, and weakness changes. For each endpoint replay an allowed idempotent request or re-run the service and assert the activity count stays one.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_activity_integrations.py -v`

Expected: missing typed activities or legacy activity types observed.

- [ ] **Step 3: Add typed events to card, review, and assessment transactions**

Create the card event after `flush()` supplies its ID. In `apply_card_review`, keep the new `ReviewLog` reference and use its ID as the event source. On quiz submission, emit exactly once when a `QuizRun` first transitions to `submitted`; retries create their own run events. Stop writing duplicate legacy `review`/`quiz` activities in the same flow.

- [ ] **Step 4: Add question and conversation events**

Emit `question_asked` only after the user message has a persistent message ID. Store question length, mode, workspace/document scope, and no question text. Let `StudySession` settlement own `conversation_completed`; do not add a second event when an assistant message finishes streaming.

- [ ] **Step 5: Add mastery and weakness evidence helpers**

Capture values before mutation. Always emit `mastery_changed` for a real mastery/status delta; additionally emit `knowledge_mastered` when status crosses into `mastered`. Emit `weakness_changed` only when weakness score changes beyond database precision or category changes. Store complete before/after values.

- [ ] **Step 6: Run domain and regression tests and verify GREEN**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_activity_integrations.py backend/tests/test_conversation_service.py backend/tests/test_review_service.py backend/tests/test_assessment_service.py backend/tests/test_weakness_service.py backend/tests/test_flashcard_api.py -v`

Expected: all selected tests pass and typed activity counts are exact.

- [ ] **Step 7: Commit automatic event integration**

```powershell
git add backend/app/api/routes/chat_sessions.py backend/app/api/routes/learning.py backend/app/services/conversation_service.py backend/app/services/review_service.py backend/app/services/assessment_service.py backend/app/services/assessment_workflows.py backend/app/services/weakness_service.py backend/tests/test_activity_integrations.py backend/tests/test_conversation_service.py backend/tests/test_review_service.py backend/tests/test_assessment_service.py
git commit -m "feat: record auditable learning activities"
```

### Task 4: Learning Goals and Progress

**Files:**
- Create: `backend/app/services/goal_service.py`
- Modify: `backend/app/api/routes/learning_insights.py`
- Modify: `backend/app/api/routes/learning.py`
- Create: `backend/tests/test_goal_service.py`
- Modify: `backend/tests/test_learning_insights_api.py`

**Interfaces:**
- Consumes: `LearningGoal`, `UserProfile`, `append_activity`, `PeriodBounds`.
- Produces: `get_goals(db, *, now) -> GoalCollection`.
- Produces: `update_global_goals(db, request, *, now) -> GoalCollection`.
- Produces: `update_workspace_goal(db, workspace_id, request, *, now) -> GoalProgress`.
- Produces: `calculate_goal_progress(db, goal, bounds, *, now) -> GoalProgress(actual, target, ratio, status)`.

- [ ] **Step 1: Write failing goal behavior and API tests**

```python
async def test_global_goal_update_syncs_profile_and_records_before_after(db):
    result = await update_global_goals(db, GlobalGoalsUpdate(
        daily_minutes=40, daily_reviews=12, weekly_days=6,
        target_completion_date=date(2026, 12, 31), timezone_name="Asia/Shanghai"), now=NOW)
    profile = await db.scalar(select(UserProfile))
    assert (profile.daily_goal_minutes, profile.daily_review_target, profile.weekly_goal_days) == (40, 12, 6)
    assert result.daily_minutes.target == 40
    events = await db.scalars(select(StudyActivity).where(StudyActivity.activity_type == "goal_changed"))
    assert len(events.all()) == 4

async def test_workspace_goal_progress_uses_average_point_mastery(db):
    # mastery .6 and .8 against target 80 -> actual 70, ratio .875
```

Also test unchanged updates produce no event, past dates return 422, invalid timezone preserves the previous value, empty workspace progress is zero, delete deactivates but preserves history, and overall mastery excludes archived workspaces.

- [ ] **Step 2: Run tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_goal_service.py backend/tests/test_learning_insights_api.py -v`

Expected: missing goal service/routes.

- [ ] **Step 3: Implement goal upsert, compatibility sync, and progress**

Use one transaction for all global fields. Compare normalized values before writing; increment an event version only for changed fields. Store total completion date on `overall_mastery` with target 100. Use natural-period activity evidence for daily minutes/reviews and weekly active days.

- [ ] **Step 4: Add goal routes and legacy profile compatibility**

Implement `GET /goals`, `PUT /goals/global`, `PUT/DELETE /goals/workspaces/{workspace_id}`. Extend legacy profile responses with timezone and weekly days. Route legacy profile changes to the goal service so the compatibility fields and canonical goals never diverge.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_goal_service.py backend/tests/test_learning_insights_api.py backend/tests/test_regressions.py -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit learning goals**

```powershell
git add backend/app/services/goal_service.py backend/app/api/routes/learning_insights.py backend/app/api/routes/learning.py backend/tests/test_goal_service.py backend/tests/test_learning_insights_api.py
git commit -m "feat: add measurable learning goals"
```

### Task 5: Real Today Dashboard Aggregation

**Files:**
- Create: `backend/app/services/dashboard_service.py`
- Modify: `backend/app/api/routes/learning_insights.py`
- Modify: `backend/app/api/routes/learning.py`
- Create: `backend/tests/test_dashboard_service.py`
- Modify: `backend/tests/test_learning_insights_api.py`

**Interfaces:**
- Consumes: period and goal services; `Flashcard`, `MistakeRecord`, `LearningTask`, `WeakKnowledgeState`, `Workspace`, and typed activities.
- Produces: `build_dashboard(db, *, now) -> DashboardView`.
- Produces: `rank_workspaces(db, *, now, limit=4) -> list[WorkspaceRecommendation]` with component scores and a human-readable primary reason.
- Produces: stable derived task IDs formatted `derived:<local-date>:<type>:<scope>`.

- [ ] **Step 1: Write failing task, streak, and ranking tests**

```python
async def test_dashboard_caps_and_orders_real_tasks(db):
    view = await build_dashboard(db, now=NOW)
    assert len(view.today_tasks) <= 5
    assert [task.type for task in view.today_tasks[:2]] == ["review", "mistake"]
    assert view.today_tasks[0].count == 7
    assert view.today_tasks[0].status == "pending"

async def test_derived_task_cannot_be_manually_completed(client):
    response = await client.post("/api/learning/tasks/derived:2026-09-15:review:global/complete")
    assert response.status_code in {400, 404}
```

Add tests for user-timezone midnight, today-vs-yesterday streak, completed derived tasks remaining visible, unresolved mistake source, due review target cap, median/fallback estimates, expiring workspace goals, archived workspace exclusion, stable score ties, and explainable recommendation components.

- [ ] **Step 2: Run tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_dashboard_service.py backend/tests/test_learning_insights_api.py -v`

Expected: current UTC dashboard and `QuizQuestion.last_correct` behavior fail the new assertions.

- [ ] **Step 3: Implement dashboard aggregation and recommendation scoring**

Use one captured `now`, one profile timezone, and shared period bounds for every query. Generate candidates in the specified order, calculate status only from real records, then cap at five. Rank unarchived workspaces with weights 35/30/20/10/5 and return every component plus the largest non-zero reason.

- [ ] **Step 4: Wire new and legacy dashboard endpoints**

Make `/api/learning/dashboard` use `build_dashboard`. Preserve existing keys (`profile`, `stats`, `today_tasks`, `weak_points`, `recent_activities`, `recent_workspaces`) and add `goal_progress`, `learning_queue`, `recommended_workspaces`, task descriptions/estimates/sources, and activity source metadata.

- [ ] **Step 5: Run focused and prior dashboard tests and verify GREEN**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_dashboard_service.py backend/tests/test_learning_insights_api.py backend/tests/test_final_assessment_fixes.py backend/tests/test_regressions.py -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit dashboard aggregation**

```powershell
git add backend/app/services/dashboard_service.py backend/app/api/routes/learning_insights.py backend/app/api/routes/learning.py backend/tests/test_dashboard_service.py backend/tests/test_learning_insights_api.py
git commit -m "feat: generate evidence-based daily learning plan"
```

### Task 6: Natural-Period Reports, Evidence, and AI Suggestions

**Files:**
- Create: `backend/app/services/report_service.py`
- Create: `backend/app/services/report_ai_service.py`
- Modify: `backend/app/api/routes/learning_insights.py`
- Modify: `backend/app/api/routes/learning.py`
- Create: `backend/tests/test_report_service.py`
- Create: `backend/tests/test_report_ai_service.py`
- Modify: `backend/tests/test_learning_insights_api.py`

**Interfaces:**
- Consumes: period, activity, and goal services plus domain tables.
- Produces: `build_report(db, period_type, anchor_date, *, now) -> LearningReportView`.
- Produces: `get_metric_evidence(db, period_type, anchor_date, metric, *, cursor=None, limit=30) -> EvidencePage`.
- Produces: `generate_suggestion(db, settings, period_type, anchor_date, *, completion=None) -> ReportSuggestionView`.
- Produces: SHA-256 hash of canonical JSON statistics with sorted keys and no suggestion fields.

- [ ] **Step 1: Write failing deterministic report tests**

```python
async def test_week_report_aggregates_only_current_natural_week(db):
    report = await build_report(db, "week", date(2026, 9, 16), now=NOW)
    assert report.period.local_start == "2026-09-14"
    assert report.total_active_seconds == 900
    assert report.review_count == 2
    assert report.quiz_accuracy == 75.0

async def test_report_accuracy_excludes_pending_ai_attempts(db):
    report = await build_report(db, "day", date(2026, 9, 15), now=NOW)
    assert report.quiz_accuracy == 50.0
    assert report.pending_grading_count == 1

async def test_metric_evidence_reconstructs_report_total(db):
    await append_activity(
        db, event_key="activity:study-session:s1", activity_type="document_read",
        title="阅读资料", workspace_id="ws-1", source_type="study_session",
        source_id="s1", duration_seconds=600,
        occurred_at=datetime(2026, 9, 15, 2, tzinfo=timezone.utc),
    )
    report = await build_report(db, "day", date(2026, 9, 15), now=NOW)
    evidence = await get_metric_evidence(
        db, "day", date(2026, 9, 15), metric="learning_time", limit=30,
    )
    assert sum(item.duration_seconds for item in evidence.items) == report.total_active_seconds
```

Add mastery delta, weakness groups, previous-period zero baseline, activity-count exclusion of internal evidence, new knowledge point records, daily buckets, cursor binding, and legacy-source labeling tests.

- [ ] **Step 2: Write failing AI cache/failure tests**

```python
async def test_same_snapshot_reuses_ready_suggestion(db):
    calls = 0
    async def completion(_prompt):
        nonlocal calls; calls += 1; return "先复习薄弱点。", "model-x"
    first = await generate_suggestion(db, settings, "week", ANCHOR, completion=completion)
    second = await generate_suggestion(db, settings, "week", ANCHOR, completion=completion)
    assert first.id == second.id
    assert calls == 1

async def test_failure_is_persisted_without_hiding_report(db):
    with pytest.raises(ReportAIError):
        await generate_suggestion(db, settings, "week", ANCHOR, completion=failing_completion)
    row = await db.scalar(select(ReportSuggestion))
    assert row.status == "failed"
    assert (await build_report(db, "week", ANCHOR, now=NOW)).metrics
```

- [ ] **Step 3: Run report tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_report_service.py backend/tests/test_report_ai_service.py -v`

Expected: missing report services.

- [ ] **Step 4: Implement report aggregation and evidence queries**

Aggregate active seconds from typed/compatible activities without source duplication. Calculate quiz accuracy as graded score sum divided by max-score sum. Calculate mastery and weakness changes only from internal evidence. Include `evidence_query` in every metric; for knowledge-point and quiz metrics resolve domain records in the evidence response.

- [ ] **Step 5: Implement cached AI suggestion generation**

Build a concise Chinese prompt from canonical statistics, current goal gaps, and at most five weak-point changes. Use the configured LLM pattern already exercised by `assessment_ai.py`. Persist `pending` before the provider call, then `ready` or `failed`; validate non-empty plain text and cap stored output at 1,200 characters.

- [ ] **Step 6: Add report/evidence/suggestion routes and legacy adapter**

Expose the three natural-period endpoints. Return deterministic stats even when suggestion status is `failed`. Adapt old `days` report response from the new aggregation primitives while preserving its exact keys.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_report_service.py backend/tests/test_report_ai_service.py backend/tests/test_learning_insights_api.py backend/tests/test_final_assessment_fixes.py -v`

Expected: all selected tests pass.

- [ ] **Step 8: Commit reports and suggestions**

```powershell
git add backend/app/services/report_service.py backend/app/services/report_ai_service.py backend/app/api/routes/learning_insights.py backend/app/api/routes/learning.py backend/tests/test_report_service.py backend/tests/test_report_ai_service.py backend/tests/test_learning_insights_api.py
git commit -m "feat: add traceable learning reports"
```

### Task 7: Frontend Active-Time Tracking and Quick-Question Handoff

**Files:**
- Create: `frontend/src/features/activity/activeStudySession.ts`
- Create: `frontend/src/hooks/useActiveStudySession.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/pages/DocumentDetail.tsx`
- Modify: `frontend/src/pages/LearningChat.tsx`
- Create: `frontend/tests/activeStudySession.test.ts`
- Create: `frontend/tests/quickQuestion.test.tsx`

**Interfaces:**
- Consumes endpoints from Task 2.
- Produces: `createActiveStudyController(deps) -> { userActivity(), visibilityChanged(visible), contextChanged(context), dispose() }`.
- Produces: `useActiveStudySession({ contextType, contextId, workspaceId, enabled })`.
- Produces: quick-question navigation state `{ quickQuestion: string, workspaceId?: string, nonce: string }` consumed once by `LearningChat`.

- [ ] **Step 1: Write failing state-machine and navigation tests**

```typescript
test('heartbeats only while visible and recently active', async () => {
  const clock = fakeClock();
  const calls: string[] = [];
  const controller = createActiveStudyController({ clock, start, heartbeat: async () => calls.push('beat'), finish });
  controller.contextChanged({ contextType: 'document', contextId: 'doc', workspaceId: 'ws' });
  controller.userActivity();
  await clock.advance(30_000);
  assert.deepEqual(calls, ['beat']);
  await clock.advance(61_000);
  assert.deepEqual(calls, ['beat']);
});

test('quick question uses navigation state and never URL query text', () => {
  const result = quickQuestionDestination('如何理解梯度下降？', 'ws-1', 'nonce-1');
  assert.equal(result.pathname, '/learn');
  assert.equal(result.search, undefined);
  assert.equal(result.state.quickQuestion, '如何理解梯度下降？');
});
```

Also test hidden pause, visible resume after interaction, ordered sequences, context switch finishing the old session, unload keepalive, network retry with the same sequence, and consume-once navigation nonce.

- [ ] **Step 2: Run frontend tests and verify RED**

Run from `frontend`: `node --import tsx --test tests/activeStudySession.test.ts tests/quickQuestion.test.tsx`

Expected: missing controller and quick-question helpers.

- [ ] **Step 3: Implement API types and browser-agnostic controller**

Inject clock/timer/API dependencies so tests use no browser globals. Coalesce pointer, keyboard, touch, and scroll into one `userActivity()` call; do not send raw event data. Reuse a client UUID per mounted context and sequence heartbeats monotonically.

- [ ] **Step 4: Implement React hook and attach it to learning pages**

Attach document context only after a real document loads. Attach conversation context only when an active chat session exists. Disable conversation active timing while a quiz/review route owns time. On cleanup, finish with fetch keepalive and retain the same idempotent session ID.

- [ ] **Step 5: Consume quick-question state safely**

Initialize workspace and composer from navigation state, then replace the current history entry with cleared state after the nonce is consumed. Do not auto-send; let the user review and press send.

- [ ] **Step 6: Run tests and build and verify GREEN**

Run from `frontend`: `node --import tsx --test tests/activeStudySession.test.ts tests/quickQuestion.test.tsx tests/learningChatPresets.test.ts`

Run from `frontend`: `npm run build`

Expected: tests pass and production build exits 0.

- [ ] **Step 7: Commit active tracking and handoff**

```powershell
git add frontend/src/features/activity/activeStudySession.ts frontend/src/hooks/useActiveStudySession.ts frontend/src/services/api.ts frontend/src/pages/DocumentDetail.tsx frontend/src/pages/LearningChat.tsx frontend/tests/activeStudySession.test.ts frontend/tests/quickQuestion.test.tsx
git commit -m "feat: track active study time in learning views"
```

### Task 8: Learning Homepage UI

**Files:**
- Create: `frontend/src/features/dashboard/dashboardViewModel.ts`
- Create: `frontend/src/components/dashboard/QuickQuestion.tsx`
- Create: `frontend/src/components/dashboard/TodayPlan.tsx`
- Create: `frontend/src/components/dashboard/LearningQueue.tsx`
- Create: `frontend/src/components/dashboard/ActivityTimeline.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/styles/app.css`
- Create: `frontend/tests/dashboardViewModel.test.ts`
- Create: `frontend/tests/learningInsightsComponents.test.tsx`

**Interfaces:**
- Consumes: extended `LearningDashboard` API type from Task 7.
- Produces: `dashboardTaskAction(task) -> { kind: 'navigate' | 'complete' | 'none'; path?: string }`.
- Produces: dashboard components with typed props and no direct API calls except the page-level coordinator.

- [ ] **Step 1: Write failing view-model and static component tests**

```typescript
test('derived tasks navigate but cannot be manually completed', () => {
  assert.deepEqual(dashboardTaskAction({ id: 'derived:2026-09-15:review:global', status: 'pending', path: '/review', source: 'derived' }),
    { kind: 'navigate', path: '/review' });
});

test('persistent pending task exposes complete action', () => {
  assert.equal(dashboardTaskAction({ id: 'task-1', status: 'pending', path: '/practice', source: 'learning_task' }).kind, 'complete');
});
```

Render components to static markup and assert quick-question label, review/mistake counts, recommendation reason, legacy activity badge, empty-state action, and completed-task copy.

- [ ] **Step 2: Run component tests and verify RED**

Run from `frontend`: `node --import tsx --test tests/dashboardViewModel.test.ts tests/learningInsightsComponents.test.tsx`

Expected: missing dashboard modules/components.

- [ ] **Step 3: Implement focused dashboard components**

Keep API fetching, reload versioning, and durable task completion in `Dashboard.tsx`. Components receive plain data and callbacks. The quick-question form validates non-empty text, passes navigation state, and offers an optional workspace selector populated from dashboard recommendations/recent workspaces.

- [ ] **Step 4: Recompose the dashboard and responsive styles**

Render, in order: greeting/goal strip, quick question, today plan, due review/mistake/recommended workspace queue, recent activity, weak points. Preserve existing error toast behavior but give each empty section a concrete action. At widths below 768px use a single column and full-width primary actions.

- [ ] **Step 5: Run dashboard tests, all existing frontend tests, and build**

Run from `frontend`: `$testFiles = Get-ChildItem tests -File | Where-Object { $_.Name -match '\.test\.tsx?$' } | ForEach-Object { $_.FullName }; node --import tsx --test $testFiles`

Run from `frontend`: `npm run build`

Expected: all frontend tests pass and build exits 0.

- [ ] **Step 6: Commit the homepage**

```powershell
git add frontend/src/features/dashboard/dashboardViewModel.ts frontend/src/components/dashboard frontend/src/pages/Dashboard.tsx frontend/src/styles/app.css frontend/tests/dashboardViewModel.test.ts frontend/tests/learningInsightsComponents.test.tsx
git commit -m "feat: rebuild the daily learning homepage"
```

### Task 9: Day/Week/Month Report, Evidence Drawer, and Goal UI

**Files:**
- Create: `frontend/src/features/report/reportViewModel.ts`
- Create: `frontend/src/components/report/GoalEditor.tsx`
- Create: `frontend/src/components/report/EvidenceDrawer.tsx`
- Create: `frontend/src/components/report/ReportTrend.tsx`
- Create: `frontend/src/components/report/WeaknessChanges.tsx`
- Modify: `frontend/src/pages/LearningReport.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/styles/app.css`
- Create: `frontend/tests/reportViewModel.test.ts`
- Create: `frontend/tests/goalEditor.test.tsx`
- Modify: `frontend/tests/learningInsightsComponents.test.tsx`

**Interfaces:**
- Consumes: report, evidence, suggestion, and goal endpoints from Tasks 4 and 6.
- Produces: `reportMetricCards(report) -> ReportMetricCard[]` with evidence metric identifiers.
- Produces: `formatComparison(value: number | null) -> { text: string; tone: 'positive' | 'negative' | 'neutral' }` where `null` means no baseline.
- Produces controlled `GoalEditor`, paginated `EvidenceDrawer`, SVG/CSS `ReportTrend`, and grouped `WeaknessChanges`.

- [ ] **Step 1: Write failing report view-model and goal validation tests**

```typescript
test('zero previous period is shown as no comparable baseline', () => {
  assert.deepEqual(formatComparison(null), { text: '暂无可比基线', tone: 'neutral' });
});

test('goal payload keeps calendar dates and validates limits', () => {
  assert.deepEqual(toGlobalGoalPayload({ minutes: 30, reviews: 10, weeklyDays: 5,
    targetDate: '2026-12-31', timezoneName: 'Asia/Shanghai' }).target_completion_date, '2026-12-31');
  assert.throws(() => toGlobalGoalPayload({ minutes: 0, reviews: 10, weeklyDays: 5,
    targetDate: '2026-12-31', timezoneName: 'Asia/Shanghai' }));
});
```

Add metric ordering, duration formatting, negative mastery change, weakness grouping, period navigation, evidence query forwarding, AI pending/ready/failed copy, and load-more cursor tests.

- [ ] **Step 2: Run focused frontend tests and verify RED**

Run from `frontend`: `node --import tsx --test tests/reportViewModel.test.ts tests/goalEditor.test.tsx tests/learningInsightsComponents.test.tsx`

Expected: missing report modules/components.

- [ ] **Step 3: Implement report and goal API contracts**

Add discriminated types for `day | week | month`, suggestion status, metric evidence, goal scope/metric, progress, and weakness changes. Encode `anchor_date` only as a calendar date. Abort or version stale report/evidence requests when the user changes periods.

- [ ] **Step 4: Implement report components**

Use accessible buttons for metric drilldown. `ReportTrend` exposes exact values through labels/tooltips and does not rely on color alone. `EvidenceDrawer` resets items/cursor whenever its metric or period changes. `GoalEditor` submits one global transaction followed by only changed workspace goals and keeps the modal open with an error message if any save fails.

- [ ] **Step 5: Rebuild the report page and connect Settings**

Replace rolling 7/30/90 controls with natural day/week/month controls and period navigation. Show metrics, trend, comparisons, weakness groups, goal progress, and suggestion metadata. Do not auto-call AI on page load when no cached suggestion exists; show “生成学习建议”. Add timezone and weekly-day compatibility controls in Settings plus a link to the full goal editor.

- [ ] **Step 6: Run focused tests, all frontend tests, and build**

Run from `frontend`: `node --import tsx --test tests/reportViewModel.test.ts tests/goalEditor.test.tsx tests/learningInsightsComponents.test.tsx`

Run from `frontend`: `$testFiles = Get-ChildItem tests -File | Where-Object { $_.Name -match '\.test\.tsx?$' } | ForEach-Object { $_.FullName }; node --import tsx --test $testFiles`

Run from `frontend`: `npm run build`

Expected: all tests pass and production build exits 0.

- [ ] **Step 7: Commit reports and goals UI**

```powershell
git add frontend/src/features/report frontend/src/components/report frontend/src/pages/LearningReport.tsx frontend/src/pages/Settings.tsx frontend/src/services/api.ts frontend/src/styles/app.css frontend/tests/reportViewModel.test.ts frontend/tests/goalEditor.test.tsx frontend/tests/learningInsightsComponents.test.tsx
git commit -m "feat: add learning trends goals and evidence"
```

### Task 10: Export, Documentation, Migration Regression, and Final Verification

**Files:**
- Modify: `backend/app/api/routes/learning.py`
- Modify: `backend/tests/test_learning_insights_api.py`
- Modify: `backend/tests/test_docker_architecture.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: all prior phase-six models and services.
- Produces: export format version `2` including goals, sessions, suggestions, and expanded activity evidence.
- Produces: final evidence that all acceptance criteria and compatibility constraints pass.

- [ ] **Step 1: Write failing export and upgraded-database regression tests**

```python
async def test_export_v2_contains_traceable_phase_six_data(client):
    data = (await client.get("/api/learning/export")).json()
    assert data["format_version"] == 2
    assert {"learning_goals", "study_sessions", "report_suggestions"} <= data.keys()
    assert {"event_key", "source_type", "source_id", "occurred_at"} <= data["activities"][0].keys()
```

Create an in-memory legacy schema matching the pre-phase-six columns, run `run_compat_migrations()` twice, insert/read an old activity, and assert old dashboard/report routes still return 200.

- [ ] **Step 2: Run export/migration tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_learning_insights_api.py backend/tests/test_phase_six_models.py backend/tests/test_docker_architecture.py -v`

Expected: export lacks phase-six entities or still reports format version 1.

- [ ] **Step 3: Extend export and README**

Export raw phase-six records without secrets or question text duplicated in activity payloads. Document active-time semantics, timezone periods, AI suggestion failure behavior, goal definitions, API entry points, and the exact verification commands below.

- [ ] **Step 4: Run the complete backend suite**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests -q`

Expected: exit 0, zero failed tests.

- [ ] **Step 5: Run the complete frontend suite**

Run from `frontend`: `$testFiles = Get-ChildItem tests -File | Where-Object { $_.Name -match '\.test\.tsx?$' } | ForEach-Object { $_.FullName }; node --import tsx --test $testFiles`

Expected: exit 0, zero failed tests.

- [ ] **Step 6: Run the production build**

Run from `frontend`: `npm run build`

Expected: TypeScript and Vite exit 0 without build errors.

- [ ] **Step 7: Perform manual acceptance checks**

Start the existing development stack and verify:

1. An active document session increases today minutes; hiding the tab for over 60 seconds does not.
2. One question, completed conversation, created card, review, submitted quiz, mastered point, and changed goal each appear exactly once.
3. Dashboard review and mistake counts match their source pages; derived tasks have no manual-complete action.
4. Day/week/month navigation uses the configured timezone and every metric opens matching evidence.
5. AI failure leaves report statistics visible and retry succeeds when the model becomes available.
6. Global and workspace goal edits immediately update progress on the report and dashboard.
7. Desktop and mobile layouts keep all primary actions visible and keyboard reachable.

- [ ] **Step 8: Review the acceptance matrix against fresh evidence**

Record the final commands and outcomes in the commit message notes or handoff response. Do not mark the phase complete if any of the five acceptance rows in the spec lacks a passing automated test plus its applicable manual check.

- [ ] **Step 9: Commit documentation and final integration**

```powershell
git add backend/app/api/routes/learning.py backend/tests/test_learning_insights_api.py backend/tests/test_docker_architecture.py README.md
git commit -m "docs: document phase six learning insights"
```

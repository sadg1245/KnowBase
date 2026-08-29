# Phase Four Knowledge Cards and Review Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the knowledge-card lifecycle, review dashboard, spaced-review state synchronization, real timing, keyboard/touch review controls, and phase-four regression coverage.

**Architecture:** Extend the existing `Flashcard` and `ReviewLog` tables in place, move review business rules into a focused backend service, and keep FastAPI routes as validation/serialization boundaries. Split the React review page into overview, library, session, and result components backed by pure session/gesture helpers so behavior is testable without a browser.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, SQLite compatibility migrations, Pydantic 2, React 18, TypeScript, Ant Design 5, Vite, Node test runner, Playwright CLI.

**Spec:** `docs/superpowers/specs/2026-08-29-phase-four-knowledge-cards-review-center-design.md`

## Global Constraints

- Preserve all existing flashcards, review logs, knowledge points, and chat-generated card links.
- Do not add a second flashcard or review-session persistence system.
- Keep the first scheduler version named exactly `simple_v1`.
- Accepted card source types are exactly `manual`, `knowledge_point`, `answer`, and `selection`.
- Accepted mastery statuses remain exactly `not_started`, `learning`, and `mastered`.
- Review duration is an integer from 0 through 3600 seconds; omitted duration remains backward compatible as 0.
- The mobile layout must work at 320px without horizontal scrolling.
- Do not add a new runtime dependency.

---

## File Map

### Backend

- Modify `backend/app/models/learning.py`: persistent card and review-log fields.
- Modify `backend/app/core/migrations.py`: idempotent SQLite column additions.
- Modify `backend/app/schemas/learning.py`: CRUD, generation, summary, and review payloads.
- Create `backend/app/services/review_service.py`: mastery, scheduling application, timing, and summary logic.
- Modify `backend/app/api/routes/learning.py`: card CRUD/generation/summary route contracts.
- Modify `backend/app/api/routes/chat_sessions.py`: answer-card source metadata.
- Create `backend/tests/test_phase_four_models.py`: model, schema, and migration contracts.
- Create `backend/tests/test_review_service.py`: pure mastery and transactional review behavior.
- Create `backend/tests/test_flashcard_api.py`: CRUD and all card-source contracts.
- Create `backend/tests/test_review_summary.py`: local-day statistics and streak behavior.

### Frontend

- Modify `frontend/src/services/api.ts`: expanded types and endpoints.
- Create `frontend/src/features/review/types.ts`: page/session state contracts.
- Create `frontend/src/features/review/reviewSession.ts`: pure session reducer and result aggregation.
- Create `frontend/src/features/review/gestures.ts`: pure touch gesture classification.
- Create `frontend/src/components/review/ReviewOverview.tsx`: daily summary and weak points.
- Create `frontend/src/components/review/CardEditorModal.tsx`: create/edit/selection form.
- Create `frontend/src/components/review/CardLibrary.tsx`: filtering, editing, and deletion.
- Create `frontend/src/components/review/ReviewSessionPanel.tsx`: flip, keyboard, touch, and rating UI.
- Create `frontend/src/components/review/ReviewResults.tsx`: session outcome.
- Replace `frontend/src/pages/ReviewCenter.tsx`: page orchestration and parallel loading.
- Create `frontend/src/pages/documentCardSelection.ts`: selection normalization.
- Modify `frontend/src/pages/DocumentDetail.tsx`: parsed-source selection flow.
- Modify `frontend/src/pages/KnowledgeBase.tsx`: workspace card generation action.
- Modify `frontend/src/styles/app.css`: responsive review-center styling.
- Create `frontend/tests/reviewSession.test.ts`: reducer/timing/result tests.
- Create `frontend/tests/reviewGestures.test.ts`: gesture threshold/direction tests.
- Create `frontend/tests/reviewComponents.test.tsx`: real component rendering contracts.
- Create `frontend/tests/documentCardSelection.test.ts`: selection normalization.

---

### Task 1: Persist Complete Card and Review State

**Files:**
- Modify: `backend/app/models/learning.py:58-88`
- Modify: `backend/app/core/migrations.py:16-64`
- Modify: `backend/app/schemas/learning.py:47-56`
- Create: `backend/tests/test_phase_four_models.py`

**Interfaces:**
- Produces: expanded `Flashcard`, expanded `ReviewLog`, `FlashcardCreate`, `FlashcardUpdate`, `FlashcardSelectionCreate`, `FlashcardGenerateRequest`, and `ReviewRequest`.
- Consumed by: Tasks 2–7.

- [ ] **Step 1: Write failing model and schema tests**

```python
class PhaseFourModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_flashcard_defaults_preserve_scheduler_state(self):
        async with self.sessions() as db:
            workspace = Workspace(name="Cards", slug="cards")
            db.add(workspace)
            await db.flush()
            card = Flashcard(workspace_id=workspace.id, front="Q", back="A")
            db.add(card)
            await db.flush()
            self.assertEqual(card.tags, [])
            self.assertEqual(card.difficulty, 2)
            self.assertEqual(card.mastery, 0.0)
            self.assertEqual(card.mastery_status, "not_started")
            self.assertEqual(card.source_type, "manual")
            self.assertEqual(card.algorithm_version, "simple_v1")
            self.assertEqual(card.scheduler_data, {})
            self.assertEqual(card.total_review_seconds, 0)

    def test_review_request_accepts_duration_and_rejects_out_of_range(self):
        self.assertEqual(ReviewRequest(rating=3, duration_seconds=18).duration_seconds, 18)
        with self.assertRaises(ValidationError):
            ReviewRequest(rating=3, duration_seconds=3601)

    def test_card_update_does_not_expose_scheduler_counters(self):
        fields = set(FlashcardUpdate.model_fields)
        self.assertTrue({"front", "back", "workspace_id", "tags", "difficulty", "source_label", "due_at"} <= fields)
        self.assertFalse({"review_count", "ease", "interval_days"} & fields)
```

- [ ] **Step 2: Run the model tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_phase_four_models.py -v`

Expected: FAIL because the new columns and schemas do not exist.

- [ ] **Step 3: Add model columns and validated schemas**

```python
class Flashcard(Base):
    tags = Column(JSON, nullable=False, default=list)
    difficulty = Column(Integer, nullable=False, default=2)
    mastery = Column(Float, nullable=False, default=0.0)
    mastery_status = Column(String(20), nullable=False, default="not_started", index=True)
    source_type = Column(String(30), nullable=False, default="manual", index=True)
    source_snapshot = Column(JSON, nullable=True)
    algorithm_version = Column(String(20), nullable=False, default="simple_v1")
    scheduler_data = Column(JSON, nullable=False, default=dict)
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    total_review_seconds = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)

class ReviewLog(Base):
    duration_seconds = Column(Integer, nullable=False, default=0)
    previous_mastery = Column(Float, nullable=False, default=0.0)
    next_mastery = Column(Float, nullable=False, default=0.0)
    previous_status = Column(String(20), nullable=False, default="not_started")
    next_status = Column(String(20), nullable=False, default="learning")
    algorithm_version = Column(String(20), nullable=False, default="simple_v1")
```

Add Pydantic literals for source and mastery states. Normalize tags by trimming, removing blanks, and preserving first occurrence order. Add all new columns to `run_compat_migrations` with SQLite-safe defaults (`'[]'`, `'{}'`, numeric defaults, and nullable timestamps).

- [ ] **Step 4: Run model tests and existing model regression tests**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_phase_four_models.py backend/tests/test_phase_two_models.py backend/tests/test_chat_architecture.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the persistence slice**

```powershell
git add backend/app/models/learning.py backend/app/core/migrations.py backend/app/schemas/learning.py backend/tests/test_phase_four_models.py
git commit -m "feat: persist complete flashcard review state"
```

---

### Task 2: Centralize Review Scheduling, Mastery, and Timing

**Files:**
- Create: `backend/app/services/review_service.py`
- Modify: `backend/app/api/routes/learning.py:68-78,409-422`
- Create: `backend/tests/test_review_service.py`
- Modify: `backend/tests/test_regressions.py:114-119`

**Interfaces:**
- Consumes: Task 1 model fields and `ReviewRequest.duration_seconds`.
- Produces:
  - `mastery_after_review(current: float, rating: int) -> float`
  - `mastery_status_for(mastery: float, review_count: int) -> str`
  - `apply_card_review(db: AsyncSession, card: Flashcard, rating: int, duration_seconds: int, now: datetime | None = None) -> dict`

- [ ] **Step 1: Write failing pure-rule and transaction tests**

```python
def test_mastery_rules_use_literal_deltas_and_thresholds():
    self.assertEqual(mastery_after_review(0.50, 1), 0.38)
    self.assertEqual(mastery_after_review(0.50, 2), 0.52)
    self.assertEqual(mastery_after_review(0.70, 3), 0.82)
    self.assertEqual(mastery_after_review(0.90, 4), 1.0)
    self.assertEqual(mastery_status_for(0.0, 0), "not_started")
    self.assertEqual(mastery_status_for(0.0, 1), "learning")
    self.assertEqual(mastery_status_for(0.8, 1), "mastered")

async def test_review_updates_card_point_log_and_real_activity_duration(self):
    change = await apply_card_review(db, card, rating=4, duration_seconds=17, now=fixed_now)
    self.assertEqual(card.interval_days, 3)
    self.assertEqual(card.mastery, 0.2)
    self.assertEqual(card.mastery_status, "learning")
    self.assertEqual(point.mastery, 0.2)
    self.assertEqual(point.mastery_status, "learning")
    self.assertEqual(change["duration_seconds"], 17)
    self.assertEqual((await db.execute(select(ReviewLog))).scalar_one().duration_seconds, 17)
    self.assertEqual((await db.execute(select(StudyActivity))).scalar_one().duration_seconds, 17)
```

Also test clamping at 0 and 1, rating 1 after mastery, and `mastered` crossing in both card and knowledge point.

- [ ] **Step 2: Run service tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_review_service.py -v`

Expected: FAIL because `review_service` does not exist.

- [ ] **Step 3: Implement the minimal review service and route delegation**

```python
MASTERY_DELTAS = {1: -0.12, 2: 0.02, 3: 0.12, 4: 0.20}

def mastery_after_review(current: float, rating: int) -> float:
    return round(max(0.0, min(1.0, current + MASTERY_DELTAS[rating])), 6)

def mastery_status_for(mastery: float, review_count: int) -> str:
    if review_count == 0 and mastery == 0:
        return "not_started"
    return "mastered" if mastery >= 0.8 else "learning"
```

Move `schedule_review` into the service and re-export/import it from the route so existing tests and consumers remain compatible. In `apply_card_review`, snapshot previous values, update the card, optionally update the knowledge point, append `ReviewLog` and `StudyActivity`, flush once, and return a literal change dictionary.

- [ ] **Step 4: Run service and scheduler regression tests**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_review_service.py backend/tests/test_regressions.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the review service slice**

```powershell
git add backend/app/services/review_service.py backend/app/api/routes/learning.py backend/tests/test_review_service.py backend/tests/test_regressions.py
git commit -m "feat: synchronize review mastery and timing"
```

---

### Task 3: Complete Card CRUD and Four Creation Sources

**Files:**
- Modify: `backend/app/api/routes/learning.py:44-51,378-422`
- Modify: `backend/app/api/routes/chat_sessions.py:155-171`
- Create: `backend/tests/test_flashcard_api.py`

**Interfaces:**
- Consumes: Task 1 schemas and Task 2 `apply_card_review`.
- Produces: full `_card` response, `PUT /learning/cards/{id}`, selection creation, workspace generation, idempotent point generation, and enriched review response.

- [ ] **Step 1: Write failing CRUD and source tests**

```python
async def test_manual_card_can_be_created_updated_listed_and_deleted(self):
    created = await create_card(FlashcardCreate(
        workspace_id=workspace.id, front="Q", back="A", tags=["memory"], difficulty=3,
    ), db)
    updated = await update_card(created["id"], FlashcardUpdate(
        front="Q2", tags=["memory", "core"], due_at=fixed_due,
    ), db)
    self.assertEqual(updated["front"], "Q2")
    self.assertEqual(updated["tags"], ["memory", "core"])
    self.assertEqual(updated["source_type"], "manual")
    await delete_card(created["id"], db)
    self.assertEqual(await list_cards(db=db), [])

async def test_selection_card_validates_document_workspace_and_saves_snapshot(self):
    card = await selection_to_card(FlashcardSelectionCreate(
        workspace_id=workspace.id,
        document_id=document.id,
        front="为什么要间隔复习？",
        back="因为遗忘曲线会随时间下降。",
        source_excerpt="遗忘曲线会随时间下降",
        source_page=3,
        source_heading="长期记忆",
    ), db)
    self.assertEqual(card["source_type"], "selection")
    self.assertEqual(card["source_snapshot"]["page"], 3)
```

Add independent tests for point-card idempotency, workspace batch generation excluding already-covered points, answer-card source metadata, missing resources, and cross-workspace document/knowledge-point rejection.

- [ ] **Step 2: Run API tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_flashcard_api.py -v`

Expected: FAIL on missing update, selection, generation, and expanded serialization behavior.

- [ ] **Step 3: Implement complete card serialization and route behavior**

```python
def _card(row: Flashcard) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "knowledge_point_id": row.knowledge_point_id,
        "front": row.front,
        "back": row.back,
        "source_label": row.source_label,
        "source_type": row.source_type,
        "source_snapshot": row.source_snapshot,
        "tags": row.tags or [],
        "difficulty": row.difficulty,
        "mastery": row.mastery,
        "mastery_status": row.mastery_status,
        "due_at": _iso(row.due_at),
        "interval_days": row.interval_days,
        "ease": row.ease,
        "review_count": row.review_count,
        "algorithm_version": row.algorithm_version,
        "scheduler_data": row.scheduler_data or {},
        "last_reviewed_at": _iso(row.last_reviewed_at),
        "total_review_seconds": row.total_review_seconds,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
```

Use a shared `_ensure_workspace`, `_ensure_point_in_workspace`, and `_ensure_document_in_workspace` validation path. For point generation, query by `knowledge_point_id` before creating. For chat cards, set `source_type="answer"` and save the message source list as `source_snapshot`.

- [ ] **Step 4: Run API, chat, and document-management tests**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_flashcard_api.py backend/tests/test_document_management.py backend/tests/test_conversation_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the card API slice**

```powershell
git add backend/app/api/routes/learning.py backend/app/api/routes/chat_sessions.py backend/tests/test_flashcard_api.py
git commit -m "feat: complete flashcard CRUD and sources"
```

---

### Task 4: Build the Local-Day Review Summary

**Files:**
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/api/routes/learning.py`
- Create: `backend/tests/test_review_summary.py`

**Interfaces:**
- Consumes: Task 1 fields and profile settings.
- Produces: `build_review_summary(db, timezone_offset_minutes: int, now: datetime | None = None) -> dict` and `GET /learning/review/summary`.

- [ ] **Step 1: Write failing summary tests with literal timestamps**

```python
async def test_summary_uses_local_day_for_due_completed_overdue_and_streak(self):
    summary = await build_review_summary(db, timezone_offset_minutes=480, now=datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc))
    self.assertEqual(summary["due_count"], 3)
    self.assertEqual(summary["new_count"], 1)
    self.assertEqual(summary["completed_today"], 2)
    self.assertEqual(summary["overdue_count"], 1)
    self.assertEqual(summary["streak_days"], 3)
    self.assertEqual(summary["estimated_minutes"], 2)
    self.assertEqual(summary["daily_target"], 10)
```

Create fixed fixtures on UTC timestamps that cross the `+480` midnight boundary. Add a no-history test that estimates 30 seconds per due card and a weak-point ordering test that prioritizes `is_key` then low mastery.

- [ ] **Step 2: Run summary tests and verify RED**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_review_summary.py -v`

Expected: FAIL because summary logic and route do not exist.

- [ ] **Step 3: Implement local-day boundaries and aggregate summary**

```python
def local_day_bounds(now: datetime, offset_minutes: int) -> tuple[datetime, datetime]:
    offset = timedelta(minutes=offset_minutes)
    local_now = now + offset
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start - offset, local_start + timedelta(days=1) - offset
```

Fetch only the timestamps and durations needed for streak/average calculations. Estimate from the latest 30 positive review durations; otherwise use 30 seconds. Return weak points as existing `_point`-compatible dictionaries or a small explicit subset containing ID, workspace, title, mastery, mastery status, importance, and key flag.

- [ ] **Step 4: Run summary and dashboard regression tests**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests/test_review_summary.py backend/tests/test_document_management.py backend/tests/test_regressions.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the summary slice**

```powershell
git add backend/app/services/review_service.py backend/app/api/routes/learning.py backend/tests/test_review_summary.py
git commit -m "feat: add daily review summary"
```

---

### Task 5: Add Frontend Review State, API Contracts, and Gestures

**Files:**
- Modify: `frontend/src/services/api.ts:337-399`
- Create: `frontend/src/features/review/types.ts`
- Create: `frontend/src/features/review/reviewSession.ts`
- Create: `frontend/src/features/review/gestures.ts`
- Create: `frontend/tests/reviewSession.test.ts`
- Create: `frontend/tests/reviewGestures.test.ts`

**Interfaces:**
- Consumes: Task 3 and Task 4 JSON contracts.
- Produces:
  - `ReviewSummary`, expanded `Flashcard`, `CardDraft`, `ReviewResponse`.
  - `createReviewSession(cards, startedAt)`, `flipCard`, `recordReview`, and `reviewResults`.
  - `classifyReviewGesture(start, end, flipped) -> 'flip' | 'forgot' | 'remembered' | null`.

- [ ] **Step 1: Write failing pure frontend tests**

```typescript
test('records rating duration and mastery delta before advancing', () => {
  const state = createReviewSession([card], 1_000);
  const next = recordReview({ ...state, flipped: true }, {
    rating: 3,
    finishedAt: 19_400,
    response: { card: { ...card, mastery: 0.52 }, change: { previous_mastery: 0.4, next_mastery: 0.52 } },
  });
  assert.equal(next.index, 1);
  assert.equal(next.results[0].durationSeconds, 18);
  assert.equal(reviewResults(next).masteryDelta, 0.12);
});

test('gesture threshold protects scroll and maps horizontal ratings', () => {
  assert.equal(classifyReviewGesture({ x: 10, y: 100 }, { x: 20, y: 35 }, false), 'flip');
  assert.equal(classifyReviewGesture({ x: 100, y: 20 }, { x: 30, y: 24 }, true), 'forgot');
  assert.equal(classifyReviewGesture({ x: 20, y: 20 }, { x: 90, y: 25 }, true), 'remembered');
  assert.equal(classifyReviewGesture({ x: 20, y: 20 }, { x: 45, y: 70 }, true), null);
});
```

- [ ] **Step 2: Run pure tests and verify RED**

Run: `npx tsx --test tests/reviewSession.test.ts tests/reviewGestures.test.ts`

Expected: FAIL because the review feature modules do not exist.

- [ ] **Step 3: Implement immutable session helpers, gesture classifier, and API calls**

```typescript
export const classifyReviewGesture = (start: Point, end: Point, flipped: boolean): ReviewGesture => {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (!flipped && dy <= -56 && Math.abs(dy) > Math.abs(dx)) return 'flip';
  if (flipped && Math.abs(dx) >= 56 && Math.abs(dx) > Math.abs(dy)) return dx < 0 ? 'forgot' : 'remembered';
  return null;
};
```

Keep timestamps as numbers and derive duration with `Math.max(0, Math.min(3600, Math.round((finishedAt - cardStartedAt) / 1000)))`. Add API functions `getReviewSummary`, `updateCard`, `createSelectionCard`, `generateWorkspaceCards`, and expanded `reviewCard(id, rating, durationSeconds)`.

- [ ] **Step 4: Run pure tests and TypeScript compilation**

Run: `npx tsx --test tests/reviewSession.test.ts tests/reviewGestures.test.ts; npx tsc --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit the frontend foundation**

```powershell
git add frontend/src/services/api.ts frontend/src/features/review frontend/tests/reviewSession.test.ts frontend/tests/reviewGestures.test.ts
git commit -m "feat: add review session state and gestures"
```

---

### Task 6: Build Review Overview, Card Library, Session, and Results UI

**Files:**
- Create: `frontend/src/components/review/ReviewOverview.tsx`
- Create: `frontend/src/components/review/CardEditorModal.tsx`
- Create: `frontend/src/components/review/CardLibrary.tsx`
- Create: `frontend/src/components/review/ReviewSessionPanel.tsx`
- Create: `frontend/src/components/review/ReviewResults.tsx`
- Replace: `frontend/src/pages/ReviewCenter.tsx`
- Modify: `frontend/src/styles/app.css`
- Create: `frontend/tests/reviewComponents.test.tsx`

**Interfaces:**
- Consumes: Task 5 API and pure state interfaces.
- Produces: complete `/review` overview, CRUD library, quick review, and result flow.

- [ ] **Step 1: Write failing real-component rendering tests**

```tsx
test('review overview renders every required metric and start action', () => {
  const html = renderToStaticMarkup(<ReviewOverview summary={summary} onStart={() => undefined} onManage={() => undefined} />);
  for (const label of ['今日待复习', '新卡片', '今日完成', '预计时长', '连续学习', '逾期卡片', '薄弱知识点', '开始复习']) {
    assert.match(html, new RegExp(label));
  }
});

test('review session exposes four ratings and discoverable shortcuts', () => {
  const html = renderToStaticMarkup(<ReviewSessionPanel state={flippedState} submitting={false} onFlip={() => undefined} onRate={async () => undefined} />);
  for (const label of ['忘记了', '有点模糊', '记住了', '非常熟练', '按 1–4 评分']) assert.match(html, new RegExp(label));
});

test('results show rating distribution time and mastery change', () => {
  const html = renderToStaticMarkup(<ReviewResults results={results} onOverview={() => undefined} onCards={() => undefined} />);
  assert.match(html, /总耗时/);
  assert.match(html, /平均每张/);
  assert.match(html, /掌握度变化/);
});
```

- [ ] **Step 2: Run component tests and verify RED**

Run: `npx tsx --test tests/reviewComponents.test.tsx`

Expected: FAIL because the components do not exist.

- [ ] **Step 3: Implement focused components and page orchestration**

Load summary and due cards in parallel:

```typescript
const loadOverview = useCallback(async () => {
  setLoading(true);
  try {
    const [nextSummary, nextDue] = await Promise.all([
      getReviewSummary(-new Date().getTimezoneOffset()),
      getCards(true),
    ]);
    setSummary(nextSummary);
    setDueCards(nextDue);
  } finally {
    setLoading(false);
  }
}, []);
```

Use page modes `overview | library | session | results`. The library loads all cards only when opened. The editor reuses `createCard` and `updateCard`; deletion uses `Modal.confirm` and reloads the library plus summary. `ReviewSessionPanel` installs one `keydown` listener with stable callbacks, ignores input/textarea targets, and locks while a rating request is pending. Touch handlers call the pure gesture classifier.

Use CSS classes rather than large inline styles. Ensure `.review-progress-count { white-space: nowrap; flex: 0 0 auto; }`, responsive metric grids, visible focus, 44px touch targets, and no horizontal overflow.

- [ ] **Step 4: Run component tests, all frontend tests, and build**

Run: `npx tsx --test tests/*.test.ts tests/*.test.tsx; npm run build`

Expected: all tests PASS and Vite build exits 0.

- [ ] **Step 5: Commit the review UI slice**

```powershell
git add frontend/src/components/review frontend/src/pages/ReviewCenter.tsx frontend/src/styles/app.css frontend/tests/reviewComponents.test.tsx
git commit -m "feat: build complete review center"
```

---

### Task 7: Add Parsed-Source Selection and Workspace Card Generation

**Files:**
- Create: `frontend/src/pages/documentCardSelection.ts`
- Modify: `frontend/src/pages/DocumentDetail.tsx`
- Modify: `frontend/src/pages/KnowledgeBase.tsx`
- Modify: `frontend/src/components/review/CardEditorModal.tsx`
- Create: `frontend/tests/documentCardSelection.test.ts`
- Modify: `frontend/tests/knowledgeBaseDetail.test.tsx`

**Interfaces:**
- Consumes: Task 5 `createSelectionCard`, `generateWorkspaceCards`, and `CardDraft`.
- Produces: normalized parsed-text selection and two visible generation entry points.

- [ ] **Step 1: Write failing selection and generation-entry tests**

```typescript
test('normalizes a same-chunk parsed-text selection', () => {
  assert.deepEqual(normalizeDocumentCardSelection({
    text: '  遗忘\n曲线会下降  ',
    startChunkId: 'chunk-1',
    endChunkId: 'chunk-1',
    page: 3,
    heading: '长期记忆',
  }), {
    excerpt: '遗忘 曲线会下降',
    chunkId: 'chunk-1',
    page: 3,
    heading: '长期记忆',
  });
});

test('rejects empty and cross-chunk selections', () => {
  assert.equal(normalizeDocumentCardSelection({ text: ' ', startChunkId: 'a', endChunkId: 'a' }), null);
  assert.equal(normalizeDocumentCardSelection({ text: 'text', startChunkId: 'a', endChunkId: 'b' }), null);
});
```

Extend the existing knowledge-base component test so the rendered point manager surface contains `批量生成卡片`.

- [ ] **Step 2: Run selection and knowledge-base tests and verify RED**

Run: `npx tsx --test tests/documentCardSelection.test.ts tests/knowledgeBaseDetail.test.tsx`

Expected: FAIL because the helper and bulk action do not exist.

- [ ] **Step 3: Implement selection capture and generation actions**

```typescript
export const normalizeDocumentCardSelection = (input: RawDocumentSelection): DocumentCardSelection | null => {
  const excerpt = input.text.replace(/\s+/g, ' ').trim();
  if (!excerpt || !input.startChunkId || input.startChunkId !== input.endChunkId) return null;
  return { excerpt, chunkId: input.startChunkId, page: input.page, heading: input.heading };
};
```

Mark parsed source articles with `data-chunk-id`, `data-page`, and `data-heading`. On selection completion, require both range endpoints to resolve to the same article within `.document-source`. Show a contextual `从选段生成卡片` button and open `CardEditorModal` with the excerpt as the back, source metadata filled, and the front required.

Add `批量生成卡片` above the knowledge-point list. Submit the current workspace ID and show `已生成 N 张卡片`; reload knowledge-base detail afterward so `card_count` changes immediately.

- [ ] **Step 4: Run targeted and complete frontend tests**

Run: `npx tsx --test tests/documentCardSelection.test.ts tests/knowledgeBaseDetail.test.tsx tests/reviewComponents.test.tsx; npm run build`

Expected: PASS.

- [ ] **Step 5: Commit the source-generation slice**

```powershell
git add frontend/src/pages/documentCardSelection.ts frontend/src/pages/DocumentDetail.tsx frontend/src/pages/KnowledgeBase.tsx frontend/src/components/review/CardEditorModal.tsx frontend/tests/documentCardSelection.test.ts frontend/tests/knowledgeBaseDetail.test.tsx
git commit -m "feat: create cards from sources and knowledge points"
```

---

### Task 8: Complete Regression and Browser Acceptance

**Files:**
- Modify only files whose behavior fails the checks below.
- Do not commit screenshots, traces, or temporary Playwright scripts.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a verified fourth-stage implementation with no known acceptance blocker.

- [ ] **Step 1: Run the full backend suite**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio python -m pytest backend/tests -q`

Expected: all backend tests PASS with zero errors.

- [ ] **Step 2: Run the full frontend suite and production build**

Run: `npx tsx --test tests/*.test.ts tests/*.test.tsx; npm run build`

Expected: all frontend tests PASS and production build exits 0.

- [ ] **Step 3: Rebuild the local Docker application**

Run: `docker compose up -d --build backend frontend`

Expected: backend and frontend containers are running; `docker compose ps` reports the backend healthy.

- [ ] **Step 4: Verify desktop CRUD and review flow with Playwright CLI**

Flow: `/review` → open card library → create a temporary manual card → edit front/tags/difficulty → return to overview → start review → Enter to flip → press 3 to rate → inspect results → delete the temporary card.

Evidence required: correct URL/title, non-empty DOM, no framework overlay, no console errors, visible state changes after create/edit/rate/delete, and screenshots saved outside the repository.

- [ ] **Step 5: Verify 390px and 320px touch layouts**

At 390×844 and 320×740, verify no horizontal overflow, progress count remains on one line, all four rating buttons remain reachable, and synthetic touch gestures produce flip/forgot/remembered actions without blocking ordinary vertical scrolling.

- [ ] **Step 6: Verify source generation flows**

Flow A: knowledge base → batch-generate knowledge-point cards → card count updates.

Flow B: non-PDF parsed document → select text → open prefilled card modal → supply question → create → verify source label and excerpt in the card library.

Flow C: AI learning answer → create card → verify `source_type=answer` through the card library or API.

- [ ] **Step 7: Run migration compatibility against a disposable legacy SQLite database**

Create a temporary database containing the old `flashcards` and `review_logs` schemas, run `run_compat_migrations`, and assert all new columns exist while the original row remains readable. The temporary database must live outside the repository and be deleted after verification.

- [ ] **Step 8: Review the diff and commit final verification fixes**

Run: `git diff --check; git status --short; git log --oneline -10`

If browser or migration verification required code changes, rerun the specific failing test first, then the complete suites. Review `git diff --name-only`, stage each actually changed implementation/test file by its literal path (never `git add .`), and commit the scoped fixes with message `fix: complete phase four acceptance`.

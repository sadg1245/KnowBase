# Phase Five Practice and Assessment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build AI-generated six-type assessments, durable quiz runs and attempts, a complete mistake notebook, explainable weak-knowledge scoring, and review-task integration without losing existing learning data.

**Architecture:** Add a focused assessment domain beside the existing learning models: `QuizSet` owns generated questions, `QuizRun` owns one answer round, and `QuizAttempt` owns immutable submissions. Dedicated scoring, AI, and weakness services keep business rules out of routes; a new assessment router exposes the workflow while the existing quiz endpoints remain compatible. The React practice page becomes a small state-driven shell composed from focused configuration, runner, results, mistake, and weakness components.

**Tech Stack:** Python 3.12+, FastAPI 0.115, SQLAlchemy 2 async, Pydantic 2, LiteLLM, SQLite/PostgreSQL, React 18, TypeScript 5.6, Ant Design 5, Node test runner with `tsx`, Playwright CLI.

**Spec:** `docs/superpowers/specs/2026-09-01-phase-five-practice-assessment-design.md`

## Global Constraints

- AI generation and subjective grading must use the configured model; never silently label deterministic templates as AI output.
- Existing `quiz_questions`, `/api/learning/quizzes/*`, `/practice?wrong=1`, and historical data remain readable.
- Database changes are additive and SQLite compatibility migrations are idempotent.
- Every generated question contains an answer, explanation, rubric where applicable, and validated structured source snapshots.
- Strict-source generation fails atomically when the requested complete paper cannot be supported.
- Correct answers stay hidden until the active answer mode permits reveal.
- Objective scoring remains available when the model is offline; failed subjective grading preserves the attempt as retryable and does not mark it wrong.
- Weakness scoring is deterministic and explainable; AI does not choose the numeric weakness score.
- Preserve unrelated working-tree files and changes.

---

### Task 1: Add durable assessment, mistake, weakness, and task models

**Files:**
- Create: `backend/app/models/assessment.py`
- Create: `backend/app/schemas/assessment.py`
- Create: `backend/tests/test_phase_five_models.py`
- Modify: `backend/app/models/learning.py:108-125`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/migrations.py:16-110`

**Interfaces:**
- Produces ORM classes `QuizSet`, `QuizRun`, `QuizAttempt`, `MistakeRecord`, `WeakKnowledgeState`, and `LearningTask`.
- Extends `QuizQuestion` with `quiz_set_id`, `document_id`, `difficulty_level`, `answer_payload`, `grading_rubric`, `source_snapshot`, `strict_sources`, `generation_model`, and `position`.
- Produces request/response schemas `QuizSetGenerateRequest`, `QuizRunCreateRequest`, `QuestionSubmitRequest`, `PaperSubmitRequest`, `MistakeRedoRequest`, and filter literals shared by later routes.

- [ ] **Step 1: Write failing model and schema tests**

```python
class PhaseFiveModelTests(unittest.TestCase):
    def test_assessment_tables_and_question_extensions_are_registered(self):
        self.assertIn("quiz_sets", Base.metadata.tables)
        self.assertIn("quiz_runs", Base.metadata.tables)
        self.assertIn("quiz_attempts", Base.metadata.tables)
        self.assertIn("mistake_records", Base.metadata.tables)
        self.assertIn("weak_knowledge_states", Base.metadata.tables)
        self.assertIn("learning_tasks", Base.metadata.tables)
        question = Base.metadata.tables["quiz_questions"]
        self.assertIn("answer_payload", question.c)
        self.assertIn("source_snapshot", question.c)

    def test_generation_schema_accepts_all_six_question_types(self):
        request = QuizSetGenerateRequest(
            workspace_id="workspace",
            count=12,
            difficulty="hard",
            question_types=[
                "single_choice", "multiple_choice", "true_false",
                "fill_blank", "short_answer", "concept_explanation",
            ],
            strict_sources=True,
            answer_mode="full_paper",
        )
        self.assertEqual(request.count, 12)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_phase_five_models -v`

Expected: import failure for `app.models.assessment` or missing metadata tables.

- [ ] **Step 3: Implement ORM models, relationships, constraints, and Pydantic schemas**

Use UUID string primary keys, timezone-aware timestamps, JSON for structured payloads, and unique constraints on `(quiz_set_id, round_number)`, `(quiz_run_id, question_id, attempt_number)`, `mistake_records.question_id`, and `weak_knowledge_states.knowledge_point_id`. Keep `QuizQuestion.answer` populated for compatibility.

- [ ] **Step 4: Add idempotent SQLite column migrations**

Extend `additions["quiz_questions"]` with literal SQLite DDL for every new nullable/defaulted column. Add indexes for `quiz_set_id`, `document_id`, mistake status, weakness score, and task due/status using `CREATE INDEX IF NOT EXISTS`.

- [ ] **Step 5: Run model tests and the existing migration suite**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_phase_five_models tests.test_phase_four_models -v`

Expected: all tests pass.

- [ ] **Step 6: Commit the persistence slice**

```powershell
git add backend/app/models/assessment.py backend/app/models/learning.py backend/app/models/__init__.py backend/app/schemas/assessment.py backend/app/core/migrations.py backend/tests/test_phase_five_models.py
git commit -m "feat: persist phase five assessment state"
```

### Task 2: Implement deterministic objective scoring and mistake transitions

**Files:**
- Create: `backend/app/services/assessment_scoring.py`
- Create: `backend/tests/test_assessment_scoring.py`

**Interfaces:**
- Produces `normalize_answer(value: object) -> object`.
- Produces `grade_objective(question_type: str, expected: object, actual: object) -> GradeResult` where `GradeResult` has `is_correct`, `score`, `max_score`, `feedback`, and `error_reason`.
- Produces `next_mistake_state(previous: MistakeState | None, *, correct: bool, is_redo: bool, now: datetime) -> MistakeState`.
- Produces `elapsed_seconds(started_at: datetime, finished_at: datetime, limit: int | None) -> int`.

- [ ] **Step 1: Write failing pure business-rule tests**

```python
def test_multiple_choice_is_order_independent_but_requires_exact_set(self):
    result = grade_objective("multiple_choice", ["A", "C"], ["C", "A"])
    self.assertTrue(result.is_correct)
    self.assertFalse(grade_objective("multiple_choice", ["A", "C"], ["A"]).is_correct)

def test_two_correct_redos_master_a_mistake(self):
    first = next_mistake_state(None, correct=False, is_redo=False, now=NOW)
    improving = next_mistake_state(first, correct=True, is_redo=True, now=NOW)
    mastered = next_mistake_state(improving, correct=True, is_redo=True, now=NOW)
    self.assertEqual(mastered.mastery_status, "mastered")
    self.assertEqual(mastered.redo_count, 2)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_scoring -v`

Expected: import failure for `assessment_scoring`.

- [ ] **Step 3: Implement normalization and all four objective graders**

Implement single choice and true/false scalar comparison, multiple-choice set comparison, and fill-blank positional comparison against one or more accepted answers per blank. Normalize Unicode whitespace, ASCII case, surrounding non-semantic Chinese sentence punctuation and detached ASCII sentence punctuation without fuzzy semantic matching. Preserve signs, operators, decimal points, brackets and identifier punctuation such as C++ and C#.

- [ ] **Step 4: Implement mistake and timer state machines**

The first error creates `unresolved`; an error increments `wrong_count` and resets consecutive correctness; a correct redo increments `redo_count` and transitions `unresolved -> improving -> mastered`; a later error returns to `unresolved`. Clamp elapsed time to zero and the configured limit when present.

- [ ] **Step 5: Run the scoring tests**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_scoring -v`

Expected: all tests pass.

- [ ] **Step 6: Commit the scoring slice**

```powershell
git add backend/app/services/assessment_scoring.py backend/tests/test_assessment_scoring.py
git commit -m "feat: grade objective answers and track mistakes"
```

### Task 3: Add validated AI question generation and subjective grading

**Files:**
- Create: `backend/app/services/assessment_ai.py`
- Create: `backend/tests/test_assessment_ai.py`
- Modify: `backend/app/services/learning_content.py:61-94`

**Interfaces:**
- Produces exception `AssessmentAIError(message: str, status_code: int)`.
- Produces Pydantic contracts `GeneratedQuestion`, `GeneratedPaper`, and `SubjectiveEvaluation`.
- Produces `build_generated_paper(evidence, request, settings, completion=None) -> GeneratedPaper`.
- Produces `evaluate_subjective(question, user_answer, settings, completion=None) -> SubjectiveEvaluation`.
- Reuses a public `resolve_provider_configuration(settings)` extracted from the existing learning-content provider resolution.

- [ ] **Step 1: Write failing AI contract tests with injected completions**

```python
async def test_generation_rejects_unknown_source_chunks(self):
    completion = fake_completion({"questions": [{
        "question_type": "single_choice", "prompt": "Q", "options": ["A", "B"],
        "answer_payload": "A", "explanation": "E", "grading_rubric": {},
        "source_chunk_ids": ["not-retrieved"], "difficulty": "medium",
    }]})
    with self.assertRaisesRegex(AssessmentAIError, "unknown source"):
        await build_generated_paper([EVIDENCE], REQUEST, SETTINGS, completion)

async def test_missing_provider_is_a_409_without_template_fallback(self):
    with self.assertRaises(AssessmentAIError) as raised:
        await build_generated_paper([EVIDENCE], REQUEST, Settings(DEFAULT_LLM_MODEL=""))
    self.assertEqual(raised.exception.status_code, 409)
```

- [ ] **Step 2: Run AI tests and verify RED**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_ai -v`

Expected: import failure for `assessment_ai`.

- [ ] **Step 3: Extract provider resolution without changing learning generation behavior**

Rename `_provider_configuration` to `resolve_provider_configuration`, keep a compatibility alias if existing tests import the private name, and verify `tests.test_learning_content` still passes.

- [ ] **Step 4: Implement the generation prompt and structured validation**

Mark source blocks as untrusted, require exactly the requested count, validate six question types, objective answers, rubric presence for subjective questions, and references restricted to supplied chunk IDs. Map missing configuration to 409, insufficient strict evidence to 422, invalid model output to 502, and provider failure to 503. Retry one invalid structured response using a repair prompt, never a deterministic paper.

- [ ] **Step 5: Implement subjective evaluation**

Send only the prompt, answer, rubric, user response, and stored source snapshots. Require `score`, `max_score`, `is_correct`, `feedback`, `error_reason`, `matched_points`, and `missing_points` in the response.

- [ ] **Step 6: Run AI and learning-content tests**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_ai tests.test_learning_content -v`

Expected: all tests pass.

- [ ] **Step 7: Commit the AI slice**

```powershell
git add backend/app/services/assessment_ai.py backend/app/services/learning_content.py backend/tests/test_assessment_ai.py
git commit -m "feat: generate and grade assessments with ai"
```

### Task 4: Orchestrate quiz sets, runs, submissions, and mistake persistence

**Files:**
- Create: `backend/app/services/assessment_service.py`
- Create: `backend/tests/test_assessment_service.py`

**Interfaces:**
- Consumes the Task 1 models/schemas and Task 2/3 grading functions.
- Produces `generate_quiz_set(db, request, settings, completion=None) -> QuizSet`.
- Produces `create_quiz_run(db, quiz_set_id, *, resume=False) -> QuizRun`.
- Produces `start_quiz_run(db, run_id, now=None) -> QuizRun`.
- Produces `submit_question(db, run_id, question_id, payload, settings, completion=None, now=None, is_redo=False) -> QuizAttempt`.
- Produces `submit_paper(db, run_id, answers, settings, completion=None, now=None) -> QuizRun`.
- Produces serializers that hide answers before reveal and return complete results afterward.

- [ ] **Step 1: Write failing transaction and state-machine tests**

```python
async def test_wrong_submission_creates_attempt_mistake_and_updates_compatibility_fields(self):
    attempt = await submit_question(self.db, run.id, question.id, QuestionSubmitRequest(answer="B", duration_seconds=12), settings)
    mistake = (await self.db.execute(select(MistakeRecord))).scalar_one()
    self.assertFalse(attempt.is_correct)
    self.assertEqual(mistake.wrong_count, 1)
    self.assertEqual(question.last_answer, "B")
    self.assertFalse(question.last_correct)

async def test_retry_creates_a_new_run_without_overwriting_history(self):
    retry = await create_quiz_run(self.db, quiz_set.id)
    self.assertEqual(retry.round_number, 2)
    self.assertNotEqual(retry.id, first_run.id)
```

- [ ] **Step 2: Run service tests and verify RED**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_service -v`

Expected: import failure for `assessment_service`.

- [ ] **Step 3: Implement scope validation and atomic generation**

Validate workspace, documents, points, and chunk filters before calling AI. Gather ordered `DocumentChunk` evidence, call `build_generated_paper`, then persist the set and every question in one transaction. Failed generation records `QuizSet.status="failed"` only when the set already exists and never stores partial questions.

- [ ] **Step 4: Implement run lifecycle and answer visibility**

Create monotonic rounds, idempotently start one run, calculate elapsed time from server timestamps, and serialize questions without `answer_payload`, `answer`, or rubric before permitted reveal.

- [ ] **Step 5: Implement per-question and full-paper submission**

Create immutable attempts, call objective or subjective grading, synchronize compatibility counters, update or resolve `MistakeRecord`, update linked knowledge-point mastery/status, and record real duration in `StudyActivity`. Full-paper submission grades every supplied answer and computes run totals only from graded attempts.

- [ ] **Step 6: Preserve subjective attempts when AI grading fails**

Create an attempt with `evaluation_status="grading_failed"`, `is_correct=None`, and the user answer; do not create a mistake or alter accuracy until retry grading succeeds.

- [ ] **Step 7: Run service tests**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_service -v`

Expected: all tests pass.

- [ ] **Step 8: Commit the orchestration slice**

```powershell
git add backend/app/services/assessment_service.py backend/tests/test_assessment_service.py
git commit -m "feat: manage quiz runs attempts and mistakes"
```

### Task 5: Calculate explainable weakness and create review tasks

**Files:**
- Create: `backend/app/services/weakness_service.py`
- Create: `backend/tests/test_weakness_service.py`
- Modify: `backend/app/services/review_service.py:59-136`
- Modify: `backend/app/api/routes/learning.py:128-167`

**Interfaces:**
- Produces `WeaknessMetrics` and `WeaknessScore` dataclasses.
- Produces `calculate_weakness(metrics, now) -> WeaknessScore` with 35/25/15/10/15 component weights.
- Produces `recalculate_knowledge_point(db, point_id, now=None) -> WeakKnowledgeState`.
- Produces `upsert_weak_learning_tasks(db, state, now=None) -> list[LearningTask]`.
- Produces `weakness_priority_subquery()` for review ordering.

- [ ] **Step 1: Write failing component and task-idempotency tests**

```python
def test_weakness_score_exposes_all_weighted_components(self):
    score = calculate_weakness(METRICS, NOW)
    self.assertEqual(score.total, 72)
    self.assertEqual(
        set(score.components),
        {"accuracy", "repeat_error", "review_feedback", "response_time", "recency"},
    )

async def test_recalculation_keeps_one_pending_task_per_point_and_type(self):
    await upsert_weak_learning_tasks(self.db, state, NOW)
    await upsert_weak_learning_tasks(self.db, state, NOW)
    rows = (await self.db.execute(select(LearningTask))).scalars().all()
    self.assertEqual(len(rows), 2)
```

- [ ] **Step 2: Run weakness tests and verify RED**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_weakness_service -v`

Expected: import failure for `weakness_service`.

- [ ] **Step 3: Implement deterministic component calculations**

Use the most recent 20 attempts with exponential recency weighting, unresolved mistake counts, recent review ratings, per-type/difficulty personal median duration, and last relevant activity time. Clamp each component and the total to 0–100 and store the raw evidence counts and timestamps.

- [ ] **Step 4: Implement recommendation paths and idempotent tasks**

For scores at least 60 create five recommended actions. Persist only `review` and `targeted_practice` as due tasks within three days; expose all five actions in `recommended_actions`. Reuse pending tasks instead of inserting duplicates.

- [ ] **Step 5: Integrate weakness into dashboard and review ordering**

Add due `LearningTask` rows to `today_tasks`. Outer join due flashcards to `WeakKnowledgeState` and order by weakness descending then `due_at`, without changing card due dates.

- [ ] **Step 6: Recalculate after quiz submission and card review**

Call `recalculate_knowledge_point` only for the affected point after the attempt/review has been flushed. Keep this call in the same transaction so dashboard and review ordering cannot observe stale state.

- [ ] **Step 7: Run weakness, review, and dashboard tests**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_weakness_service tests.test_review_service tests.test_review_summary -v`

Expected: all tests pass.

- [ ] **Step 8: Commit the weakness slice**

```powershell
git add backend/app/services/weakness_service.py backend/app/services/review_service.py backend/app/services/assessment_service.py backend/app/api/routes/learning.py backend/tests/test_weakness_service.py backend/tests/test_review_service.py backend/tests/test_review_summary.py
git commit -m "feat: prioritize review with weak knowledge"
```

### Task 6: Expose assessment, mistake, weakness, and task APIs

**Files:**
- Create: `backend/app/api/routes/assessments.py`
- Create: `backend/tests/test_assessment_api.py`
- Modify: `backend/app/main.py:65-76`
- Modify: `backend/app/api/routes/learning.py:574-628`
- Modify: `backend/app/api/routes/chat_sessions.py:204-223`
- Modify: `backend/app/api/routes/learning.py:654-671`

**Interfaces:**
- Produces the complete `/api/learning/quiz-sets`, `/quiz-runs`, `/mistakes`, `/weak-knowledge`, and `/tasks` routes specified by the design.
- Keeps existing `/api/learning/quizzes/*` endpoints and chat-created mistakes compatible with new mistake records.
- Extends learning export with `quiz_sets`, `quiz_runs`, `quiz_attempts`, `mistakes`, `weak_knowledge`, and `learning_tasks`.

- [ ] **Step 1: Write failing route-contract and response-hiding tests**

```python
def test_phase_five_routes_are_registered(self):
    paths = {route.path for route in app.routes}
    self.assertIn("/api/learning/quiz-sets/generate", paths)
    self.assertIn("/api/learning/quiz-runs/{run_id}/submit", paths)
    self.assertIn("/api/learning/mistakes", paths)
    self.assertIn("/api/learning/weak-knowledge", paths)

async def test_unsubmitted_quiz_set_does_not_reveal_answers(self):
    payload = await routes.get_quiz_set(quiz_set.id, self.db)
    self.assertNotIn("answer", payload["questions"][0])
    self.assertNotIn("answer_payload", payload["questions"][0])
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_api -v`

Expected: missing route or import failure.

- [ ] **Step 3: Implement route handlers and status mapping**

Use service functions rather than duplicating business rules. Preserve `AssessmentAIError.status_code`; map missing rows to 404, cross-scope input to 400, invalid state transitions to 409, and validation shortfalls to 422.

- [ ] **Step 4: Implement list filters and task completion**

Support workspace, document, knowledge point, mastery status, due date, and pagination filters. Completing a task sets `completed_at`, records a `StudyActivity`, and recalculates its knowledge point.

- [ ] **Step 5: Upgrade legacy quiz and chat mistake adapters**

Legacy generated questions write compatible structured fields. Legacy submission creates `QuizAttempt` and `MistakeRecord` through the shared service. Chat mistakes create an unresolved `MistakeRecord` using the message source snapshot while keeping idempotent `origin_message_id` behavior.

- [ ] **Step 6: Extend the portable export**

Serialize all phase-five entities without dropping old fields. The export remains read-only and uses ISO timestamps.

- [ ] **Step 7: Run API and regression tests**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_assessment_api tests.test_conversation_service tests.test_document_management tests.test_regressions -v`

Expected: all tests pass.

- [ ] **Step 8: Commit the API slice**

```powershell
git add backend/app/api/routes/assessments.py backend/app/api/routes/learning.py backend/app/api/routes/chat_sessions.py backend/app/main.py backend/tests/test_assessment_api.py backend/tests/test_conversation_service.py backend/tests/test_regressions.py
git commit -m "feat: expose phase five assessment APIs"
```

### Task 7: Add frontend assessment contracts and state machine

**Files:**
- Create: `frontend/src/features/practice/types.ts`
- Create: `frontend/src/features/practice/practiceSession.ts`
- Create: `frontend/tests/practiceSession.test.ts`
- Modify: `frontend/src/services/api.ts:384-452`

**Interfaces:**
- Produces TypeScript types matching all new API schemas.
- Produces API functions `generateQuizSet`, `getQuizSet`, `createQuizRun`, `startQuizRun`, `submitQuizQuestion`, `submitQuizPaper`, `retryQuizRun`, `retryAttemptGrading`, `getMistakes`, `redoMistake`, `getWeakKnowledge`, `getLearningTasks`, and `completeLearningTask`.
- Produces pure state functions `createPracticeSession`, `setAnswer`, `recordAttempt`, `remainingSeconds`, `unansweredQuestionIds`, and `practiceResults`.

- [ ] **Step 1: Write failing state-machine tests**

```typescript
test('full paper keeps answers hidden and reports unanswered questions', () => {
  const state = setAnswer(createPracticeSession(run, questions, 1_000), 'q1', 'A');
  assert.deepEqual(unansweredQuestionIds(state), ['q2']);
  assert.equal(state.revealedQuestionIds.size, 0);
});

test('timer resumes from server started_at and clamps at the limit', () => {
  assert.equal(remainingSeconds(runWithLimit, Date.parse(runWithLimit.started_at) + 61_000), 0);
});
```

- [ ] **Step 2: Run the frontend state test and verify RED**

Run: `cd frontend && node --import tsx --test tests/practiceSession.test.ts`

Expected: import failure for `features/practice/practiceSession`.

- [ ] **Step 3: Implement API contracts and pure session state**

Represent answers as `string | string[]`, use immutable state updates, store only the active run draft under a versioned `sessionStorage` key, and derive progress/results instead of duplicating them in React effects.

- [ ] **Step 4: Run the state tests and TypeScript build**

Run: `cd frontend && node --import tsx --test tests/practiceSession.test.ts`

Run: `cd frontend && npm run build`

Expected: both commands pass.

- [ ] **Step 5: Commit the frontend contract slice**

```powershell
git add frontend/src/features/practice/types.ts frontend/src/features/practice/practiceSession.ts frontend/src/services/api.ts frontend/tests/practiceSession.test.ts
git commit -m "feat: model phase five practice sessions"
```

### Task 8: Build configurable quiz generation, runner, and results UI

**Files:**
- Create: `frontend/src/components/practice/PracticeBuilder.tsx`
- Create: `frontend/src/components/practice/QuestionInput.tsx`
- Create: `frontend/src/components/practice/QuizRunner.tsx`
- Create: `frontend/src/components/practice/QuizResults.tsx`
- Create: `frontend/tests/practiceComponents.test.tsx`
- Modify: `frontend/src/pages/Practice.tsx`
- Modify: `frontend/src/styles/app.css`

**Interfaces:**
- `PracticeBuilder` emits a complete `QuizSetGenerateRequest` with scope, count, difficulty, six question types, strict mode, answer mode, and optional duration.
- `QuestionInput` renders radio, checkbox, true/false, fill-blank, or text-area controls from `question_type`.
- `QuizRunner` supports sequential and full-paper navigation, timer display, submission guards, restored drafts, and retryable AI grading states.
- `QuizResults` displays score, accuracy, elapsed time, per-question answer/feedback/explanation, and clickable source snapshots.

- [ ] **Step 1: Write failing component contract tests**

```tsx
test('builder exposes every phase five configuration control', () => {
  const html = renderToStaticMarkup(<PracticeBuilder {...builderProps} />);
  for (const label of ['知识库', '章节或知识点', '题目数量', '难度', '单项选择题', '多项选择题', '判断题', '填空题', '简答题', '解释概念题', '严格依据资料', '逐题答题', '整卷答题']) {
    assert.match(html, new RegExp(label));
  }
});

test('results render answer explanation feedback and source links', () => {
  const html = renderToStaticMarkup(<QuizResults run={gradedRun} onRetry={() => undefined} onSource={() => undefined} />);
  for (const label of ['参考答案', '解析', 'AI 评价', '资料引用', '重新作答']) assert.match(html, new RegExp(label));
});
```

- [ ] **Step 2: Run component tests and verify RED**

Run: `cd frontend && node --import tsx --test tests/practiceComponents.test.tsx`

Expected: imports fail because the new components do not exist.

- [ ] **Step 3: Implement the builder and question inputs**

Reuse existing knowledge-base/document selectors and request guards. Load knowledge points after workspace selection. Disable generation until at least one question type and one ready source are selected. Send the effective document scope, not the empty UI sentinel used to mean “all ready documents.”

- [ ] **Step 4: Implement runner, timer, recovery, and results**

Start independent fetches together, keep timer ticks in one interval with cleanup, use primitive effect dependencies, and derive progress from answer maps. Require confirmation before full-paper submission with unanswered questions. Display AI failure without discarding answers and expose retry grading.

- [ ] **Step 5: Replace the legacy page with the state-driven shell**

Keep `/practice` and query-string compatibility. The page owns remote loading/error transitions and delegates rendered states to focused components; do not define components inline.

- [ ] **Step 6: Add responsive styling**

Desktop uses a readable centered paper with side navigation for full-paper mode. At widths below 768px, controls become one column, the question navigator scrolls horizontally, and answer actions remain visible without covering content. Respect the existing reduced-motion rules.

- [ ] **Step 7: Run component tests, all frontend tests, and build**

Run: `cd frontend && node --import tsx --test tests/practiceComponents.test.tsx tests/practiceSession.test.ts`

Run: `cd frontend && $testFiles = Get-ChildItem tests -File | Where-Object { $_.Name -match '\.test\.tsx?$' } | ForEach-Object { $_.FullName }; node --import tsx --test $testFiles`

Run: `cd frontend && npm run build`

Expected: all commands pass.

- [ ] **Step 8: Commit the quiz UI slice**

```powershell
git add frontend/src/components/practice frontend/src/pages/Practice.tsx frontend/src/styles/app.css frontend/tests/practiceComponents.test.tsx
git commit -m "feat: build complete assessment experience"
```

### Task 9: Build mistake notebook and weak-knowledge actions

**Files:**
- Create: `frontend/src/components/practice/MistakeNotebook.tsx`
- Create: `frontend/src/components/practice/WeakKnowledgePanel.tsx`
- Create: `frontend/tests/mistakeWeaknessComponents.test.tsx`
- Modify: `frontend/src/pages/Practice.tsx`
- Modify: `frontend/src/components/review/ReviewOverview.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/styles/app.css`

**Interfaces:**
- `MistakeNotebook` displays question, latest answer, correct answer, reason, knowledge point, sources, counts, status, and redo action.
- `WeakKnowledgePanel` displays total/component scores and five recommendation actions.
- Dashboard and review-center tasks navigate to the exact recommendation path returned by the API.

- [ ] **Step 1: Write failing mistake and weakness component tests**

```tsx
test('mistake notebook exposes every required durable field and redo', () => {
  const html = renderToStaticMarkup(<MistakeNotebook mistakes={[mistake]} onRedo={() => undefined} onSource={() => undefined} />);
  for (const label of ['你的答案', '正确答案', '错误原因', '知识点', '来源资料', '重做次数', '当前掌握状态', '重新练习']) assert.match(html, new RegExp(label));
});

test('weak knowledge exposes five recommended actions', () => {
  const html = renderToStaticMarkup(<WeakKnowledgePanel items={[weak]} onAction={() => undefined} />);
  for (const label of ['重新阅读', '通俗讲解', '生成新例子', '针对性练习', '加入近期复习']) assert.match(html, new RegExp(label));
});
```

- [ ] **Step 2: Run component tests and verify RED**

Run: `cd frontend && node --import tsx --test tests/mistakeWeaknessComponents.test.tsx`

Expected: component imports fail.

- [ ] **Step 3: Implement the mistake notebook**

Use filters for workspace, source, knowledge point, and mastery status. Redo opens one focused question using the new run/attempt flow; a correct result updates the displayed mastery state from the server response.

- [ ] **Step 4: Implement weak knowledge and recommendation navigation**

Show the five weighted components with accessible labels and deterministic color thresholds. Use server paths for source navigation, `/learn` mode/query presets, targeted practice filters, and task creation/completion.

- [ ] **Step 5: Connect dashboard and review center**

Render pending weak tasks with their due dates and use weakness-aware order returned by the backend. Preserve existing flashcard review actions and overview metrics.

- [ ] **Step 6: Run component and full frontend tests**

Run: `cd frontend && node --import tsx --test tests/mistakeWeaknessComponents.test.tsx tests/reviewComponents.test.tsx`

Run: `cd frontend && $testFiles = Get-ChildItem tests -File | Where-Object { $_.Name -match '\.test\.tsx?$' } | ForEach-Object { $_.FullName }; node --import tsx --test $testFiles`

Expected: all tests pass.

- [ ] **Step 7: Commit the learning-loop UI slice**

```powershell
git add frontend/src/components/practice/MistakeNotebook.tsx frontend/src/components/practice/WeakKnowledgePanel.tsx frontend/src/pages/Practice.tsx frontend/src/components/review/ReviewOverview.tsx frontend/src/pages/Dashboard.tsx frontend/src/styles/app.css frontend/tests/mistakeWeaknessComponents.test.tsx frontend/tests/reviewComponents.test.tsx
git commit -m "feat: connect mistakes weakness and review tasks"
```

### Task 10: Verify migrations, regressions, and real browser flows

**Files:**
- Modify: `README.md`
- Modify only if a failing acceptance check requires it: files introduced or changed in Tasks 1–9

**Interfaces:**
- Produces an evidence-backed final acceptance matrix for all six stage-five criteria.
- Produces no committed screenshots, traces, generated databases, or temporary scripts.

- [ ] **Step 1: Run the complete backend suite**

Run: `cd backend && ..\.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 2: Run the complete frontend suite**

Run: `cd frontend && $testFiles = Get-ChildItem tests -File | Where-Object { $_.Name -match '\.test\.tsx?$' } | ForEach-Object { $_.FullName }; node --import tsx --test $testFiles`

Expected: all tests pass.

- [ ] **Step 3: Run the production build**

Run: `cd frontend && npm run build`

Expected: TypeScript and Vite finish with exit code 0.

- [ ] **Step 4: Verify upgrade from a legacy SQLite schema**

Create a temporary database outside the repository with the pre-phase-five `quiz_questions` shape, run `run_compat_migrations`, run it a second time, and assert every new column/index exists while the legacy row and answer remain unchanged.

- [ ] **Step 5: Run desktop Playwright acceptance**

Flow: `/practice` -> configure all requested fields -> generate a six-type strict-source paper -> start sequential mode -> answer one objective and one subjective question -> verify timer, answer, explanation, AI feedback, and source navigation -> intentionally miss a question -> verify it appears in the mistake notebook -> redo it twice correctly -> verify mastered status. Use Playwright route fixtures for the browser workflow unless a local no-cost model is already configured; AI provider behavior itself is proven by backend tests with injected completion functions, and verification must not consume a paid external model without explicit authorization.

- [ ] **Step 6: Run weak-knowledge and review-link acceptance**

Flow: create repeated errors and a low card review -> open weak knowledge -> verify five components and actions -> add recent review -> open dashboard and review center -> verify task visibility and weakness-aware order.

- [ ] **Step 7: Run mobile Playwright acceptance**

Use a 390×844 viewport. Verify configuration controls do not clip, full-paper navigation scrolls, answer inputs remain usable, results and citations are readable, and the console contains no relevant errors or warnings.

- [ ] **Step 8: Update user documentation**

Document six question types, generation controls, AI configuration requirement, sequential/full-paper modes, mistake mastery rules, weakness score inputs, recommendation actions, and the behavior when AI generation or grading is unavailable.

- [ ] **Step 9: Re-run verification after documentation and any acceptance fixes**

Repeat Steps 1–3 and inspect `git diff --check`. Do not claim completion from an earlier run.

- [ ] **Step 10: Commit final verification and documentation changes**

```powershell
git add README.md
git add backend frontend
git commit -m "docs: complete phase five acceptance"
```

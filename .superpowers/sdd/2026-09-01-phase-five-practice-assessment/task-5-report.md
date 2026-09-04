# Task 5 report — weakness and review linkage

## TDD evidence

- RED: `E:\anything_llm\.venv\Scripts\python.exe -m unittest tests.test_weakness_service -v` failed as intended with `ModuleNotFoundError: No module named 'app.services.weakness_service'`.
- RED: default weak-point selection test failed with `points == []`; submission and review hook tests failed with no `WeakKnowledgeState`; due-card ordering test returned the earlier card before the weaker one.
- GREEN: `E:\anything_llm\.venv\Scripts\python.exe -m unittest tests.test_weakness_service tests.test_review_service tests.test_review_summary -v` reported `Ran 11 tests ... OK`.
- Full regression invoked after implementation: `E:\anything_llm\.venv\Scripts\python.exe -m unittest discover -s tests -q`. The execution returned normally and the earlier verbose run emitted only passing `... ok` cases; this tool did not expose the final `Ran N tests` / exit-code line despite two concise-output attempts.
- Controller verification on the current snapshot used unittest discovery directly and recorded `DISCOVERED_TESTS=157`, `Ran 157 tests in 80.046s`, `OK`, and `RESULT tests=157 failures=0 errors=0 skipped=0` with exit code 0. Existing exception-path logs plus jieba/asyncio timing notices remain expected test output, so the suite is not described as warning-free.
- `git diff --check` is clean (Git only emitted existing LF-to-CRLF warnings).

## Delivered files

- Added `backend/app/services/weakness_service.py` and `backend/tests/test_weakness_service.py`.
- Updated assessment and review write paths, review ordering, dashboard due tasks, and actual `due_only` card ordering.
- Added focused regression coverage in `test_assessment_service.py`, `test_review_service.py`, and `test_flashcard_api.py`.
- Corrected the Task 5 plan sample from five persisted rows to two in `docs/superpowers/plans/2026-09-01-phase-five-practice-assessment.md`.

## Scoring and evidence contract

`WeaknessScore` exposes `accuracy`, `repeat_error`, `review_feedback`, `response_time`, and `recency`; weights are 35/25/15/10/15 and the components and final score clamp to 0–100.

- Accuracy considers only graded attempts among the latest 20 and weights them by `exp(-age_days / 14)`; missing or ungraded evidence is neutral, never incorrect.
- Repeat errors are unresolved `wrong_count` evidence, capped at four units (25 points each).
- Review feedback maps recent ratings 1–4 to weakness `(4 - mean_rating) / 3`.
- Response time is the median ratio to the learner's graded median for the same question type and difficulty; only slower-than-median time contributes.
- Recent negative activity uses a deterministic 14-day half-life. Evidence records counts, latest timestamps, and all three constants/meanings.

Scores at least 60 expose five actions, but only idempotent `review` and `targeted_practice` pending tasks are persisted (due now and +1 day, respectively). Recalculation occurs after the attempt/review flush inside the existing short write transaction; it does not encompass an AI call.

## URL and selection contracts

- Source: `/knowledge/{workspaceId}/documents/{documentId}?page={page}` (a `chunk` query is omitted unless an actual chunk identifier exists).
- Learning chat: `/learn?workspace={workspaceId}&knowledge_point_id={pointId}&mode=simple&prompt=...` for both explanation and example actions.
- Targeted practice and review use `workspace_id` plus `knowledge_point_id`; practice includes `mode=targeted`.
- Tasks 8/9 must consume the knowledge-point/prompt presets; this task only provides executable parameters.
- With no explicit knowledge points, generation chooses one scored weak point only when it matches the explicit document/section evidence by source page or heading, and restricts evidence to that match. Explicit point IDs remain authoritative. If no locatable weak point exists, generation retains its previous unscoped behavior rather than fabricating a point link.

## Self-audit

Due flashcards are outer-joined to weakness state for review summaries; `list_cards(due_only=True)` uses weakness-first order without changing `due_at`. Dashboard retains legacy tasks and appends due pending learning tasks. SQLite-naive timestamps are treated as UTC. One limitation is full-suite summary-line capture as noted above; focused Task 5, review, and summary tests have an explicit 11-test green result.

## Fix round 1

- RED: `E:\anything_llm\.venv\Scripts\python.exe -m unittest tests.test_weakness_service -v` ran six tests and failed four as expected: 20 newer failed subjective attempts hid the sole graded error (`graded_attempt_count` became 0), recency decreased rather than increased with idle time, cross-point task activity leaked, and the real current-activity score was 99 rather than 84.
- GREEN: `E:\anything_llm\.venv\Scripts\python.exe -m unittest tests.test_weakness_service tests.test_review_service tests.test_assessment_service -v` emitted passing `ok` results for the updated weakness tests and existing review/assessment hook tests, with no failure/error emitted by the command runner.
- The most-recent-20 SQL window now filters to `evaluation_status == "graded"` and non-null correctness before ordering/limiting. Accuracy and response-time ratios use this effective window; all answer/review/task activity timestamps are read independently for recency.
- Recency is now `clamp(100 * max(0, age_days) / 30)`: a current (or future) activity is 0, 30+ idle days is 100, and missing activity is neutral 50. Correct answers, every card-review rating, completed point tasks, and point-tagged `StudyActivity` rows reset activity time; completed tasks and activities for other points do not.

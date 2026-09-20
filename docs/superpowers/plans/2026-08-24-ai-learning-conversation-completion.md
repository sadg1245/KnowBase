# AI Learning Conversation Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 执行状态：本计划的复选框未回填（TDD 步骤留痕），不代表未执行。
> 实际实现状态见 `docs/2026-09-18-knowbase-project-design.md` §13 与对应阶段测试。

**Goal:** Finish the persistence, evidence-audit, interrupted-generation recovery, and responsive browser acceptance work that remains after the first implementation of the AI learning conversation design.

**Architecture:** Keep the existing FastAPI/SQLAlchemy modular monolith and React page decomposition. Complete compatibility and evidence correctness in small backend helpers that are directly unit tested, then add frontend recovery state without expanding `LearningChat.tsx` further, and finish with browser and Docker verification.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, SQLite FTS5, ChromaDB, pytest, React 18, TypeScript, Ant Design, Vite, Node test runner, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-22-ai-learning-conversation-hybrid-retrieval-design.md`

## Global Constraints

- Keep SQLite FTS5 and ChromaDB; do not introduce Elasticsearch, OpenSearch, Qdrant, or another resident service.
- Keep deterministic RRF/reranking with `k=60`, vector weight `0.65`, keyword weight `0.35`, and at most eight evidence citations.
- Strict-source mode calls the model only for `supported` evidence and rejects `limited` or `insufficient` evidence deterministically.
- Preserve existing workspaces, documents, cards, quiz questions, learning progress, historical source snapshots, and local Docker deployment.
- Desktop breakpoints remain `>=1280px` three-column, `900-1279px` two-column, and `<900px` single-column.
- External models, ChromaDB, and embeddings are replaced by fixed fakes in automated tests.
- Existing completed baseline must stay green: 34 backend tests, 23 backend subtests, 2 Feishu tests, 15 frontend tests, and `npm run build`.

---

### Task 1: Reproducible test entry point and legacy-session compatibility

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `backend/app/core/migrations.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routes/search.py`
- Modify: `backend/app/schemas/schemas.py`
- Modify: `backend/tests/test_conversation_service.py`
- Modify: `backend/tests/test_regressions.py`

**Interfaces:**
- Consumes: existing `chat_sessions` and `conversations` tables.
- Produces: `backfill_legacy_chat_sessions(conn) -> int` and `requested_session_id(session_id: str | None) -> str | None`.

- [ ] **Step 1: Add failing migration and compatibility tests**

```python
async def test_legacy_conversations_are_backfilled_once(self):
    # Insert two session-less messages for one legacy user/workspace.
    # Run backfill twice and assert one ChatSession exists, both messages point
    # to it, the title comes from the first user question, and the second run
    # reports zero migrated groups.

def test_legacy_conversation_id_does_not_force_session_lookup(self):
    request = ChatRequest(question="旧客户端问题", workspace_id="workspace", conversation_id="legacy-thread")
    self.assertIsNone(requested_session_id(request.session_id))
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `$env:PYTHONPATH='E:\anything_llm\backend'; uv run --with pytest --with pytest-asyncio pytest -q backend/tests/test_conversation_service.py backend/tests/test_regressions.py`

Expected: failure because the backfill and session-selection helper do not exist.

- [ ] **Step 3: Add pytest development dependencies and root test discovery**

```toml
[dependency-groups]
dev = [
    "pytest>=8.3,<9",
    "pytest-asyncio>=0.24,<1",
]

[tool.pytest.ini_options]
pythonpath = ["backend", "feishu-bot"]
testpaths = ["backend/tests", "feishu-bot/tests"]
```

Run: `uv lock`

- [ ] **Step 4: Implement idempotent historical-message backfill**

```python
async def backfill_legacy_chat_sessions(conn) -> int:
    """Group session-less historical messages by owner and workspace."""
    # Select only conversations whose session_id IS NULL.
    # Insert one UUID chat_sessions row per distinct user/workspace group.
    # Derive a 24-character normalized title from the first user message.
    # Update only still-null conversation rows in the same transaction.
    # Return the number of groups migrated; a repeat run returns zero.
```

Call it after `Base.metadata.create_all` and compatibility column creation, before the application accepts requests.

- [ ] **Step 5: Restore the documented old-client behavior**

```python
def requested_session_id(session_id: str | None) -> str | None:
    return session_id
```

Use only `payload.session_id` for persistent-session lookup. Keep `conversation_id` accepted by the request schema and keep returning it in the `done` event, but a request that omits `session_id` must create a new session.

- [ ] **Step 6: Run focused and full backend tests**

Run: `uv run pytest -q`

Expected: all backend and Feishu tests pass from the repository root without setting `PYTHONPATH` or injecting pytest packages.

- [ ] **Step 7: Commit the compatibility slice**

```bash
git add pyproject.toml uv.lock backend/app/core/migrations.py backend/app/main.py backend/app/api/routes/search.py backend/app/schemas/schemas.py backend/tests/test_conversation_service.py backend/tests/test_regressions.py
git commit -m "fix: preserve legacy learning conversations"
```

### Task 2: Evidence grouping and citation-audit consistency

**Files:**
- Modify: `backend/app/models/chat.py`
- Modify: `backend/app/services/hybrid_retrieval.py`
- Modify: `backend/app/services/learning_answer.py`
- Modify: `backend/app/api/routes/search.py`
- Modify: `backend/app/schemas/schemas.py`
- Modify: `backend/tests/test_hybrid_retrieval.py`
- Modify: `backend/tests/test_learning_answer.py`

**Interfaces:**
- Consumes: ranked `RetrievalCandidate` objects and generated answer text containing `[资料N]` citations.
- Produces: `EvidenceGroup`, `group_adjacent_evidence(...)`, `referenced_source_numbers(...)`, and `mark_cited_retrieval_hits(...)`.

- [ ] **Step 1: Add failing evidence-group and citation tests**

```python
def test_adjacent_chunks_from_same_document_are_one_source(self):
    groups = group_adjacent_evidence([
        candidate("a", document_id="doc", chunk_index=4, page_num=2),
        candidate("b", document_id="doc", chunk_index=5, page_num=2),
        candidate("c", document_id="other", chunk_index=1, page_num=1),
    ])
    self.assertEqual([group.chunk_ids for group in groups], [["a", "b"], ["c"]])

def test_referenced_source_numbers_are_unique_valid_and_ordered(self):
    self.assertEqual(referenced_source_numbers("结论[资料2]。补充[资料2][资料1]", 2), [2, 1])
```

Add an async test that persists three `RetrievalHit` rows, marks source 2 as cited, and asserts only the chunks belonging to source 2 have `cited_in_answer=True`.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `uv run pytest -q backend/tests/test_hybrid_retrieval.py backend/tests/test_learning_answer.py`

Expected: failure because grouping and citation-audit helpers do not exist.

- [ ] **Step 3: Preserve chunk adjacency metadata in candidates**

```python
@dataclass
class RetrievalCandidate:
    chunk_id: str
    document_id: str | None
    chunk_index: int | None
    # existing source, page, heading, content, and score fields remain

@dataclass
class EvidenceGroup:
    chunk_ids: list[str]
    document_id: str | None
    source_file: str
    page_num: int | None
    heading: str | None
    content: str
    score: float
```

Load `chunk_index` from both FTS and Chroma metadata. Merge only directly adjacent chunks from the same document and page, retain rank order, join content once, and cap the resulting source list at eight.

- [ ] **Step 4: Parse citations and update the retrieval audit**

```python
def referenced_source_numbers(answer: str, source_count: int) -> list[int]:
    values = [int(value) for value in re.findall(r"\[资料(\d+)\]", answer)]
    return list(dict.fromkeys(value for value in values if 1 <= value <= source_count))

async def mark_cited_retrieval_hits(db, run_id: str, cited_chunk_ids: set[str]) -> None:
    await db.execute(
        update(RetrievalHit)
        .where(RetrievalHit.retrieval_run_id == run_id)
        .values(cited_in_answer=False)
    )
    if cited_chunk_ids:
        await db.execute(
            update(RetrievalHit)
            .where(RetrievalHit.retrieval_run_id == run_id, RetrievalHit.chunk_id.in_(cited_chunk_ids))
            .values(cited_in_answer=True)
        )
```

After final strict filtering or non-strict generation, translate cited source numbers to every chunk ID in the matching evidence groups before saving the assistant message.

- [ ] **Step 5: Return grouped source snapshots to SSE clients**

Each source snapshot keeps `content`, `source_file`, `page_num`, `heading`, `score`, and `document_id`, and adds `chunk_ids`. The prompt and UI numbering must use this same grouped list so `[资料N]`, displayed sources, and `retrieval_hits.cited_in_answer` cannot drift.

- [ ] **Step 6: Run focused and full tests**

Run: `uv run pytest -q`

Expected: all tests pass, including degradation and deterministic threshold boundaries.

- [ ] **Step 7: Commit the evidence slice**

```bash
git add backend/app/models/chat.py backend/app/services/hybrid_retrieval.py backend/app/services/learning_answer.py backend/app/api/routes/search.py backend/app/schemas/schemas.py backend/tests/test_hybrid_retrieval.py backend/tests/test_learning_answer.py
git commit -m "fix: align answer citations with retrieval audit"
```

### Task 3: Streaming integration, partial persistence, and session isolation

**Files:**
- Modify: `backend/app/api/routes/search.py`
- Modify: `backend/tests/test_chat_streaming.py`
- Modify: `frontend/src/hooks/useStreamingChat.ts`
- Modify: `frontend/src/features/learning/learningConversationState.ts`
- Modify: `frontend/tests/learningConversationState.test.ts`

**Interfaces:**
- Consumes: the current SSE contract (`session`, `evidence`, `token`, `sources`, `suggestions`, `done`, `error`).
- Produces: a tested event ordering contract and `requestId`-isolated frontend reducer updates.

- [ ] **Step 1: Add backend integration tests with fixed fakes**

```python
async def test_two_turn_stream_persists_and_reloads_history(self):
    # Fake both recall paths and the LLM stream.
    # Consume the first response body and assert event order:
    # session -> evidence -> token -> sources -> suggestions -> done.
    # Send a second request with session_id and assert both user/assistant pairs
    # are returned by GET /api/chat/sessions/{id}.

async def test_interrupted_stream_persists_partial_message(self):
    # Yield one token and then raise from the fake model.
    # Assert the error event contains the saved message_id and the database row
    # has generation_status="partial" and the emitted partial content.
```

- [ ] **Step 2: Run integration tests and verify current failures**

Run: `uv run pytest -q backend/tests/test_chat_streaming.py`

Expected: at least one failure around exact event order, partial metadata, or persisted retrieval/citation state.

- [ ] **Step 3: Make the stream finalization path explicit**

Refactor the nested event generator into small helpers so both complete and partial messages save `session_id`, `mode`, `evidence_status`, `retrieval_run_id`, source snapshots, suggestions, and generation status before the terminal SSE event is emitted. Do not keep a database transaction open while waiting for the client to finish reading.

- [ ] **Step 4: Add stale-request reducer coverage**

```typescript
test('切换会话后忽略旧请求的结束事件', () => {
  const current = applyChatEvent(createAssistantDraft(), { token: '新会话' });
  assert.equal(shouldApplyChatEvent(8, 7), false);
  assert.equal(current.content, '新会话');
});
```

Keep the existing `AbortController` and monotonically increasing request ID. The hook must not forward any old event after cancellation or session switching.

- [ ] **Step 5: Run all backend and frontend state tests**

Run: `uv run pytest -q`

Run: `node --experimental-strip-types --test tests/*.test.ts` from `frontend`.

Expected: every backend, Feishu, and frontend test passes.

- [ ] **Step 6: Commit the streaming slice**

```bash
git add backend/app/api/routes/search.py backend/tests/test_chat_streaming.py frontend/src/hooks/useStreamingChat.ts frontend/src/features/learning/learningConversationState.ts frontend/tests/learningConversationState.test.ts
git commit -m "test: cover persistent learning chat streams"
```

### Task 4: Interrupted-answer recovery and action-state feedback

**Files:**
- Modify: `frontend/src/features/learning/types.ts`
- Modify: `frontend/src/features/learning/learningConversationState.ts`
- Create: `frontend/src/hooks/useMessageActions.ts`
- Modify: `frontend/src/components/learning/ChatTranscript.tsx`
- Modify: `frontend/src/components/learning/MessageActions.tsx`
- Modify: `frontend/src/pages/LearningChat.tsx`
- Modify: `frontend/tests/learningConversationState.test.ts`
- Create: `frontend/tests/messageActionState.test.ts`

**Interfaces:**
- Consumes: `DisplayMessage.status`, the preceding user question, and existing card/note/mistake/feedback API calls.
- Produces: `recoveryPromptFor(messages, assistantId, kind)`, per-message action states, and retry/continue controls.

- [ ] **Step 1: Add failing recovery and idempotent-action state tests**

```typescript
test('重答使用中断回答前最近一条用户问题', () => {
  assert.equal(recoveryPromptFor(messages, 'assistant-2', 'retry'), '解释混合检索');
});

test('继续生成给出不重复已有内容的明确请求', () => {
  assert.match(recoveryPromptFor(messages, 'assistant-2', 'continue'), /继续.*不要重复/);
});

test('同一消息同一动作在请求中不可重复提交', () => {
  const key = messageActionKey('message-1', 'card');
  assert.equal(isActionPending(new Set([key]), 'message-1', 'card'), true);
});
```

- [ ] **Step 2: Run frontend tests and verify they fail**

Run: `node --experimental-strip-types --test tests/*.test.ts` from `frontend`.

Expected: failure because the recovery and action-state helpers do not exist.

- [ ] **Step 3: Implement recovery prompts without a new backend endpoint**

```typescript
export const recoveryPromptFor = (
  messages: DisplayMessage[],
  assistantId: string,
  kind: 'continue' | 'retry',
): string => {
  // retry returns the nearest preceding user content;
  // continue asks the same session to continue from the saved partial answer
  // without repeating it, allowing the existing persisted history to supply context.
};
```

Show “继续生成” and “重新回答” only for partial assistant messages, and “重新回答” for failed assistant messages. Reuse `sendQuestion` with the current session so recovery remains part of the same history.

- [ ] **Step 4: Add per-message pending/success/error action state**

`useMessageActions` owns a `Set<string>` of pending `messageId:action` keys. Disable only the action currently being saved, prevent duplicate clicks, and update feedback buttons to show the selected helpful state. Use one notification per request; do not enqueue duplicate failure toasts from both the hook and page.

- [ ] **Step 5: Keep `LearningChat.tsx` as orchestration only**

Pass `onContinue`, `onRetry`, action pending flags, and feedback state into `ChatTranscript`. Keep API execution in `useMessageActions` and recovery-state calculations in `learningConversationState.ts`.

- [ ] **Step 6: Run frontend tests and production build**

Run: `node --experimental-strip-types --test tests/*.test.ts`

Run: `npm run build`

Expected: all frontend tests pass and TypeScript/Vite production build succeeds.

- [ ] **Step 7: Commit the recovery slice**

```bash
git add frontend/src/features/learning/types.ts frontend/src/features/learning/learningConversationState.ts frontend/src/hooks/useMessageActions.ts frontend/src/components/learning/ChatTranscript.tsx frontend/src/components/learning/MessageActions.tsx frontend/src/pages/LearningChat.tsx frontend/tests/learningConversationState.test.ts frontend/tests/messageActionState.test.ts
git commit -m "feat: recover interrupted learning answers"
```

### Task 5: Responsive browser acceptance and delivery verification

**Files:**
- Modify if required by observed defects: `frontend/src/styles/app.css`
- Modify if required by observed defects: `frontend/src/components/learning/MobileLearningControls.tsx`
- Modify if required by observed defects: `frontend/src/components/learning/LearningModePanel.tsx`
- Modify: `README.md`
- Create: `docs/verification/2026-08-24-learning-chat-acceptance.md`

**Interfaces:**
- Consumes: completed chat API and production frontend build.
- Produces: captured acceptance evidence for 1440px, 1024px, and 390px viewports and verified Docker Compose configuration.

- [ ] **Step 1: Start the local application with deterministic test data**

Run: `docker compose config`

Run: `docker compose up -d --build backend frontend redis chromadb`

Seed one workspace, two ready documents, one session with two completed turns, one partial assistant turn, citations, and three suggestions through API fixtures or direct local database setup. No external LLM call is used for the seeded history.

- [ ] **Step 2: Execute the 1440px desktop flow**

Verify three visible columns, session creation/open/rename/favorite/filter/delete, message actions, citation drawer, mode switch, strict switch, and fixed composer. Confirm the evidence source shows filename, page, heading, original excerpt, and retrieval score.

- [ ] **Step 3: Execute the 1024px tablet flow**

Verify the session list is in a left drawer, the chat and learning panel remain usable, the explicit “会话” button is visible, and neither the composer nor the right panel covers message content.

- [ ] **Step 4: Execute the 390px mobile flow**

Verify a single chat column, session drawer, bottom learning-settings panel, horizontally scrollable scope strip, wrapped actions/citations, keyboard-safe fixed composer, and no horizontal document overflow.

- [ ] **Step 5: Correct only defects observed in the browser**

For each defect, add or extend a focused Node source/style contract before modifying CSS or the relevant component. Re-run the affected viewport after every correction and record the final result and screenshot path in the acceptance document.

- [ ] **Step 6: Run complete verification**

Run: `uv run pytest -q`

Run: `node --experimental-strip-types --test tests/*.test.ts` from `frontend`.

Run: `npm run build` from `frontend`.

Run: `docker compose config`

Run: `docker compose build backend frontend feishu-bot worker`

Expected: all tests and builds succeed; browser console has no unexplained errors; all three viewports have no horizontal overflow, vertical body text, hidden composer, or duplicate toasts.

- [ ] **Step 7: Document exact local commands and current test counts**

Update the README testing section with the root backend command and frontend commands. Record container build results, browser viewport results, remaining environment-dependent checks, and screenshot paths in `docs/verification/2026-08-24-learning-chat-acceptance.md`.

- [ ] **Step 8: Commit final acceptance work**

```bash
git add frontend/src/styles/app.css frontend/src/components/learning/MobileLearningControls.tsx frontend/src/components/learning/LearningModePanel.tsx README.md docs/verification/2026-08-24-learning-chat-acceptance.md
git commit -m "docs: verify responsive learning chat"
```

## Self-review

- Spec coverage: lifecycle, migration, hybrid retrieval, deterministic evidence gating, citation audit, learning actions, interrupted generation, responsive layouts, and full verification each map to a task above.
- Existing completed functionality is preserved and exercised rather than rebuilt.
- Interface names are consistent between producing and consuming tasks.
- Every implementation task begins with a failing focused test and ends with full relevant verification.

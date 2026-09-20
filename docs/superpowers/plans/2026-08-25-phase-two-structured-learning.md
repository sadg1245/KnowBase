# Phase Two Structured Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 执行状态：本计划的复选框未回填（TDD 步骤留痕），不代表未执行。
> 实际实现状态见 `docs/2026-09-18-knowbase-project-design.md` §13 与对应阶段测试。

**Goal:** Complete the second-stage document-to-learning pipeline so uploads asynchronously produce structured study content, document sources are precisely browsable, and users can fully manage generated knowledge points.

**Architecture:** Extend the existing SQLAlchemy document and chunk models, keep Celery/Redis as the two-stage parsing and generation pipeline, and read generation input from the durable `document_chunks` table. Add focused FastAPI services and endpoints, then build a document detail page and knowledge-management components on top of typed frontend APIs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Celery 5, Redis, ChromaDB, Pydantic 2, PyMuPDF, python-docx, python-pptx, openpyxl, React 18, TypeScript 5.6, Vite 6, Ant Design 5, Node test runner via `tsx`.

**Spec:** `docs/superpowers/specs/2026-08-25-phase-two-structured-learning-design.md`

## Global Constraints

- Keep the existing FastAPI, SQLAlchemy, Celery, Redis, ChromaDB, and React architecture; do not introduce a new queue, workflow engine, OCR service, or task table.
- Upload requests must never run parsing, embedding, ChromaDB writes, or LLM generation inline.
- Existing API fields and routes remain backward compatible.
- PDF uses physical one-based page numbers; DOCX page numbers remain null; PPT slide numbers and Excel sheet numbers are one-based.
- ChromaDB and `document_chunks` use the stable chunk ID `{document_id}_chunk_{index}`.
- Historic chat sources without `chunk_id` continue to open the evidence drawer.
- New behavior follows strict red-green-refactor: run each target test and observe the expected failure before production edits.
- Do not add frontend runtime or test dependencies; use existing React server rendering, Node assertions, and pure helper tests.

## File Structure

### Backend files to create

- `backend/app/services/learning_content.py`: validated LLM material schema, prompt construction, generation, and transactional document/knowledge-point replacement.
- `backend/app/services/document_jobs.py`: small Celery dispatch boundary shared by upload, reprocess, and regenerate endpoints.
- `backend/tests/test_phase_two_models.py`: schema defaults and migration coverage.
- `backend/tests/test_phase_two_parsers.py`: parser metadata hierarchy coverage.
- `backend/tests/test_learning_content.py`: material validation and idempotent persistence coverage.
- `backend/tests/test_document_jobs.py`: commit-before-dispatch and non-blocking failure coverage.
- `backend/tests/test_document_management.py`: sections, retry, update, detail, recommendations, merge, and quiz coverage.
- `backend/tests/test_source_navigation.py`: source `chunk_id` propagation coverage.

### Frontend files to create

- `frontend/src/pages/DocumentDetail.tsx`: document header, source preview, outline, and structured learning panel.
- `frontend/src/pages/documentDetailState.ts`: pure selection, page-fragment, and outline helpers.
- `frontend/src/components/knowledge/KnowledgeOverview.tsx`: progress, activity, and recommendation presentation.
- `frontend/src/components/knowledge/KnowledgeDocumentList.tsx`: document states, errors, retry, regenerate, and detail navigation.
- `frontend/src/components/knowledge/KnowledgePointManager.tsx`: edit, delete, merge, key/mastery, card, and quiz controls.
- `frontend/src/features/learning/sourceNavigation.ts`: citation linkification and document-detail target construction.
- `frontend/tests/documentDetailState.test.ts`: document location behavior.
- `frontend/tests/sourceNavigation.test.ts`: citation conversion and fallback behavior.
- `frontend/tests/knowledgeBaseDetail.test.tsx`: structured detail rendering coverage.

### Existing files to modify

- Backend models, migrations, schemas, parsers, pipeline, Celery tasks, document and learning routes, hybrid retrieval, and search response serialization.
- Frontend API types/client, application routes, learning transcript/markdown/evidence drawer, knowledge-base page, and shared styles.
- `docker-compose.dev.yml` to point the worker at `app.collector.tasks`.

---

### Task 1: Persist Phase-Two Document and Knowledge Metadata

**Files:**
- Modify: `backend/app/models/document.py`
- Modify: `backend/app/models/chat.py`
- Modify: `backend/app/models/learning.py`
- Modify: `backend/app/core/migrations.py`
- Modify: `backend/app/schemas/schemas.py`
- Modify: `backend/app/schemas/learning.py`
- Create: `backend/tests/test_phase_two_models.py`

**Interfaces:**
- Produces `Document.tags`, structured learning JSON fields, `learning_error_message`, `processed_at`, and `learning_generated_at`.
- Produces `DocumentChunk.heading_level` and `DocumentChunk.section_path`.
- Produces `KnowledgePoint.is_key` and `KnowledgePoint.mastery_status`.
- Produces `DocumentUpdate`, expanded `DocumentResponse`, expanded `DocumentStatusResponse`, `KnowledgePointMerge`, and expanded `KnowledgePointUpdate` schemas.

- [ ] **Step 1: Write failing model and schema tests**

```python
async def test_document_phase_two_defaults(db, workspace):
    row = Document(workspace_id=workspace.id, filename="a.pdf", file_path="a.pdf", file_type=".pdf")
    db.add(row)
    await db.flush()
    await db.refresh(row)
    assert row.learning_status == "not_started"
    assert row.tags == []
    assert row.chapter_summaries == []
    response_fields = DocumentResponse.model_fields
    assert {"tags", "chapter_summaries", "core_concepts", "important_terms",
            "common_mistakes", "prerequisites", "learning_order", "review_points",
            "learning_error_message", "processed_at", "learning_generated_at"} <= set(response_fields)


def test_knowledge_point_update_accepts_phase_two_state():
    payload = KnowledgePointUpdate(is_key=True, mastery_status="mastered")
    assert payload.is_key is True
    assert payload.mastery_status == "mastered"
```

- [ ] **Step 2: Run the model tests and verify RED**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_phase_two_models.py -q`

Expected: collection or assertions fail because the new fields and schemas do not exist.

- [ ] **Step 3: Add model columns and typed schemas**

Use SQLAlchemy `JSON` defaults with `default=list`, nullable false for list fields, nullable timestamps, and these exact knowledge-point defaults:

```python
is_key = Column(Boolean, nullable=False, default=False)
mastery_status = Column(String(20), nullable=False, default="not_started", index=True)
```

Define:

```python
class DocumentUpdate(BaseModel):
    filename: Optional[str] = Field(None, min_length=1, max_length=512)
    tags: Optional[list[str]] = Field(None, max_length=30)


class KnowledgePointMerge(BaseModel):
    target_id: str
    source_ids: list[str] = Field(..., min_length=1, max_length=50)
```

Use `Literal["not_started", "learning", "mastered"]` for mastery status validation.

- [ ] **Step 4: Add idempotent SQLite compatibility columns**

Extend `run_compat_migrations()` additions for `documents`, `document_chunks`, and `knowledge_points`. JSON list fields use `JSON NOT NULL DEFAULT '[]'`; booleans use `BOOLEAN NOT NULL DEFAULT 0`.

- [ ] **Step 5: Run target and existing model tests**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_phase_two_models.py tests/test_chat_architecture.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit the metadata foundation**

```bash
git add backend/app/models/document.py backend/app/models/chat.py backend/app/models/learning.py backend/app/core/migrations.py backend/app/schemas/schemas.py backend/app/schemas/learning.py backend/tests/test_phase_two_models.py
git commit -m "feat: persist structured learning metadata"
```

### Task 2: Preserve Parser Page and Heading Hierarchy

**Files:**
- Modify: `backend/app/collector/parsers/pdf_parser.py`
- Modify: `backend/app/collector/parsers/docx_parser.py`
- Modify: `backend/app/collector/parsers/pptx_parser.py`
- Modify: `backend/app/collector/pipeline.py`
- Modify: `backend/app/services/hybrid_retrieval.py`
- Create: `backend/tests/test_phase_two_parsers.py`

**Interfaces:**
- Consumes `DocumentChunk.heading_level` and `section_path` from Task 1.
- Produces parser metadata keys `page_num`, `heading`, `heading_level`, and `section_path` on every supported structured block.
- Makes `upsert_document_chunks()` persist the added keys.

- [ ] **Step 1: Write failing parser metadata tests**

Create small temporary PDF/DOCX/PPTX/XLSX fixtures in tests. Assert:

```python
assert pdf_chunks[1]["metadata"] == {
    "page_num": 2,
    "heading": "第一章",
    "heading_level": 1,
    "section_path": ["第一章"],
    "source_file": "book.pdf",
}
assert docx_chunks[1]["metadata"]["page_num"] is None
assert docx_chunks[1]["metadata"]["section_path"] == ["第一章", "1.1 小节"]
assert pptx_chunks[0]["metadata"]["page_num"] == 1
assert xlsx_chunks[0]["metadata"]["section_path"] == ["Sheet1"]
```

- [ ] **Step 2: Run parser tests and verify RED**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_phase_two_parsers.py -q`

Expected: missing hierarchy fields and DOCX fake page number assertions fail.

- [ ] **Step 3: Implement PDF TOC inheritance**

Build sorted TOC entries `(page_num, level, title)`, maintain a heading stack while iterating physical pages, and attach the most recent path. A page before the first TOC entry gets empty heading, null level, and an empty path.

- [ ] **Step 4: Implement DOCX heading stack**

Replace `section_counter` metadata with a stack keyed by Heading 1–9. On a heading level `n`, truncate the stack to `n - 1`, append the heading, and flush blocks with `page_num=None`.

- [ ] **Step 5: Add PPT and Excel structure metadata**

PPT titles use `heading_level=1` and `[title]` when non-empty. Excel sheets use `heading_level=1` and `[sheet_name]`. Ensure the Excel header row is included in rendered content even when the sheet has no data rows.

- [ ] **Step 6: Persist and vectorize hierarchy metadata**

Copy `heading_level` and JSON-safe `section_path` into Chroma metadata and `DocumentChunk`. Chroma metadata stores `section_path` as a JSON string because list values are not accepted by all Chroma versions; database rows store a JSON list.

- [ ] **Step 7: Run parser, content-filter, and retrieval tests**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_phase_two_parsers.py tests/test_content_filter.py tests/test_hybrid_retrieval.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit parser structure**

```bash
git add backend/app/collector/parsers/pdf_parser.py backend/app/collector/parsers/docx_parser.py backend/app/collector/parsers/pptx_parser.py backend/app/collector/pipeline.py backend/app/services/hybrid_retrieval.py backend/tests/test_phase_two_parsers.py
git commit -m "feat: preserve document section hierarchy"
```

### Task 3: Extract and Validate Structured Learning Generation

**Files:**
- Create: `backend/app/services/learning_content.py`
- Modify: `backend/app/api/routes/learning.py`
- Create: `backend/tests/test_learning_content.py`

**Interfaces:**
- Consumes `Document`, `DocumentChunk`, `KnowledgePoint`, `Settings`, and `AsyncSession`.
- Produces `LearningMaterial`, `build_learning_material(chunks, settings, completion=None)`, `replace_document_learning_content(db, document, material)`, and `generate_document_learning_content(db, document_id, settings)`.
- Existing manual analyze route calls the new service for backward compatibility until Task 4 changes its dispatch behavior.

- [ ] **Step 1: Write failing validation and replacement tests**

```python
def test_learning_material_clamps_point_values():
    material = LearningMaterial.model_validate({
        "summary": "摘要",
        "chapter_summaries": [], "core_concepts": [], "important_terms": [],
        "common_mistakes": [], "prerequisites": [], "learning_order": [],
        "review_points": [],
        "knowledge_points": [{
            "title": "概念", "summary": "简述", "explanation": "解释",
            "importance": 9, "difficulty": 0, "tags": ["基础"],
            "source_chunk_index": 0,
        }],
    })
    assert material.knowledge_points[0].importance == 5
    assert material.knowledge_points[0].difficulty == 1


async def test_replace_learning_content_is_idempotent(db, ready_document, chunks):
    await replace_document_learning_content(db, ready_document, material)
    await replace_document_learning_content(db, ready_document, material)
    rows = (await db.execute(select(KnowledgePoint).where(
        KnowledgePoint.document_id == ready_document.id))).scalars().all()
    assert len(rows) == 1
    assert ready_document.learning_status == "ready"
```

- [ ] **Step 2: Run learning-content tests and verify RED**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_learning_content.py -q`

Expected: import fails because `learning_content.py` does not exist.

- [ ] **Step 3: Define strict Pydantic material schemas**

Use bounded list lengths, bounded strings, field validators that clamp importance/difficulty to 1–5, and a `source_chunk_index` used to resolve page and heading from durable chunks. Ignore unknown model fields.

- [ ] **Step 4: Implement LLM generation**

Move provider selection and LiteLLM invocation out of `learning.py`. The prompt requests all nine top-level fields and treats document content as untrusted data. Parse the first JSON object, raise `LearningGenerationError` for missing configuration, timeouts, invalid JSON, or an empty knowledge-point list.

- [ ] **Step 5: Implement transactional replacement**

Delete existing points for only the target document, map `source_chunk_index` to `DocumentChunk.page_num` and `heading`, insert validated points, update all document material fields, set `learning_status="ready"`, clear the learning error, and set `learning_generated_at` to UTC now.

- [ ] **Step 6: Replace route-local generation code**

Remove `_ai_learning_material` and heuristic generation from `learning.py`. Keep `POST /learning/workspaces/{id}/analyze` backward compatible by invoking `generate_document_learning_content()` for each selected ready document and returning the refreshed detail.

- [ ] **Step 7: Run learning and route regression tests**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_learning_content.py tests/test_regressions.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit learning generation service**

```bash
git add backend/app/services/learning_content.py backend/app/api/routes/learning.py backend/tests/test_learning_content.py
git commit -m "feat: generate validated structured learning content"
```

### Task 4: Make Upload and Generation Reliably Asynchronous

**Files:**
- Create: `backend/app/services/document_jobs.py`
- Modify: `backend/app/api/routes/documents.py`
- Modify: `backend/app/collector/pipeline.py`
- Modify: `backend/app/collector/tasks.py`
- Modify: `docker-compose.dev.yml`
- Create: `backend/tests/test_document_jobs.py`

**Interfaces:**
- Consumes `generate_document_learning_content()` from Task 3.
- Produces `enqueue_document_processing(document)` and `enqueue_learning_generation(document_id)` dispatch functions.
- Produces Celery task `collector.generate_learning_content`.

- [ ] **Step 1: Write failing dispatch-order and fallback tests**

Use an async test session and a dispatcher spy that opens a second session. Assert the document is visible with `status="processing"` when dispatch begins. Add a broker-failure test that patches `_process_document` to raise if called and asserts upload records `failed` without calling it.

- [ ] **Step 2: Run document-job tests and verify RED**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_document_jobs.py -q`

Expected: the visibility assertion fails or inline `_process_document` is called.

- [ ] **Step 3: Add the dispatch boundary**

Implement the exact signatures:

```python
def enqueue_document_processing(document: Document) -> None:
    process_document_task.delay(
        document_id=document.id, file_path=document.file_path,
        file_type=document.file_type, workspace_id=document.workspace_id,
    )


def enqueue_learning_generation(document_id: str) -> None:
    generate_learning_content_task.delay(document_id=document_id)
```

Imports of Celery task objects stay inside the functions to avoid circular imports.

- [ ] **Step 4: Commit before upload dispatch and remove inline fallback**

Set `document.status="processing"`, flush, and `await db.commit()` before calling the dispatcher. On dispatch exception, set `failed`, store a concise queue error, commit, and return the document response. Remove `_process_document()` from the upload path; keep the helper only if existing tests or explicit internal callers still require it.

- [ ] **Step 5: Chain parsing to generation**

After `pipeline.process_document()` returns `status="ready"`, update the document to `learning_status="queued"` and commit before dispatching generation. If dispatch fails, leave parsing `ready` but set learning `failed` and `learning_error_message`.

- [ ] **Step 6: Add the generation Celery task**

The task opens an async session, sets `generating`, calls `generate_document_learning_content`, commits, and retries transient exceptions up to three times. On terminal failure it sets `learning_status="failed"` and stores the exception string.

- [ ] **Step 7: Correct and validate the development worker entrypoint**

Change the worker command to:

```yaml
command: celery -A app.collector.tasks worker --loglevel=debug --concurrency=2 --pool=solo
```

Verify the merged deployment configuration and the real Celery module import rather than testing configuration text:

Run from repository root: `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet`

Run from `backend`: `uv run python -c "from app.collector.tasks import celery_app; assert celery_app is not None"`

Expected: Compose validation and Celery application import both exit zero.

- [ ] **Step 8: Run async pipeline regressions**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_document_jobs.py tests/test_content_filter.py tests/test_regressions.py -q`

Expected: all selected tests pass and no test invokes inline parsing during upload.

- [ ] **Step 9: Commit the asynchronous task chain**

```bash
git add backend/app/services/document_jobs.py backend/app/api/routes/documents.py backend/app/collector/pipeline.py backend/app/collector/tasks.py backend/tests/test_document_jobs.py docker-compose.dev.yml
git commit -m "fix: make document learning pipeline asynchronous"
```

### Task 5: Add Document Detail, Sections, Update, and Retry APIs

**Files:**
- Modify: `backend/app/api/routes/documents.py`
- Modify: `backend/app/schemas/schemas.py`
- Create: `backend/tests/test_document_management.py`

**Interfaces:**
- Consumes dispatch functions from Task 4 and chunk fields from Tasks 1–2.
- Produces `PATCH /documents/{id}`, `GET /documents/{id}/sections`, `GET /documents/{id}/sections/{chunk_id}`, `POST /documents/{id}/reprocess`, and `POST /documents/{id}/regenerate-learning`.
- Produces Pydantic response types `DocumentSectionItem`, `DocumentSectionsResponse`, and `DocumentSectionDetail` in `schemas.py`.

- [ ] **Step 1: Write failing document-management tests**

Cover filename/tag update, ordered sections, one section with neighbor IDs, `409` while a phase runs, `400` regenerate before parsing is ready, successful `202` dispatch, and expanded status errors.

```python
assert section_payload["items"][0]["chunk_id"] == f"{document.id}_chunk_0"
assert section_payload["items"][0]["section_path"] == ["第一章"]
assert detail["previous_chunk_id"] is None
assert detail["next_chunk_id"] == f"{document.id}_chunk_1"
```

- [ ] **Step 2: Run document-management tests and verify RED**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_document_management.py -q`

Expected: endpoints/helpers are absent and assertions fail.

- [ ] **Step 3: Add response helpers and section queries**

Return chunks ordered by `chunk_index`. The list response contains `outline` de-duplicated by `(section_path, heading, page_num)` and `items` with source content. The detail endpoint verifies the chunk belongs to the requested document before computing neighbors.

- [ ] **Step 4: Add document update**

Normalize tags by trimming, dropping empties, and preserving first occurrence order. Update `updated_at` and return `DocumentResponse`.

- [ ] **Step 5: Add retry endpoints**

`reprocess` rejects `pending/processing`, sets parsing `processing`, clears both errors, sets learning `not_started`, commits, and dispatches parsing. The parsing worker sets learning `queued` only after the new chunks are ready. `regenerate-learning` requires parsing `ready`, rejects `queued/generating`, sets learning `queued`, commits, and dispatches generation. If dispatch fails, persist the corresponding failed state and return `503` with the recorded reason.

- [ ] **Step 6: Expand status response**

Return `learning_status`, `learning_error_message`, `processed_at`, and `learning_generated_at` alongside existing parsing fields.

- [ ] **Step 7: Run target and document regression tests**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_document_management.py tests/test_regressions.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit document-management APIs**

```bash
git add backend/app/api/routes/documents.py backend/app/schemas/schemas.py backend/tests/test_document_management.py
git commit -m "feat: add document detail and retry APIs"
```

### Task 6: Complete Knowledge-Base Detail and Knowledge-Point Management

**Files:**
- Modify: `backend/app/api/routes/learning.py`
- Modify: `backend/app/schemas/learning.py`
- Extend: `backend/tests/test_document_management.py`

**Interfaces:**
- Consumes expanded document and point models from Task 1.
- Produces detail keys `recent_activities`, `recommendations`, document structured fields, and document outlines.
- Produces `POST /learning/knowledge-points/merge` and `POST /learning/knowledge-points/{id}/quiz`.

- [ ] **Step 1: Add failing detail and knowledge-point tests**

Test workspace-filtered recent activity, deterministic recommendation priority, knowledge-point response fields, mastery synchronization, same-workspace merge, cross-workspace rejection, and single-point quiz creation.

```python
assert detail["recommendations"][0]["type"] == "retry_document"
assert updated["mastery_status"] == "mastered"
assert updated["mastery"] == 1.0
assert set(merged["tags"]) == {"A", "B"}
assert quiz.knowledge_point_id == target.id
```

- [ ] **Step 2: Run the tests and verify RED**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_document_management.py -q`

Expected: missing detail keys and endpoints fail.

- [ ] **Step 3: Expand workspace detail serialization**

Query activities by workspace, query chunk headings in one statement, group outlines by document ID, and include all document learning fields. Build at most five recommendations with this priority: parsing failure, learning failure, ready/not-started, important unmastered point, continue chat.

- [ ] **Step 4: Synchronize mastery updates**

When update payload sets `mastery_status="mastered"`, set `mastery=1.0`. When numeric mastery reaches `1.0`, set status to `mastered`; positive values below 1 set status to `learning` unless the payload explicitly supplied a status.

- [ ] **Step 5: Implement merge**

Load target and all source IDs, reject missing rows and cross-workspace rows, merge unique tags, join non-duplicate summaries/explanations with blank lines, keep maximum importance/difficulty/mastery, propagate `is_key`, delete sources, flush, and return the target.

- [ ] **Step 6: Implement single-point quiz**

Create one deterministic short-answer `QuizQuestion` from point title/explanation, set `knowledge_point_id`, `workspace_id`, explanation, and source label, then return `_quiz(row)` without revealing the answer.

- [ ] **Step 7: Run learning-route regressions**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_document_management.py tests/test_learning_answer.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit complete learning management**

```bash
git add backend/app/api/routes/learning.py backend/app/schemas/learning.py backend/tests/test_document_management.py
git commit -m "feat: complete knowledge point management"
```

### Task 7: Propagate Stable Chunk IDs Through Answer Sources

**Files:**
- Modify: `backend/app/schemas/schemas.py`
- Modify: `backend/app/core/rag_engine.py`
- Modify: `backend/app/services/hybrid_retrieval.py`
- Modify: `backend/app/api/routes/search.py`
- Create: `backend/tests/test_source_navigation.py`

**Interfaces:**
- Consumes `RetrievalCandidate.chunk_id` already produced by hybrid retrieval.
- Produces optional `chunk_id` on `SourceItem`, `SearchResult`, streaming `sources` events, stored conversation sources, and non-streaming responses.
- Produces `serialize_source(candidate: RetrievalCandidate) -> dict[str, object]` as the single serializer used by ordinary and streaming search responses.

- [ ] **Step 1: Write failing source serialization tests**

```python
candidate = RetrievalCandidate(
    chunk_id="doc_chunk_3", document_id="doc", source_file="book.pdf",
    page_num=8, heading="第三章", content="证据",
)
source = serialize_source(candidate)
assert source["chunk_id"] == "doc_chunk_3"
assert source["document_id"] == "doc"
```

Exercise both stream and ordinary response helpers so history persistence contains the same value.

- [ ] **Step 2: Run source tests and verify RED**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_source_navigation.py -q`

Expected: schema or serializer omits `chunk_id`.

- [ ] **Step 3: Add optional source schema fields**

Add `chunk_id: Optional[str] = None` to `SourceItem` and `SearchResult`. Preserve optional behavior for historic rows.

- [ ] **Step 4: Serialize the stable ID everywhere**

When source data comes from retrieval candidates use `candidate.chunk_id`; when it comes from legacy metadata use `metadata.get("chunk_id") or metadata.get("id")`. Include the value in saved conversation `sources` JSON.

- [ ] **Step 5: Run chat and retrieval regression tests**

Run from `backend`: `uv run --with pytest python -m pytest tests/test_source_navigation.py tests/test_hybrid_retrieval.py tests/test_conversation_service.py tests/test_learning_answer.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit source navigation metadata**

```bash
git add backend/app/schemas/schemas.py backend/app/core/rag_engine.py backend/app/services/hybrid_retrieval.py backend/app/api/routes/search.py backend/tests/test_source_navigation.py
git commit -m "feat: expose stable source chunk ids"
```

### Task 8: Add Typed Frontend APIs and Pure Document Navigation State

**Files:**
- Modify: `frontend/src/services/api.ts`
- Create: `frontend/src/pages/documentDetailState.ts`
- Create: `frontend/tests/documentDetailState.test.ts`

**Interfaces:**
- Consumes backend response fields from Tasks 1, 5, 6, and 7.
- Produces `DocumentSection`, expanded `Document`, expanded `KnowledgePoint`, expanded `KnowledgeBaseDetail`, and API functions for update/retry/sections/merge/quiz.
- Produces `resolveSelectedChunk(items, requestedChunk, requestedPage)`, `pdfPageFragment(page)`, and `buildOutline(items)`.

- [ ] **Step 1: Write failing document-detail state tests**

```typescript
test('优先按 chunk 查询参数定位原文', () => {
  assert.equal(resolveSelectedChunk(items, 'doc_chunk_2', 1)?.chunk_id, 'doc_chunk_2');
});

test('没有 chunk 时按页码选择首个切片', () => {
  assert.equal(resolveSelectedChunk(items, undefined, 8)?.page_num, 8);
  assert.equal(pdfPageFragment(8), '#page=8');
});
```

- [ ] **Step 2: Run the state tests and verify RED**

Run from `frontend`: `npx tsx --test tests/documentDetailState.test.ts`

Expected: import fails because `documentDetailState.ts` does not exist.

- [ ] **Step 3: Expand frontend types**

Mirror backend field names exactly. Add `chunk_id?: string | null` to both backend and normalized source types. Define typed recommendations and recent activities instead of `any`.

- [ ] **Step 4: Add API functions**

Implement `getDocument`, `updateDocument`, `getDocumentSections`, `getDocumentSection`, `reprocessDocument`, `regenerateDocumentLearning`, `mergeKnowledgePoints`, and `knowledgePointToQuiz` with existing Axios instance semantics.

- [ ] **Step 5: Implement pure selection helpers**

Chunk ID takes priority, then page number, then first item. `pdfPageFragment` returns an empty string for null/non-positive values. `buildOutline` removes duplicate path/heading/page combinations without sorting away source order.

- [ ] **Step 6: Run state tests and TypeScript compilation**

Run from `frontend`: `npx tsx --test tests/documentDetailState.test.ts && npx tsc --noEmit`

Expected: tests and type checking pass.

- [ ] **Step 7: Commit frontend API foundation**

```bash
git add frontend/src/services/api.ts frontend/src/pages/documentDetailState.ts frontend/tests/documentDetailState.test.ts
git commit -m "feat: add document detail client APIs"
```

### Task 9: Build the Document Detail Page

**Files:**
- Create: `frontend/src/pages/DocumentDetail.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles/app.css`
- Create: `frontend/tests/knowledgeBaseDetail.test.tsx`

**Interfaces:**
- Consumes Task 8 APIs/helpers.
- Produces route `/knowledge/:workspaceId/documents/:documentId` and a page with source selection, PDF page location, parsed-text fallback, learning panels, metadata editing, and retry actions.

- [ ] **Step 1: Write a failing static-render test**

Export focused presentational helpers/components from `DocumentDetail.tsx` and render them with `react-dom/server`:

```typescript
const html = renderToStaticMarkup(<StructuredLearningPanel document={documentFixture} />);
assert.match(html, /章节摘要/);
assert.match(html, /重要术语/);
assert.match(html, /易错点/);
assert.match(html, /前置知识/);
```

- [ ] **Step 2: Run the render test and verify RED**

Run from `frontend`: `npx tsx --test tests/knowledgeBaseDetail.test.tsx`

Expected: import fails because `DocumentDetail.tsx` does not exist.

- [ ] **Step 3: Implement page loading and polling**

Load document and sections in parallel with `Promise.all`. Use one interval only while parsing is `pending/processing` or learning is `queued/generating`; clear it on unmount. Derive the selected item during render from query parameters and loaded items.

- [ ] **Step 4: Implement source preview**

For PDF, use authenticated blob URL plus `pdfPageFragment`. Revoke old blob URLs on cleanup. For all other formats render ordered section cards with stable element IDs `source-${chunk_id}` and scroll the selected card into view.

- [ ] **Step 5: Implement metadata and retry controls**

Use an Ant Design modal/form for filename and tags. Show separate parsing and learning tags, exact error text, reprocess and regenerate buttons, and `409/503` messages returned by the backend.

- [ ] **Step 6: Implement structured learning panel and responsive layout**

Render every structured field with empty-state copy. Desktop uses outline/source/learning columns; at the existing mobile breakpoint, outline and learning panels move to drawers. Add `content-visibility: auto` to long source cards.

- [ ] **Step 7: Register the lazy route and run checks**

Run from `frontend`: `npx tsx --test tests/knowledgeBaseDetail.test.tsx tests/documentDetailState.test.ts && npm run build`

Expected: tests and production build pass.

- [ ] **Step 8: Commit document detail UI**

```bash
git add frontend/src/pages/DocumentDetail.tsx frontend/src/App.tsx frontend/src/styles/app.css frontend/tests/knowledgeBaseDetail.test.tsx
git commit -m "feat: add structured document detail page"
```

### Task 10: Complete the Knowledge-Base Detail Experience

**Files:**
- Create: `frontend/src/components/knowledge/KnowledgeOverview.tsx`
- Create: `frontend/src/components/knowledge/KnowledgeDocumentList.tsx`
- Create: `frontend/src/components/knowledge/KnowledgePointManager.tsx`
- Modify: `frontend/src/pages/KnowledgeBase.tsx`
- Extend: `frontend/tests/knowledgeBaseDetail.test.tsx`

**Interfaces:**
- Consumes Task 8 APIs and Task 6 detail payload.
- Produces complete overview, document operations, and knowledge-point management while `KnowledgeBase.tsx` owns loading, polling, and refresh orchestration.

- [ ] **Step 1: Add failing component render tests**

Render fixtures and assert recent activity, recommendation actions, both document statuses, failure reason, key/mastered state, edit/delete/merge/card/quiz labels, and chapters appear.

- [ ] **Step 2: Run component tests and verify RED**

Run from `frontend`: `npx tsx --test tests/knowledgeBaseDetail.test.tsx`

Expected: new components do not exist or expected controls are absent.

- [ ] **Step 3: Implement `KnowledgeOverview`**

Render goal, progress, document learning route, deduplicated chapter outline, recent activities, and typed recommendation buttons. Recommendation paths navigate to retry, document detail, point expansion, or learning chat as appropriate.

- [ ] **Step 4: Implement `KnowledgeDocumentList`**

Render parsing and learning tags separately, error alerts, tags, summary, detail navigation, reprocess, regenerate, and deletion. Keep operations callback-driven so the parent owns network state and refreshes once.

- [ ] **Step 5: Implement `KnowledgePointManager`**

Use a selected-ID set for merge. Provide edit modal fields for title, summary, explanation, importance, difficulty, and tags; buttons for delete, key, mastery, card, and quiz. Merge requires two or more selected points and uses the first selected point as target after a confirmation modal.

- [ ] **Step 6: Refactor `KnowledgeBase.tsx` into orchestration**

Keep `load()` stable with `useCallback`, use one polling interval for active document phases, and pass callbacks to focused components. Remove synchronous `analyzeKnowledgeBase` usage from normal UI; regeneration uses the async document endpoint.

- [ ] **Step 7: Run detail tests and production build**

Run from `frontend`: `npx tsx --test tests/knowledgeBaseDetail.test.tsx && npm run build`

Expected: tests and build pass.

- [ ] **Step 8: Commit knowledge-base management UI**

```bash
git add frontend/src/components/knowledge/KnowledgeOverview.tsx frontend/src/components/knowledge/KnowledgeDocumentList.tsx frontend/src/components/knowledge/KnowledgePointManager.tsx frontend/src/pages/KnowledgeBase.tsx frontend/tests/knowledgeBaseDetail.test.tsx
git commit -m "feat: complete knowledge base learning management"
```

### Task 11: Make Answer Citations Open Exact Source Locations

**Files:**
- Create: `frontend/src/features/learning/sourceNavigation.ts`
- Modify: `frontend/src/components/learning/LearningMessageContent.tsx`
- Modify: `frontend/src/components/learning/ChatTranscript.tsx`
- Modify: `frontend/src/components/learning/EvidenceDrawer.tsx`
- Modify: `frontend/src/pages/LearningChat.tsx`
- Modify: `frontend/src/services/api.ts`
- Create: `frontend/tests/sourceNavigation.test.ts`
- Modify: `frontend/tests/learningMessageContent.test.tsx`

**Interfaces:**
- Consumes optional source `document_id`, `chunk_id`, `page_number`, and current workspace ID.
- Produces `linkifySourceCitations(markdown, sourceCount)`, `sourceDetailTarget(workspaceId, source)`, and shared `openSource` behavior.

- [ ] **Step 1: Write failing citation transformation tests**

```typescript
test('转换正文引用但保留代码中的引用文本', () => {
  const input = '结论[资料1]\n\n`示例[资料1]`\n\n```txt\n[资料1]\n```';
  const output = linkifySourceCitations(input, 1);
  assert.match(output, /knowbase-source:\/\/1/);
  assert.match(output, /`示例\[资料1\]`/);
  assert.match(output, /```txt\n\[资料1\]\n```/);
});

test('来源地址携带精确切片与页码', () => {
  assert.equal(sourceDetailTarget('ws', source),
    '/knowledge/ws/documents/doc?chunk=doc_chunk_3&page=8');
});
```

- [ ] **Step 2: Run source-navigation tests and verify RED**

Run from `frontend`: `npx tsx --test tests/sourceNavigation.test.ts tests/learningMessageContent.test.tsx`

Expected: helper import fails and message content has no citation handler.

- [ ] **Step 3: Implement citation-safe markdown transformation**

Scan fenced code blocks and inline code spans as protected ranges; replace only unprotected `[资料N]` where `1 <= N <= sourceCount` with `[资料N](knowbase-source://N)`.

- [ ] **Step 4: Handle internal links in `LearningMessageContent`**

Add `sources` and `onSource` props. Supply a ReactMarkdown `a` component that intercepts `knowbase-source://N`, prevents ordinary navigation, and invokes the corresponding source. Render ordinary links unchanged with safe attributes.

- [ ] **Step 5: Centralize source opening in `LearningChat`**

If current workspace, document ID, and chunk ID exist, navigate to `sourceDetailTarget`; otherwise set the evidence drawer source. Pass the same handler to inline citations, source buttons, and a new “查看原文” button in the drawer.

- [ ] **Step 6: Run learning frontend regressions and build**

Run from `frontend`: `npx tsx --test tests/sourceNavigation.test.ts tests/learningMessageContent.test.tsx tests/learningConversationState.test.ts && npm run build`

Expected: tests and production build pass.

- [ ] **Step 7: Commit exact citation navigation**

```bash
git add frontend/src/features/learning/sourceNavigation.ts frontend/src/components/learning/LearningMessageContent.tsx frontend/src/components/learning/ChatTranscript.tsx frontend/src/components/learning/EvidenceDrawer.tsx frontend/src/pages/LearningChat.tsx frontend/src/services/api.ts frontend/tests/sourceNavigation.test.ts frontend/tests/learningMessageContent.test.tsx
git commit -m "feat: navigate answer citations to original sources"
```

### Task 12: Run Full Verification and Close Acceptance Gaps

**Files:**
- Update: `README.md` with the automatic pipeline, status meanings, retry flow, and document detail route.

**Interfaces:**
- Consumes all previous task outputs.
- Produces a fully verified repository and operator-facing behavior documentation.

- [ ] **Step 1: Run the complete backend suite**

Run from `backend`: `uv run --with pytest python -m pytest tests -q`

Expected: all backend tests pass with zero collection errors and zero failures.

If a command in this task fails, stop this verification task, add one focused failing regression test for that exact behavior, run it to confirm RED, make the smallest production change, run the focused test to GREEN, and commit those exact test and production paths before resuming Step 1.

- [ ] **Step 2: Run the complete frontend suite**

Run from `frontend`: `npx tsx --test tests/*.test.ts tests/*.test.tsx`

Expected: all frontend tests pass with zero failures.

- [ ] **Step 3: Run compile and production build checks**

Run from repository root: `uv run python -m compileall -q backend/app`

Run from `frontend`: `npm run build`

Expected: both commands exit zero.

- [ ] **Step 4: Exercise the API state machine with fakes**

Run the focused integration tests with verbose output from `backend`:

`uv run --with pytest python -m pytest tests/test_document_jobs.py tests/test_learning_content.py tests/test_document_management.py tests/test_source_navigation.py -v`

Expected: upload visibility, non-blocking queue failure, parse-to-generation chaining, generation replacement, retry states, and source location assertions all pass.

- [ ] **Step 5: Update README behavior documentation**

Document the `status` and `learning_status` state tables, automatic parse-to-generation chain, Redis/Celery requirement, failure retry buttons, and exact-source document route. Do not claim OCR support.

- [ ] **Step 6: Review the acceptance matrix against fresh evidence**

Confirm each row in the design spec maps to a passing focused test or production build result. Record any external-service limitation explicitly: live LLM, Redis, and ChromaDB are integration dependencies, while automated tests use controlled fakes.

- [ ] **Step 7: Commit final verification documentation and fixes**

```bash
git add README.md
git commit -m "docs: document phase two learning workflow"
```

- [ ] **Step 8: Inspect final repository state**

Run: `git status --short --branch`

Expected: no tracked modifications remain; pre-existing untracked user files, if any, are reported without being staged or altered.

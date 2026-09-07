import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  buildQuizSetGenerateRequest,
  PracticeBuilder,
} from '../src/components/practice/PracticeBuilder';
import {
  answerIsPresent,
  QuestionInput,
} from '../src/components/practice/QuestionInput';
import {
  paperSubmissionWarning,
  QuizRunner,
  shouldAutoSubmitPaper,
} from '../src/components/practice/QuizRunner';
import {
  assessmentSourceHref,
  QuizResults,
} from '../src/components/practice/QuizResults';
import { LegacyPracticeView } from '../src/pages/Practice';


const workspace = {
  id: 'workspace-1', name: '几何知识库', description: '', document_count: 2,
  created_at: '2026-09-01T00:00:00Z',
};
const readyDocument = {
  id: 'document-1', workspace_id: workspace.id, filename: 'geometry.pdf', file_type: 'pdf',
  file_size: 10, chunk_count: 2, status: 'ready' as const, learning_status: 'ready' as const,
  tags: [], chapter_summaries: [], core_concepts: [], important_terms: [], common_mistakes: [],
  prerequisites: [], learning_order: [], review_points: [], created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
};
const pendingDocument = { ...readyDocument, id: 'document-2', filename: 'draft.pdf', status: 'processing' as const };
const knowledgePoint = {
  id: 'point-1', workspace_id: workspace.id, document_id: readyDocument.id, title: '勾股定理',
  summary: '', explanation: '', source_page: 3, source_heading: '定理', importance: 4,
  difficulty: 2, mastery: 0, tags: [], is_key: true, mastery_status: 'not_started' as const,
  created_at: '2026-09-01T00:00:00Z',
};

const question = {
  id: 'question-1', quiz_set_id: 'set-1', workspace_id: workspace.id,
  document_id: readyDocument.id, knowledge_point_id: knowledgePoint.id,
  question_type: 'single_choice' as const, prompt: '直角三角形的关系是？',
  options: ['a²+b²=c²', 'a+b=c'], difficulty: 'medium' as const, position: 1,
  source_snapshot: [{ document_id: readyDocument.id, source_file: 'geometry.pdf', chunk_id: 'chunk-7', page: 3 }],
  strict_sources: true, generation_model: null,
};

const makeRun = (overrides: Record<string, unknown> = {}) => ({
  id: 'run-1', quiz_set_id: 'set-1', round_number: 1, answer_mode: 'full_paper' as const,
  question_ids: null, status: 'in_progress' as const, started_at: '2026-09-01T00:00:00Z',
  submitted_at: null, elapsed_seconds: 75, score: 0, max_score: 0, correct_count: 0,
  graded_count: 0, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
  attempts: [],
  quiz_set: {
    id: 'set-1', workspace_id: workspace.id, title: '几何自测', document_ids: [readyDocument.id],
    knowledge_point_ids: [knowledgePoint.id], section_filters: [], question_count: 1,
    difficulty: 'medium' as const, question_types: ['single_choice' as const], strict_sources: true,
    answer_mode: 'full_paper' as const, duration_limit_seconds: 600, status: 'ready' as const,
    generation_model: null, generation_error: null, created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z', questions: [question], latest_run: null,
  },
  ...overrides,
});


test('builder exposes every phase five configuration control and legacy history access', () => {
  const html = renderToStaticMarkup(<PracticeBuilder
    workspaces={[workspace]}
    documents={[readyDocument, pendingDocument]}
    knowledgePoints={[knowledgePoint]}
    workspaceId={workspace.id}
    selectedDocumentIds={[]}
    selectedKnowledgePointIds={[]}
    onWorkspaceChange={() => undefined}
    onDocumentChange={() => undefined}
    onKnowledgePointChange={() => undefined}
    onGenerate={() => undefined}
  />);

  for (const label of ['知识库', '章节或知识点', '题目数量', '难度', '单项选择题', '多项选择题', '判断题', '填空题', '简答题', '解释概念题', '严格依据资料', '逐题答题', '整卷答题', '限时', '历史错题']) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /href="\/practice\?wrong=1"/);
});

test('builder emits ready documents instead of the empty all-documents sentinel', () => {
  assert.deepEqual(buildQuizSetGenerateRequest({
    workspaceId: workspace.id,
    documents: [readyDocument, pendingDocument],
    selectedDocumentIds: [],
    selectedKnowledgePointIds: [knowledgePoint.id],
    count: 12,
    difficulty: 'hard',
    questionTypes: ['multiple_choice', 'fill_blank'],
    strictSources: true,
    answerMode: 'full_paper',
    durationMinutes: 25,
  }), {
    workspace_id: workspace.id,
    document_ids: [readyDocument.id],
    knowledge_point_ids: [knowledgePoint.id],
    section_filters: [],
    count: 12,
    difficulty: 'hard',
    question_types: ['multiple_choice', 'fill_blank'],
    strict_sources: true,
    answer_mode: 'full_paper',
    duration_limit_seconds: 1500,
  });
});

test('question input renders the appropriate control for all six question types', () => {
  const cases = [
    ['single_choice', ['type="radio"']],
    ['multiple_choice', ['type="checkbox"']],
    ['true_false', ['正确', '错误']],
    ['fill_blank', ['practice-fill-blank']],
    ['short_answer', ['textarea']],
    ['concept_explanation', ['textarea']],
  ] as const;

  for (const [questionType, expected] of cases) {
    const html = renderToStaticMarkup(<QuestionInput
      question={{ ...question, question_type: questionType, options: questionType === 'true_false' ? null : question.options }}
      value={questionType === 'multiple_choice' ? [] : ''}
      onChange={() => undefined}
    />);
    for (const marker of expected) assert.match(html, new RegExp(marker));
  }
});

test('answer guards accept multiple selections and reject empty text or arrays', () => {
  assert.equal(answerIsPresent('  '), false);
  assert.equal(answerIsPresent([]), false);
  assert.equal(answerIsPresent('解释'), true);
  assert.equal(answerIsPresent(['A', 'C']), true);
  assert.match(paperSubmissionWarning(['question-2', 'question-3']) ?? '', /2 道题未作答/);
  assert.equal(paperSubmissionWarning([]), null);
});

test('only an expired active full paper auto-submits at the deadline', () => {
  assert.equal(shouldAutoSubmitPaper(makeRun(), 0), true);
  assert.equal(shouldAutoSubmitPaper(makeRun({ answer_mode: 'sequential' }), 0), false);
  assert.equal(shouldAutoSubmitPaper(makeRun({ status: 'submitted' }), 0), false);
  assert.equal(shouldAutoSubmitPaper(makeRun(), 1), false);
});

test('runner conceals protected material until the run is submitted', () => {
  const protectedQuestion = {
    ...question,
    answer: 'a²+b²=c²',
    explanation: '平方关系',
    source_snapshot: [{ ...question.source_snapshot[0], excerpt: '勾股定理原文' }],
  };
  const run = makeRun({ quiz_set: { ...makeRun().quiz_set, questions: [protectedQuestion] } });
  const html = renderToStaticMarkup(<QuizRunner
    session={{
      run,
      questions: [protectedQuestion],
      answers: {},
      attemptsByQuestionId: {},
      revealedQuestionIds: new Set(),
      createdAt: Date.parse('2026-09-01T00:00:00Z'),
    }}
    onAnswer={() => undefined}
    onSubmitQuestion={() => undefined}
    onSubmitPaper={() => undefined}
    onRetry={() => undefined}
    onRetryGrading={() => undefined}
  />);

  assert.doesNotMatch(html, /参考答案|平方关系|勾股定理原文/);
  assert.match(html, /disabled/);
});

test('sequential runner reveals the submitted question reference answer', () => {
  const attempt = {
    id: 'attempt-1', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: question.id,
    attempt_number: 1, user_answer: 'a²+b²=c²', is_correct: true, score: 1, max_score: 1,
    evaluation_status: 'graded' as const, feedback: { message: '掌握准确' }, error_reason: null,
    duration_seconds: 12, submitted_at: '2026-09-01T00:00:12Z',
  };
  const revealedQuestion = { ...question, attempt, answer: 'a²+b²=c²', explanation: '平方关系' };
  const run = makeRun({
    answer_mode: 'sequential',
    attempts: [attempt],
    quiz_set: { ...makeRun().quiz_set, questions: [revealedQuestion] },
  });
  const html = renderToStaticMarkup(<QuizRunner
    session={{
      run,
      questions: [revealedQuestion],
      answers: { [question.id]: attempt.user_answer },
      attemptsByQuestionId: { [question.id]: attempt },
      revealedQuestionIds: new Set([question.id]),
      createdAt: Date.parse('2026-09-01T00:00:00Z'),
    }}
    onAnswer={() => undefined}
    onSubmitQuestion={() => undefined}
    onSubmitPaper={() => undefined}
    onRetry={() => undefined}
    onRetryGrading={() => undefined}
  />);

  assert.match(html, /参考答案/);
  assert.match(html, /平方关系/);
});

test('results reveal answer explanation feedback and traceable source links', () => {
  const attempt = {
    id: 'attempt-1', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: question.id,
    attempt_number: 1, user_answer: 'a+b=c', is_correct: false, score: 0, max_score: 1,
    evaluation_status: 'graded' as const, feedback: { message: '请检查平方项' }, error_reason: null,
    duration_seconds: 32, submitted_at: '2026-09-01T00:00:32Z',
  };
  const revealedQuestion = {
    ...question,
    attempt,
    answer: 'a²+b²=c²',
    explanation: '直角边平方和等于斜边平方。',
    source_snapshot: [{ ...question.source_snapshot[0], excerpt: '若三角形为直角三角形……' }],
  };
  const gradedRun = makeRun({
    status: 'submitted', submitted_at: '2026-09-01T00:01:15Z', score: 0, max_score: 1,
    correct_count: 0, graded_count: 1, attempts: [attempt],
    quiz_set: { ...makeRun().quiz_set, questions: [revealedQuestion] },
  });
  const html = renderToStaticMarkup(<QuizResults
    run={gradedRun}
    onRetry={() => undefined}
    onRetryGrading={() => undefined}
  />);

  for (const label of ['参考答案', '解析', 'AI 评价', '资料引用', '重新作答', '请检查平方项']) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /href="\/knowledge\/workspace-1\/documents\/document-1\?chunk=chunk-7&amp;page=3"/);
});

test('grading failures stay retryable and are not rendered as wrong answers', () => {
  const failedAttempt = {
    id: 'attempt-failed', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: question.id,
    attempt_number: 1, user_answer: '我的解释', is_correct: null, score: null, max_score: 1,
    evaluation_status: 'grading_failed' as const, feedback: null, error_reason: 'provider unavailable',
    duration_seconds: 18, submitted_at: '2026-09-01T00:00:18Z',
  };
  const failedRun = makeRun({
    status: 'submitted', submitted_at: '2026-09-01T00:00:18Z', attempts: [failedAttempt],
    quiz_set: { ...makeRun().quiz_set, questions: [{ ...question, attempt: failedAttempt }] },
  });
  const html = renderToStaticMarkup(<QuizResults
    run={failedRun}
    onRetry={() => undefined}
    onRetryGrading={() => undefined}
  />);

  assert.match(html, /评分暂未完成|重试评分|我的解释/);
  assert.doesNotMatch(html, /回答错误/);
});

test('source navigation keeps workspace, document, chunk, and page scope', () => {
  assert.equal(
    assessmentSourceHref(workspace.id, { document_id: readyDocument.id, chunk_id: 'chunk 7', page: 3 }),
    '/knowledge/workspace-1/documents/document-1?chunk=chunk+7&page=3',
  );
  assert.equal(assessmentSourceHref(workspace.id, { source_file: 'unknown.pdf' }), null);
});

test('legacy wrong-question mode remains available at the original query route', () => {
  const html = renderToStaticMarkup(<LegacyPracticeView
    workspaces={[workspace]}
    workspaceId={workspace.id}
    documents={[readyDocument]}
    documentIds={[]}
    workspacesLoading={false}
    scopeLoading={false}
    working={false}
    questions={[]}
    questionIndex={0}
    answer=""
    result={null}
    onWorkspaceChange={() => undefined}
    onDocumentChange={() => undefined}
    onAnswerChange={() => undefined}
    onSubmit={() => undefined}
    onNext={() => undefined}
    onClearError={() => undefined}
  />);

  assert.match(html, /历史错题重练/);
  assert.match(html, /旧练习记录会继续保留/);
  assert.match(html, /href="\/practice"/);
});

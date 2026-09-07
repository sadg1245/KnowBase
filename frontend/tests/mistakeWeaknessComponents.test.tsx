import React from 'react';
import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';

import { MistakeNotebook, MistakeRedoPanel } from '../src/components/practice/MistakeNotebook';
import { WeakKnowledgePanel, weaknessBand } from '../src/components/practice/WeakKnowledgePanel';
import { PracticeHistoryActions } from '../src/pages/Practice';
import { TodayTaskList } from '../src/pages/Dashboard';
import {
  dueLearningTaskFilters,
  mistakeListFilters,
  replaceMistakeFromRedo,
  retryMistakeGradingAndRefresh,
  weakKnowledgeListFilters,
} from '../src/features/practice/learningLoop';
import type { LearningTask, MistakeRecord, MistakeRedoResult, WeakKnowledgeState } from '../src/features/practice/types';

const mistake: MistakeRecord = {
  id: 'mistake-1', question_id: 'question-1', knowledge_point_id: 'point-1', workspace_id: 'workspace-1',
  latest_attempt_id: 'attempt-1', user_answer_snapshot: '3', correct_answer_snapshot: '4',
  error_reason: '混淆了平方与倍数', source_snapshot: [{ document_id: 'document-1', chunk_id: 'chunk-7', source_file: '几何.pdf', page: 8 }],
  wrong_count: 2, redo_count: 1, consecutive_correct: 0, mastery_status: 'unresolved',
  first_wrong_at: '2026-09-01T08:00:00Z', last_wrong_at: '2026-09-02T08:00:00Z', last_redone_at: null, resolved_at: null,
  document_id: 'document-1', knowledge_point_title: '勾股定理', source_label: '几何.pdf · 第 8 页', source_type: 'quiz',
  question: {
    id: 'question-1', quiz_set_id: 'set-1', workspace_id: 'workspace-1', document_id: 'document-1', knowledge_point_id: 'point-1',
    question_type: 'single_choice', prompt: '3-4-5 三角形的斜边是多少？', options: ['3', '4', '5', '6'], difficulty: 'medium', position: 1,
    source_snapshot: [{ document_id: 'document-1', chunk_id: 'chunk-7', source_file: '几何.pdf', page: 8 }], strict_sources: true, generation_model: 'local',
  },
};

const weak: WeakKnowledgeState = {
  id: 'weak-1', knowledge_point_id: 'point-1', workspace_id: 'workspace-1', weakness_score: 78,
  accuracy_component: 80, repeat_error_component: 75, review_feedback_component: 65, response_time_component: 55, recency_component: 90,
  evidence: { graded_attempt_count: 4, attempt_count: 5, unresolved_mistake_count: 2, review_count: 3, duration_comparison_count: 4 },
  recommended_actions: [
    { type: 're_read', label: '重新阅读', path: '/knowledge/workspace-1/documents/document-1?page=8' },
    { type: 'plain_explanation', label: '通俗讲解', path: '/learn?workspace=workspace-1&knowledge_point_id=point-1&mode=simple&prompt=plain' },
    { type: 'new_example', label: '生成新例子', path: '/learn?workspace=workspace-1&knowledge_point_id=point-1&mode=simple&prompt=example' },
    { type: 'targeted_practice', label: '针对性练习', path: '/practice?workspace_id=workspace-1&knowledge_point_id=point-1&mode=targeted' },
    { type: 'review', label: '加入近期复习', path: '/review?workspace_id=workspace-1&knowledge_point_id=point-1' },
  ],
  calculated_at: '2026-09-07T08:00:00Z', knowledge_point_title: '勾股定理', document_id: 'document-1', source_page: 8, source_heading: '直角三角形',
};

test('mistake notebook exposes every durable field but keeps redo editors closed', () => {
  const html = renderToStaticMarkup(<MistakeNotebook
    mistakes={[mistake, { ...mistake, id: 'mistake-2', question_id: 'question-2', question: { ...mistake.question, id: 'question-2', prompt: '第二道错题' } }]}
    total={2}
    filters={{ limit: 20, offset: 0 }}
    workspaceOptions={[{ label: '数学', value: 'workspace-1' }]}
    documentOptions={[{ label: '几何.pdf', value: 'document-1' }]}
    knowledgePointOptions={[{ label: '勾股定理', value: 'point-1' }]}
    onFiltersChange={() => undefined}
    onRedo={() => undefined}
    onRetryGrading={() => undefined}
    onSource={() => undefined}
  />);
  for (const label of ['你的答案', '正确答案', '错误原因', '知识点', '来源资料', '错误次数', '重做次数', '当前掌握状态', '重新练习', '几何.pdf']) {
    assert.match(html, new RegExp(label));
  }
  assert.doesNotMatch(html, /type="radio"/);
  assert.equal((html.match(/打开重新练习/g) || []).length, 2);
});

test('focused redo panel renders exactly one question-appropriate editor and can close', () => {
  const html = renderToStaticMarkup(<MistakeRedoPanel
    mistake={mistake}
    onAnswerChange={() => undefined}
    onClose={() => undefined}
    onRedo={() => undefined}
    onRetryGrading={() => undefined}
  />);
  assert.match(html, /type="radio"/);
  assert.match(html, /收起重新练习/);
});

test('a failed redo grade stays neutral and explicitly retryable', () => {
  const failedAttempt = {
    id: 'attempt-failed', quiz_set_id: 'set-1', quiz_run_id: 'redo-run', question_id: 'question-1', attempt_number: 3,
    user_answer: '5', is_correct: null, score: null, max_score: 1, evaluation_status: 'grading_failed' as const,
    feedback: { retryable: true }, error_reason: 'provider unavailable', duration_seconds: 5, submitted_at: '2026-09-07T09:00:00Z',
  };
  const html = renderToStaticMarkup(<MistakeRedoPanel
    mistake={{ ...mistake, question: { ...mistake.question, question_type: 'short_answer' } }} attempt={failedAttempt} answer="5"
    onAnswerChange={() => undefined} onClose={() => undefined} onRedo={() => undefined} onRetryGrading={() => undefined}
  />);
  assert.match(html, /评分暂未完成，可直接重试/);
  assert.match(html, /重新评分/);
  assert.doesNotMatch(html, /提交重做答案/);
  assert.doesNotMatch(html, /这次仍需巩固/);
});

test('only subjective pending or failed redo attempts expose grading retry', () => {
  const failedAttempt = {
    id: 'attempt-objective-failed', quiz_set_id: 'set-1', quiz_run_id: 'redo-run', question_id: 'question-1', attempt_number: 3,
    user_answer: '5', is_correct: null, score: null, max_score: 1, evaluation_status: 'grading_failed' as const,
    feedback: null, error_reason: 'unexpected failure', duration_seconds: 5, submitted_at: '2026-09-07T09:00:00Z',
  };
  const html = renderToStaticMarkup(<MistakeRedoPanel
    mistake={mistake} attempt={failedAttempt} answer="5"
    onAnswerChange={() => undefined} onClose={() => undefined} onRedo={() => undefined} onRetryGrading={() => undefined}
  />);
  assert.doesNotMatch(html, /重新评分/);
  assert.match(html, /请刷新后再试/);
});

test('weak knowledge exposes component evidence and five exact server actions', () => {
  const html = renderToStaticMarkup(<WeakKnowledgePanel
    items={[weak]}
    total={1}
    filters={{ limit: 20, offset: 0 }}
    documentOptions={[]}
    knowledgePointOptions={[]}
    onFiltersChange={() => undefined}
    onAction={() => undefined}
    onRecalculate={() => undefined}
  />);
  for (const label of ['正确率', '重复错误', '复习反馈', '答题用时', '学习间隔', '作答证据', '重新阅读', '通俗讲解', '生成新例子', '针对性练习', '加入近期复习']) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /href="\/knowledge\/workspace-1\/documents\/document-1\?page=8"/);
  assert.equal(weaknessBand(39).label, '状态平稳');
  assert.equal(weaknessBand(40).label, '继续观察');
  assert.equal(weaknessBand(70).label, '优先巩固');
});

test('list helpers retain the complete filter, due and pagination payloads', () => {
  assert.deepEqual(mistakeListFilters({ workspaceId: 'w', documentId: 'd', knowledgePointId: 'p', masteryStatus: 'mastered', limit: 10, offset: 20 }), {
    workspace_id: 'w', document_id: 'd', knowledge_point_id: 'p', mastery_status: 'mastered', limit: 10, offset: 20,
  });
  assert.deepEqual(weakKnowledgeListFilters({ workspaceId: 'w', documentId: 'd', knowledgePointId: 'p', limit: 10, offset: 10 }), {
    workspace_id: 'w', document_id: 'd', knowledge_point_id: 'p', limit: 10, offset: 10,
  });
  assert.deepEqual(dueLearningTaskFilters('2026-09-07T00:00:00.000Z', 25, 50), {
    status: 'pending', due_before: '2026-09-07T00:00:00.000Z', limit: 25, offset: 50,
  });
});

test('redo reconciliation replaces the durable mistake with returned mastery and attempt', () => {
  const result = {
    mistake: { ...mistake, mastery_status: 'mastered', consecutive_correct: 2, redo_count: 2, resolved_at: '2026-09-07T09:00:00Z' },
    attempt: { id: 'attempt-2', quiz_set_id: 'set-1', quiz_run_id: 'redo-run', question_id: 'question-1', attempt_number: 3, user_answer: '5', is_correct: true, score: 1, max_score: 1, evaluation_status: 'graded', feedback: null, error_reason: null, duration_seconds: 8, submitted_at: '2026-09-07T09:00:00Z' },
    run: {} as MistakeRedoResult['run'],
  } satisfies MistakeRedoResult;
  const reconciled = replaceMistakeFromRedo([mistake], result);
  assert.equal(reconciled.mistakes[0].mastery_status, 'mastered');
  assert.equal(reconciled.attemptsByMistakeId['mistake-1'].id, 'attempt-2');
});

test('grading retry refreshes the durable mistake and rejects stale responses', async () => {
  const retryResult = {
    attempt: { id: 'attempt-2', quiz_set_id: 'set-1', quiz_run_id: 'redo-run', question_id: 'question-1', attempt_number: 3, user_answer: '5', is_correct: true, score: 1, max_score: 1, evaluation_status: 'graded' as const, feedback: null, error_reason: null, duration_seconds: 8, submitted_at: '2026-09-07T09:00:00Z' },
    run: {} as MistakeRedoResult['run'],
  };
  let loads = 0;
  const refreshed = { ...mistake, mastery_status: 'improving' as const, consecutive_correct: 1 };
  const accepted = await retryMistakeGradingAndRefresh({
    token: 2, isCurrent: token => token === 2, attemptId: 'attempt-failed', retryGrading: async () => retryResult,
    loadMistakes: async () => { loads += 1; return { items: [refreshed], total: 1, limit: 20, offset: 0 }; },
  });
  assert.equal(loads, 1);
  assert.equal(accepted?.mistake.mastery_status, 'improving');
  assert.equal(accepted?.attempt.id, 'attempt-2');

  const stale = await retryMistakeGradingAndRefresh({
    token: 1, isCurrent: () => false, attemptId: 'attempt-failed', retryGrading: async () => retryResult,
    loadMistakes: async () => { loads += 1; return { items: [refreshed], total: 1, limit: 20, offset: 0 }; },
  });
  assert.equal(stale, null);
  assert.equal(loads, 1);
});

test('grading retry still returns the authoritative filtered page when mastery removes the record', async () => {
  const retryResult = {
    attempt: { id: 'attempt-mastered', quiz_set_id: 'set-1', quiz_run_id: 'redo-run', question_id: 'question-1', attempt_number: 4, user_answer: '5', is_correct: true, score: 1, max_score: 1, evaluation_status: 'graded' as const, feedback: null, error_reason: null, duration_seconds: 6, submitted_at: '2026-09-07T10:00:00Z' },
    run: {} as MistakeRedoResult['run'],
  };
  const refreshed = await retryMistakeGradingAndRefresh({
    token: 3,
    isCurrent: token => token === 3,
    attemptId: 'attempt-failed',
    retryGrading: async () => retryResult,
    loadMistakes: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
  });

  assert.notEqual(refreshed, null);
  assert.deepEqual(refreshed?.page, { items: [], total: 0, limit: 20, offset: 0 });
  assert.equal(refreshed?.mistake, undefined);
  assert.equal(refreshed?.attempt.id, 'attempt-mastered');
});

test('wrong notebook keeps explicit compatibility history access', () => {
  const html = renderToStaticMarkup(<PracticeHistoryActions workspaceId="workspace-1" />);
  assert.match(html, /历史错题/);
  assert.match(html, /wrong=1(?:&amp;|&)history=1/);
});

test('mixed dashboard tasks keep legacy counts and durable navigation/completion', () => {
  const task: LearningTask = {
    id: 'task-1', workspace_id: 'workspace-1', knowledge_point_id: 'point-1', task_type: 'review', title: '加入近期复习',
    path: '/review?workspace=workspace-1&knowledge_point_id=point-1', payload: {}, due_at: '2026-09-07T08:00:00Z', priority: 78,
    status: 'pending', created_at: '2026-09-06T08:00:00Z', completed_at: null, knowledge_point_title: '勾股定理', document_id: 'document-1', source_page: 8, source_heading: '直角三角形',
  };
  const html = renderToStaticMarkup(<TodayTaskList
    tasks={[
      { type: 'mistake', title: '重做薄弱题目', count: 3, path: '/practice?wrong=1' },
      task,
    ]}
    onNavigate={() => undefined}
    onComplete={() => undefined}
  />);
  assert.match(html, /还有 3 项等待你/);
  assert.match(html, /href="\/review\?workspace=workspace-1&amp;knowledge_point_id=point-1"/);
  assert.match(html, /待完成/);
  assert.match(html, /标记完成/);
});

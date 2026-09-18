import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  QuizHistoryPanel,
  quizHistoryAction,
  quizHistoryProgress,
  quizHistoryRunLabel,
  quizHistoryScopeLabel,
  quizHistoryTitle,
} from '../src/components/practice/QuizHistoryPanel';
import type { QuizSetHistoryItem } from '../src/features/practice/types';


const item = (overrides: Partial<QuizSetHistoryItem> = {}): QuizSetHistoryItem => ({
  id: 'set-1',
  workspace_id: 'workspace-1',
  title: '',
  status: 'ready',
  answer_mode: 'sequential',
  difficulty: 'medium',
  question_count: 6,
  question_types: ['single_choice', 'fill_blank'],
  section_filters: [],
  document_ids: [],
  knowledge_point_ids: [],
  strict_sources: false,
  duration_limit_seconds: null,
  generation_model: 'deepseek/deepseek-flash',
  generation_error: null,
  created_at: '2026-09-18T02:30:00Z',
  updated_at: '2026-09-18T02:31:00Z',
  documents: [],
  round_count: 0,
  run: null,
  ...overrides,
});

const run = (overrides: Partial<NonNullable<QuizSetHistoryItem['run']>> = {}) => ({
  id: 'run-1',
  round_number: 1,
  answer_mode: 'sequential' as const,
  status: 'in_progress' as const,
  started_at: '2026-09-18T02:32:00Z',
  submitted_at: null,
  elapsed_seconds: 90,
  score: 0,
  max_score: 0,
  correct_count: 0,
  graded_count: 0,
  answered_count: 3,
  total_questions: 6,
  ...overrides,
});

test('history actions follow the latest round state', () => {
  assert.deepEqual(quizHistoryAction(item()), { label: '开始作答', tone: 'start' });
  assert.deepEqual(quizHistoryAction(item({ run: run({ status: 'not_started' }) })), { label: '开始作答', tone: 'start' });
  assert.deepEqual(quizHistoryAction(item({ run: run() })), { label: '继续作答', tone: 'resume' });
  assert.deepEqual(quizHistoryAction(item({ run: run({ status: 'submitted' }) })), { label: '再练一次', tone: 'retry' });
  assert.equal(quizHistoryAction(item({ status: 'failed', generation_error: 'provider empty' })), null);
  assert.equal(quizHistoryAction(item({ status: 'generating' })), null);
});

test('history copy describes scope, progress and scores without leaking ids', () => {
  const scoped = item({
    document_ids: ['document-1'],
    documents: [{ id: 'document-1', filename: '深度学习入门.pdf' }],
    section_filters: ['5.6 Affine/Softmax 层的实现'],
    knowledge_point_ids: ['point-1'],
  });
  assert.equal(quizHistoryTitle(scoped), '自定义测验');
  assert.equal(quizHistoryTitle(item({ title: '  5.6 测验  ' })), '5.6 测验');
  assert.equal(quizHistoryScopeLabel(scoped), '深度学习入门.pdf · 5.6 Affine/Softmax 层的实现 · 1 个知识点');
  assert.equal(
    quizHistoryScopeLabel(item({ document_ids: ['a', 'b'] })),
    '2 份已解析资料 · 全部章节 · 全部知识点',
  );
  assert.equal(quizHistoryRunLabel(null), '还没有作答记录');
  assert.equal(quizHistoryRunLabel(run()), '第 1 轮 · 进行中 · 已答 3/6');
  assert.equal(
    quizHistoryRunLabel(run({ status: 'submitted', score: 4.5, max_score: 6, correct_count: 5 })),
    '第 1 轮 · 已完成 · 得分 4.5/6 · 正确 5/6',
  );
  assert.equal(quizHistoryProgress(null), 0);
  assert.equal(quizHistoryProgress(run()), 50);
  assert.equal(quizHistoryProgress(run({ status: 'submitted', answered_count: 2 })), 100);
});

test('history panel splits the two answer modes and exposes the failure reason', () => {
  const html = renderToStaticMarkup(<QuizHistoryPanel
    mode="sequential"
    counts={{ sequential: 3, full_paper: 1 }}
    items={[
      item({ run: run(), round_count: 2 }),
      item({ id: 'set-2', status: 'failed', generation_error: '模型输出预算不足' }),
    ]}
    total={3}
    filters={{ limit: 10, offset: 0 }}
    onModeChange={() => undefined}
    onFiltersChange={() => undefined}
    onOpen={() => undefined}
    onRefresh={() => undefined}
  />);

  assert.match(html, /逐题答题（3）/);
  assert.match(html, /整卷答题（1）/);
  assert.match(html, /历史出题/);
  assert.match(html, /第 1 轮 · 进行中 · 已答 3\/6/);
  assert.match(html, /共 2 轮作答/);
  assert.match(html, /继续作答/);
  assert.match(html, /模型输出预算不足/);
  assert.match(html, /答对|单项选择/);
});

test('empty history explains which answer mode has no records yet', () => {
  const html = renderToStaticMarkup(<QuizHistoryPanel
    mode="full_paper"
    counts={{ sequential: 2, full_paper: 0 }}
    items={[]}
    total={0}
    filters={{ limit: 10, offset: 0 }}
    onModeChange={() => undefined}
    onFiltersChange={() => undefined}
    onOpen={() => undefined}
    onRefresh={() => undefined}
  />);
  assert.match(html, /还没有「整卷答题」的出题记录/);
});

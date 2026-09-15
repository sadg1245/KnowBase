import React from 'react';
import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { ReviewOverview } from '../src/components/review/ReviewOverview';
import { CardLibrary } from '../src/components/review/CardLibrary';
import { ReviewSessionPanel } from '../src/components/review/ReviewSessionPanel';
import { ReviewResults } from '../src/components/review/ReviewResults';
import type { Flashcard, ReviewSummary } from '../src/services/api';
import type { LearningTask } from '../src/features/practice/types';
import { createReviewSession, flipCard } from '../src/features/review/reviewSession';

const card: Flashcard = {
  id: 'card-1', workspace_id: 'workspace-1', knowledge_point_id: 'point-1',
  front: '什么是间隔重复？', back: '在逐渐拉长的时间间隔后重新回忆。',
  source_label: '长期记忆 · 第 3 页', source_type: 'knowledge_point',
  source_snapshot: null, tags: ['记忆'], difficulty: 2, mastery: 0.4,
  mastery_status: 'learning', due_at: '2026-08-29T00:00:00Z', interval_days: 1,
  ease: 2.5, review_count: 2, algorithm_version: 'simple_v1', scheduler_data: {},
  last_reviewed_at: null, total_review_seconds: 25,
  created_at: '2026-08-28T00:00:00Z', updated_at: '2026-08-28T00:00:00Z',
};

const summary: ReviewSummary = {
  due_count: 8, new_count: 3, completed_today: 4, estimated_minutes: 6,
  streak_days: 5, overdue_count: 2, daily_target: 10,
  weak_points: [{
    id: 'point-1', workspace_id: 'workspace-1', title: '遗忘曲线', mastery: 0.25,
    mastery_status: 'learning', importance: 5, is_key: true,
  }],
};

const learningTask: LearningTask = {
  id: 'task-1', workspace_id: 'workspace-1', knowledge_point_id: 'point-1', task_type: 'targeted_practice', title: '针对性练习',
  path: '/practice?workspace=workspace-1&knowledge_point_id=point-1&mode=targeted', payload: {}, due_at: '2026-09-07T08:00:00Z',
  priority: 80, status: 'pending', created_at: '2026-09-06T08:00:00Z', completed_at: null, knowledge_point_title: '遗忘曲线',
  document_id: null, source_page: null, source_heading: null,
};

test('review overview renders every required metric and start action', () => {
  const html = renderToStaticMarkup(
    <ReviewOverview summary={summary} tasks={[learningTask]} onStart={() => undefined} onManage={() => undefined} onTask={() => undefined} onCompleteTask={() => undefined} />,
  );
  for (const label of ['今日待复习', '新卡片', '今日完成', '预计时长', '连续学习', '逾期卡片', '薄弱知识点', '开始复习']) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /近期学习任务/);
  assert.match(html, /针对性练习/);
  assert.match(html, /href="\/practice\?workspace=workspace-1&amp;knowledge_point_id=point-1&amp;mode=targeted"/);
  assert.ok(html.indexOf('遗忘曲线') < html.indexOf('针对性练习'), 'backend weak-point order and existing weak section stay ahead of tasks');
});

test('card library exposes filtering and CRUD actions', () => {
  const html = renderToStaticMarkup(
    <CardLibrary
      cards={[card]}
      loading={false}
      onCreate={() => undefined}
      onEdit={() => undefined}
      onDelete={() => undefined}
      onFiltersChange={() => undefined}
    />,
  );
  for (const label of ['新建卡片', '搜索卡片', '全部来源', '编辑', '删除', '什么是间隔重复']) {
    assert.match(html, new RegExp(label));
  }
});

test('review session exposes four ratings and discoverable shortcuts', () => {
  const state = flipCard(createReviewSession([card], 1_000));
  const html = renderToStaticMarkup(
    <ReviewSessionPanel
      state={state}
      submitting={false}
      onFlip={() => undefined}
      onRate={async () => undefined}
      onExit={() => undefined}
    />,
  );
  for (const label of ['忘记了', '有点模糊', '记住了', '非常熟练', '按 1–4 评分']) {
    assert.match(html, new RegExp(label));
  }
});

test('results show rating distribution time and mastery change', () => {
  const html = renderToStaticMarkup(
    <ReviewResults
      results={{ completed: 4, ratingCounts: { 1: 1, 2: 1, 3: 1, 4: 1 }, totalSeconds: 52, averageSeconds: 13, masteryDelta: 0.06 }}
      onOverview={() => undefined}
      onCards={() => undefined}
    />,
  );
  assert.match(html, /总耗时/);
  assert.match(html, /平均每张/);
  assert.match(html, /掌握度变化/);
});

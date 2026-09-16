import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { ActivityTimeline } from '../src/components/dashboard/ActivityTimeline';
import { LearningQueue } from '../src/components/dashboard/LearningQueue';
import { QuickQuestion } from '../src/components/dashboard/QuickQuestion';
import { TodayPlan } from '../src/components/dashboard/TodayPlan';
import { evidenceDetail } from '../src/components/report/EvidenceDrawer';

test('quick question and today plan render safe actions and completed copy', () => {
  const quick = renderToStaticMarkup(<QuickQuestion
    workspaces={[{ id: 'ws-1', name: '线性代数' }]}
    onAsk={() => undefined}
  />);
  assert.match(quick, /快速提问/);
  assert.match(quick, /先写下你的问题/);
  assert.match(quick, /线性代数/);

  const plan = renderToStaticMarkup(<TodayPlan tasks={[
    { id: 'derived:today:review:global', type: 'review', title: '完成今日复习', path: '/review', count: 7, estimated_minutes: 6, status: 'pending', derived: true },
    { id: 'derived:today:mistake:global', type: 'mistake', title: '重做错题', path: '/practice', count: 0, estimated_minutes: 0, status: 'completed', derived: true },
  ]} onNavigate={() => undefined} onComplete={() => undefined} />);
  assert.match(plan, /7 张/);
  assert.match(plan, /约 6 分钟/);
  assert.match(plan, /今日已完成/);
  assert.doesNotMatch(plan, /标记完成/);
});

test('learning queue shows counts, recommendation reason, and directional empty action', () => {
  const html = renderToStaticMarkup(<LearningQueue
    queue={{ due_reviews: { count: 4, path: '/review' }, mistakes: { count: 2, path: '/practice?wrong=1' } }}
    recommendations={[{
      workspace_id: 'ws-1', name: '概率论', description: '', domain: '数学', accent_color: '#167d8d',
      score: 27, components: { goal_urgency: 0, weakness: 27, unfinished_work: 0, recent_activity: 0, new_material: 0 },
      reason: '存在需要巩固的薄弱知识', path: '/knowledge/ws-1',
    }]}
    onNavigate={() => undefined}
  />);
  assert.match(html, /待复习卡片/);
  assert.match(html, />4</);
  assert.match(html, /待重做错题/);
  assert.match(html, /存在需要巩固的薄弱知识/);

  const empty = renderToStaticMarkup(<LearningQueue
    queue={{ due_reviews: { count: 0, path: '/review' }, mistakes: { count: 0, path: '/practice' } }}
    recommendations={[]}
    onNavigate={() => undefined}
  />);
  assert.match(empty, /导入一份资料/);
});

test('activity timeline labels records without a source as legacy history', () => {
  const html = renderToStaticMarkup(<ActivityTimeline activities={[
    { id: 'a1', type: 'organize', title: '整理资料', duration_seconds: 60, created_at: '2026-09-15T00:00:00Z' },
  ]} />);
  assert.match(html, /最近学习记录/);
  assert.match(html, /历史记录/);
});

test('report evidence explains how quiz mastery and weakness rows contribute', () => {
  assert.match(evidenceDetail({ kind: 'quiz_attempt', score: 8, max_score: 10 } as any) || '', /8\/10/);
  assert.match(evidenceDetail({
    kind: 'activity', activity_type: 'mastery_changed',
    payload: { before_mastery: 20, after_mastery: 45, before_status: 'learning', after_status: 'familiar' },
  } as any) || '', /20 → 45/);
  assert.match(evidenceDetail({
    kind: 'activity', activity_type: 'weakness_changed',
    payload: { before_score: 70, after_score: 35, before_category: 'weak', after_category: 'watch' },
  } as any) || '', /70 → 35/);
});

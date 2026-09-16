import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { GoalEditor, toGlobalGoalPayload } from '../src/components/report/GoalEditor';

test('goal payload keeps calendar dates and validates limits', () => {
  assert.equal(toGlobalGoalPayload({
    minutes: 30, reviews: 10, weeklyDays: 5,
    targetDate: '2026-12-31', timezoneName: 'Asia/Shanghai',
  }).target_completion_date, '2026-12-31');
  assert.throws(() => toGlobalGoalPayload({
    minutes: 0, reviews: 10, weeklyDays: 5,
    targetDate: '2026-12-31', timezoneName: 'Asia/Shanghai',
  }));
});

test('goal editor exposes all global and workspace goal controls', () => {
  const html = renderToStaticMarkup(<GoalEditor
    open
    initial={{ minutes: 30, reviews: 10, weeklyDays: 5, targetDate: '2026-12-31', timezoneName: 'Asia/Shanghai' }}
    workspaces={[{ id: 'ws-1', name: '机器学习', targetMastery: 80, targetDate: '2027-01-31' }]}
    saving={false}
    error="部分知识库目标保存失败"
    onClose={() => undefined}
    onSave={() => undefined}
  />);
  assert.match(html, /每日学习分钟数/);
  assert.match(html, /每日复习卡片数/);
  assert.match(html, /每周学习天数/);
  assert.match(html, /总目标日期/);
  assert.match(html, /机器学习/);
  assert.match(html, /部分知识库目标保存失败/);
});

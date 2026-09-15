import assert from 'node:assert/strict';
import test from 'node:test';

import { dashboardTaskAction } from '../src/features/dashboard/dashboardViewModel';

test('derived tasks navigate but cannot be manually completed', () => {
  assert.deepEqual(dashboardTaskAction({
    id: 'derived:2026-09-15:review:global', type: 'review', title: '复习',
    status: 'pending', path: '/review', derived: true,
  }), { kind: 'navigate', path: '/review' });
});

test('persistent pending task exposes complete action', () => {
  assert.equal(dashboardTaskAction({
    id: 'task-1', type: 'targeted_practice', title: '练习', status: 'pending',
    path: '/practice', derived: false, source: { type: 'learning_task' },
  }).kind, 'complete');
});

test('completed and pathless derived tasks expose no invalid action', () => {
  assert.deepEqual(dashboardTaskAction({
    id: 'derived:x', type: 'review', title: '完成', status: 'completed', path: '/review', derived: true,
  }), { kind: 'navigate', path: '/review' });
  assert.deepEqual(dashboardTaskAction({
    id: 'derived:y', type: 'review', title: '等待', status: 'pending', path: null, derived: true,
  }), { kind: 'none' });
});

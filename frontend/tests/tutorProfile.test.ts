import assert from 'node:assert/strict';
import test from 'node:test';

import { filterMemories, memoryKindLabel, memorySourceLabel, profileSummary } from '../src/features/learning/tutorProfile';

const memory = (overrides: Partial<any> = {}) => ({
  id: 'mem-1', kind: 'mistake_pattern', title: '闭包的常见错误', content: '循环变量绑定错误',
  workspace_id: null, source_refs: { knowledge_point_id: 'kp-1' }, importance: 0.75,
  is_active: true, embedding_state: 'ready', use_count: 2, last_used_at: null,
  created_at: '2026-09-18T02:00:00+00:00', updated_at: '2026-09-18T02:00:00+00:00',
  ...overrides,
});

test('memory kinds and sources are human readable', () => {
  assert.equal(memoryKindLabel('mistake_pattern'), '错题模式');
  assert.equal(memoryKindLabel('manual'), '手动记录');
  assert.match(memorySourceLabel(memory() as any), /知识点/);
});

test('memory filtering respects kind and active state', () => {
  const items = [memory(), memory({ id: 'mem-2', kind: 'manual' }), memory({ id: 'mem-3', is_active: false })];

  assert.deepEqual(filterMemories(items as any, 'manual').map(item => item.id), ['mem-2']);
  assert.deepEqual(filterMemories(items as any, undefined).map(item => item.id), ['mem-1', 'mem-2']);
});

test('profile summary counts weak points and next actions', () => {
  const summary = profileSummary({
    display_name: '小光', preferred_mode: 'simple', goal_summary: '日目标 30 分钟',
    mastery: [], recent_topics: ['RAG 重排'], next_actions: ['复习闭包'],
    weak_points: [{ knowledge_point_id: 'kp-1', title: '闭包', mastery: 0.45, weakness_score: 72, reason: '' }],
    common_mistakes: [], generated_at: '2026-09-18T02:00:00+00:00',
  });

  assert.match(summary, /1 个薄弱知识点/);
  assert.match(summary, /复习闭包/);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { TutorProfilePanel } from '../src/components/learning/TutorProfileDrawer';

const profile = {
  display_name: '小光', preferred_mode: 'simple', goal_summary: '日目标 30 分钟',
  mastery: [], recent_topics: ['RAG 重排'], next_actions: ['复习闭包'],
  weak_points: [{ knowledge_point_id: 'kp-1', title: '闭包', mastery: 0.45, weakness_score: 72, reason: '最近两次练习错误' }],
  common_mistakes: [{ knowledge_point_title: '闭包', pattern: '循环变量绑定错误', count: 2 }],
  generated_at: '2026-09-18T02:00:00+00:00',
};

const memories = [
  { id: 'mem-1', kind: 'mistake_pattern', title: '闭包的常见错误', content: '循环变量绑定错误', workspace_id: null, source_refs: { knowledge_point_id: 'kp-1' }, importance: 0.75, is_active: true, embedding_state: 'ready', use_count: 2, last_used_at: null, created_at: '', updated_at: '' },
  { id: 'mem-2', kind: 'manual', title: '先给例子', content: '喜欢先看例子再看定义', workspace_id: null, source_refs: {}, importance: 0.9, is_active: false, embedding_state: 'ready', use_count: 0, last_used_at: null, created_at: '', updated_at: '' },
];

test('tutor profile panel shows profile, active memories, and the evidence disclaimer', () => {
  const html = renderToStaticMarkup(<TutorProfilePanel
    profile={profile as any}
    memories={memories as any}
    loading={false}
    onFilter={() => undefined}
    onToggle={() => undefined}
    onDelete={() => undefined}
  />);

  assert.match(html, /不会当作你的资料证据/);
  assert.match(html, /闭包/);
  assert.match(html, /闭包的常见错误/);
  assert.doesNotMatch(html, /先给例子/);
});

test('tutor profile panel renders an empty state without memories', () => {
  const html = renderToStaticMarkup(<TutorProfilePanel
    profile={profile as any}
    memories={[]}
    loading={false}
    onFilter={() => undefined}
    onToggle={() => undefined}
    onDelete={() => undefined}
  />);

  assert.match(html, /还没有学习记忆/);
});

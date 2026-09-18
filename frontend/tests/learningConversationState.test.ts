import assert from 'node:assert/strict';
import test from 'node:test';

import * as stateModule from '../src/features/learning/learningConversationState.ts';


test('流式事件依次更新会话、证据、正文、来源、追问和完成状态', () => {
  const createState = (stateModule as Record<string, unknown>).createAssistantDraft;
  const applyEvent = (stateModule as Record<string, unknown>).applyChatEvent;
  assert.equal(typeof createState, 'function');
  assert.equal(typeof applyEvent, 'function');

  let state = (createState as () => any)();
  const reduce = applyEvent as (value: any, event: any) => any;
  state = reduce(state, { session: { id: 'session-a', title: '向量检索', title_changed: true } });
  state = reduce(state, { evidence: { status: 'supported', vector_succeeded: true, keyword_succeeded: true, top_score: 0.72 } });
  state = reduce(state, { token: '第一段' });
  state = reduce(state, { token: '第二段' });
  state = reduce(state, { sources: [{ source_file: '资料.pdf', content: '证据', score: 0.72 }] });
  state = reduce(state, { suggestions: ['继续深入'] });
  state = reduce(state, { done: true, message_id: 'message-a', session_id: 'session-a', generation_status: 'complete' });

  assert.equal(state.session.id, 'session-a');
  assert.equal(state.content, '第一段第二段');
  assert.equal(state.evidence.status, 'supported');
  assert.equal(state.sources.length, 1);
  assert.deepEqual(state.suggestions, ['继续深入']);
  assert.equal(state.messageId, 'message-a');
  assert.equal(state.status, 'complete');
});

test('专注三栏按桌面、平板和移动端断点退化', () => {
  const layout = (stateModule as Record<string, unknown>).learningLayoutForWidth;
  assert.equal(typeof layout, 'function');
  const resolve = layout as (width: number) => string;

  assert.equal(resolve(1440), 'three-column');
  assert.equal(resolve(1024), 'two-column');
  assert.equal(resolve(390), 'single-column');
});

test('证据状态使用面向学习者的明确文案', () => {
  const label = (stateModule as Record<string, unknown>).evidenceStatusLabel;
  assert.equal(typeof label, 'function');
  const resolve = label as (status?: string) => string;

  assert.equal(resolve('supported'), '资料命中');
  assert.equal(resolve('limited'), '资料不足，已用模型补充');
  assert.equal(resolve('insufficient'), '资料不足，已用模型补充');
  assert.equal(resolve('model_only'), '仅模型补充');
  assert.equal(resolve(), '尚未检索');
});

test('删除当前会话时清空孤立的历史消息', () => {
  const resolver = (stateModule as Record<string, unknown>).messagesAfterSessionDelete;

  assert.equal(typeof resolver, 'function');
  const resolve = resolver as <T>(activeId: string | undefined, deletedId: string, messages: T[]) => T[];
  const messages = [{ id: 'message-a' }];
  assert.deepEqual(resolve('session-a', 'session-a', messages), []);
  assert.equal(resolve('session-b', 'session-a', messages), messages);
});

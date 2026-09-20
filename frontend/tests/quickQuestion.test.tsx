import assert from 'node:assert/strict';
import test from 'node:test';

import { consumeQuickQuestion, quickQuestionDestination } from '../src/features/learning/quickQuestion';

test('quick question uses navigation state and never URL query text', () => {
  const result = quickQuestionDestination('如何理解梯度下降？', 'ws-1', 'nonce-1');
  assert.equal(result.pathname, '/learn');
  assert.equal(result.search, undefined);
  assert.deepEqual(result.state, {
    quickQuestion: '如何理解梯度下降？', workspaceId: 'ws-1', nonce: 'nonce-1',
  });
});

test('navigation nonce is consumed once and invalid state is ignored', () => {
  const state = { quickQuestion: '  请解释注意力机制  ', workspaceId: 'ws-1', nonce: 'nonce-1' };
  assert.deepEqual(consumeQuickQuestion(state, undefined), {
    question: '请解释注意力机制', workspaceId: 'ws-1', nonce: 'nonce-1',
  });
  assert.equal(consumeQuickQuestion(state, 'nonce-1'), null);
  assert.equal(consumeQuickQuestion({ quickQuestion: '', nonce: 'nonce-2' }, undefined), null);
});

test('practice context travels with the quick question state', () => {
  const result = quickQuestionDestination('这道题该怎么想', 'ws-1', 'nonce-practice', 'practice');

  assert.deepEqual(result.state, {
    quickQuestion: '这道题该怎么想', workspaceId: 'ws-1', nonce: 'nonce-practice', mode: 'practice',
  });
  assert.deepEqual(consumeQuickQuestion(result.state, undefined), {
    question: '这道题该怎么想', workspaceId: 'ws-1', nonce: 'nonce-practice', mode: 'practice',
  });
});

test('unknown quick question modes are dropped instead of forwarded', () => {
  assert.deepEqual(consumeQuickQuestion({ quickQuestion: '问题', nonce: 'nonce-x', mode: 'exam' }, undefined), {
    question: '问题', nonce: 'nonce-x',
  });
});

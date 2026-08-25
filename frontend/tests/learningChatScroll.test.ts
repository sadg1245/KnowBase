import assert from 'node:assert/strict';
import test from 'node:test';

import { scrollMessagesIntoView } from '../src/pages/learningChatScroll.ts';

test('滚动助手不把浏览器返回的 Promise 当成 React effect 清理函数', () => {
  let called = false;
  const result = scrollMessagesIntoView({
    scrollIntoView: () => {
      called = true;
      return Promise.resolve();
    },
  });

  assert.equal(called, true);
  assert.equal(result, undefined);
});

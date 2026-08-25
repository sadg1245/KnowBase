import assert from 'node:assert/strict';
import test from 'node:test';

import * as sessionSidebarModule from '../src/components/learning/SessionSidebar.tsx';

type Confirmation = {
  title: string;
  content: string;
  okText: string;
  cancelText: string;
  centered: boolean;
  okButtonProps: { danger: boolean };
  onOk: () => Promise<void>;
};

const pendingSessionSidebarModule = sessionSidebarModule as typeof sessionSidebarModule & {
  requestSessionDeletion?: (
    session: { id: string; title: string },
    actions: {
      confirm: (confirmation: Confirmation) => void;
      remove: (sessionId: string) => Promise<void>;
      onSuccess: (sessionTitle: string) => void;
      onError: (error: unknown) => void;
    },
  ) => void;
};

test('点击会话垃圾桶先打开居中确认对话框，确认后才删除', async () => {
  let confirmation: Confirmation | undefined;
  const removedIds: string[] = [];
  const successfulTitles: string[] = [];

  assert.equal(
    typeof pendingSessionSidebarModule.requestSessionDeletion,
    'function',
    '会话删除需要使用明确的确认对话框',
  );

  pendingSessionSidebarModule.requestSessionDeletion?.(
    { id: 'session-1', title: '新学习会话' },
    {
      confirm: config => { confirmation = config; },
      remove: async sessionId => { removedIds.push(sessionId); },
      onSuccess: sessionTitle => { successfulTitles.push(sessionTitle); },
      onError: () => undefined,
    },
  );

  assert.deepEqual(removedIds, []);
  assert.ok(confirmation);
  assert.equal(confirmation.centered, true);
  assert.equal(confirmation.title, '删除会话“新学习会话”？');
  assert.equal(confirmation.content, '聊天记录将被删除；已保存的卡片和笔记会保留。');
  assert.equal(confirmation.cancelText, '取消');
  assert.equal(confirmation.okText, '确定删除');
  assert.equal(confirmation.okButtonProps.danger, true);

  await confirmation.onOk();

  assert.deepEqual(removedIds, ['session-1']);
  assert.deepEqual(successfulTitles, ['新学习会话']);
});

test('会话删除失败时报告错误并保留确认对话框', async () => {
  let confirmation: Confirmation | undefined;
  const failures: unknown[] = [];
  const failure = new Error('network unavailable');

  assert.equal(typeof pendingSessionSidebarModule.requestSessionDeletion, 'function');

  pendingSessionSidebarModule.requestSessionDeletion?.(
    { id: 'session-2', title: '什么是感知机' },
    {
      confirm: config => { confirmation = config; },
      remove: async () => { throw failure; },
      onSuccess: () => assert.fail('删除失败时不应报告成功'),
      onError: error => { failures.push(error); },
    },
  );

  assert.ok(confirmation);
  await assert.rejects(confirmation.onOk(), failure);
  assert.deepEqual(failures, [failure]);
});

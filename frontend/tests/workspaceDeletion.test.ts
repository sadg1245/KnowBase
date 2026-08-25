import assert from 'node:assert/strict';
import test from 'node:test';

import * as workspacesModule from '../src/pages/Workspaces.tsx';

type Confirmation = {
  title: string;
  content: string;
  okText: string;
  cancelText: string;
  centered: boolean;
  okButtonProps: { danger: boolean };
  onOk: () => Promise<void>;
};

const pendingWorkspacesModule = workspacesModule as typeof workspacesModule & {
  requestWorkspaceDeletion?: (
    workspace: { id: string; name: string },
    actions: {
      confirm: (confirmation: Confirmation) => void;
      remove: (workspaceId: string) => Promise<void>;
      onSuccess: (workspaceName: string) => void;
      onError: (error: unknown) => void;
    },
  ) => void;
};

test('点击垃圾桶先打开居中确认对话框，确认后才删除知识库', async () => {
  let confirmation: Confirmation | undefined;
  const removedIds: string[] = [];
  const successfulNames: string[] = [];

  assert.equal(
    typeof pendingWorkspacesModule.requestWorkspaceDeletion,
    'function',
    '知识库删除需要使用明确的确认对话框',
  );

  pendingWorkspacesModule.requestWorkspaceDeletion?.(
    { id: 'workspace-1', name: '测试2' },
    {
      confirm: config => { confirmation = config; },
      remove: async workspaceId => { removedIds.push(workspaceId); },
      onSuccess: workspaceName => { successfulNames.push(workspaceName); },
      onError: () => undefined,
    },
  );

  assert.deepEqual(removedIds, []);
  assert.ok(confirmation);
  assert.equal(confirmation.centered, true);
  assert.equal(confirmation.title, '删除知识库“测试2”？');
  assert.equal(confirmation.content, '相关资料和学习记录将一起删除，此操作不可撤销。');
  assert.equal(confirmation.cancelText, '取消');
  assert.equal(confirmation.okText, '确定删除');
  assert.equal(confirmation.okButtonProps.danger, true);

  await confirmation.onOk();

  assert.deepEqual(removedIds, ['workspace-1']);
  assert.deepEqual(successfulNames, ['测试2']);
});

test('删除失败时保留确认对话框并显示错误提示', async () => {
  let confirmation: Confirmation | undefined;
  const failures: unknown[] = [];
  const failure = new Error('network unavailable');

  assert.equal(typeof pendingWorkspacesModule.requestWorkspaceDeletion, 'function');

  pendingWorkspacesModule.requestWorkspaceDeletion?.(
    { id: 'workspace-2', name: '测试' },
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

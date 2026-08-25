import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveUploadWorkspace } from '../src/pages/uploadWorkspaceSelection.ts';

const workspaces = [
  { id: 'only-workspace', name: '测试' },
];

test('只有一个知识库且未指定时自动选中', () => {
  assert.equal(resolveUploadWorkspace(workspaces, ''), 'only-workspace');
});

test('保留仍然有效的已选知识库', () => {
  assert.equal(resolveUploadWorkspace(workspaces, 'only-workspace'), 'only-workspace');
});

test('多个知识库且未指定时不擅自选择', () => {
  assert.equal(
    resolveUploadWorkspace(
      [...workspaces, { id: 'another-workspace', name: '另一个' }],
      '',
    ),
    '',
  );
});

test('已选知识库不存在时清空旧值', () => {
  assert.equal(resolveUploadWorkspace(workspaces, 'missing-workspace'), '');
});

import assert from 'node:assert/strict';
import test from 'node:test';

import * as practiceScopeModule from '../src/pages/practiceScope.ts';
import {
  practiceDocumentPlaceholder,
  practiceWorkspaceOption,
  readyPracticeDocuments,
  resolvePracticeWorkspaceSelection,
} from '../src/pages/practiceScope.ts';


const pendingPracticeScope = practiceScopeModule as typeof practiceScopeModule & {
  createPracticeRequestGuard?: () => {
    start: () => number;
    invalidate: () => void;
    isCurrent: (token: number) => boolean;
  };
  resolvePracticeDocumentIds?: (
    documents: { id: string; status: string }[],
    selectedIds: string[],
  ) => string[];
};


test('无文件知识库仍可从下拉框选择并查看空文件状态', () => {
  assert.deepEqual(
    practiceWorkspaceOption({ id: 'empty', name: '测试2', document_count: 0 }),
    { label: '测试2 · 0 个文件', value: 'empty' },
  );
});

test('有文件知识库保持可选并显示文件数量', () => {
  assert.deepEqual(
    practiceWorkspaceOption({ id: 'ready', name: '测试', document_count: 7 }),
    { label: '测试 · 7 个文件', value: 'ready' },
  );
});

test('练习范围只把已解析文件视为可用资料', () => {
  const documents = [
    { id: 'ready', status: 'ready' },
    { id: 'failed', status: 'failed' },
    { id: 'processing', status: 'processing' },
  ];

  assert.deepEqual(readyPracticeDocuments(documents).map(item => item.id), ['ready']);
  assert.equal(practiceDocumentPlaceholder(undefined, []), '先选择知识库');
  assert.equal(practiceDocumentPlaceholder('workspace', documents), '全部已解析文件');
  assert.equal(practiceDocumentPlaceholder('workspace', documents.slice(1)), '该知识库暂无可用文件');
});

test('未选择具体文件时把所有已解析文件作为明确资料范围', () => {
  const documents = [
    { id: 'ready-a', status: 'ready' },
    { id: 'failed', status: 'failed' },
    { id: 'ready-b', status: 'ready' },
  ];

  assert.deepEqual(
    pendingPracticeScope.resolvePracticeDocumentIds?.(documents, []),
    ['ready-a', 'ready-b'],
  );
  assert.deepEqual(
    pendingPracticeScope.resolvePracticeDocumentIds?.(documents, ['ready-b']),
    ['ready-b'],
  );
});

test('资料范围改变后拒绝旧生成请求的返回结果', () => {
  const guard = pendingPracticeScope.createPracticeRequestGuard?.();
  assert.ok(guard, '练习生成请求需要范围版本保护');

  const requestToken = guard.start?.();
  assert.equal(typeof requestToken, 'number');
  assert.equal(guard.isCurrent(requestToken), true);
  const newerRequestToken = guard.start?.();
  assert.equal(guard.isCurrent(requestToken), false);
  assert.equal(guard.isCurrent(newerRequestToken), true);
  guard.invalidate();
  assert.equal(guard.isCurrent(newerRequestToken), false);
});

test('练习页只在唯一知识库有文件时自动选择', () => {
  const empty = { id: 'empty', name: '测试2', document_count: 0 };
  const ready = { id: 'ready', name: '测试', document_count: 7 };

  assert.equal(resolvePracticeWorkspaceSelection([empty]), undefined);
  assert.equal(resolvePracticeWorkspaceSelection([ready]), 'ready');
  assert.equal(resolvePracticeWorkspaceSelection([empty, ready]), undefined);
  assert.equal(resolvePracticeWorkspaceSelection([empty, ready], 'ready'), 'ready');
  assert.equal(resolvePracticeWorkspaceSelection([empty, ready], 'empty'), 'empty');
});

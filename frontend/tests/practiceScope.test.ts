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
  requestedPracticeScope?: (params: URLSearchParams) => {
    workspaceId?: string;
    knowledgePointId?: string;
  };
  resolveRequestedKnowledgePointId?: (
    points: Array<{ id: string; workspace_id: string; document_id?: string | null }>,
    requestedId: string | undefined,
    workspaceId: string,
    effectiveDocumentIds: string[],
  ) => string | undefined;
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

test('恢复测验在创建运行期间失效后不会启动旧运行', async () => {
  const restoreGuardedPracticeRun = (practiceScopeModule as Record<string, unknown>).restoreGuardedPracticeRun as undefined | ((options: {
    token: number;
    isCurrent: (token: number) => boolean;
    loadQuizSet: () => Promise<{ id: string }>;
    existingRun: () => null;
    createRun: () => Promise<{ id: string; status: 'not_started' }>;
    startRun: () => Promise<{ id: string; status: 'in_progress' }>;
  }) => Promise<{ id: string; status: string } | null>);
  assert.ok(restoreGuardedPracticeRun, '恢复流程需要在每个异步变更后验证请求版本');
  const guard = pendingPracticeScope.createPracticeRequestGuard?.();
  assert.ok(guard);
  const token = guard.start();
  let releaseCreate!: (run: { id: string; status: 'not_started' }) => void;
  let signalCreate!: () => void;
  const createReached = new Promise<void>(resolve => { signalCreate = resolve; });
  const created = new Promise<{ id: string; status: 'not_started' }>(resolve => { releaseCreate = resolve; });
  let starts = 0;

  const restoration = restoreGuardedPracticeRun({
    token,
    isCurrent: guard.isCurrent,
    loadQuizSet: async () => ({ id: 'set-old' }),
    existingRun: () => null,
    createRun: async () => {
      signalCreate();
      return created;
    },
    startRun: async run => {
      starts += 1;
      return { ...run, status: 'in_progress' };
    },
  });
  await createReached;
  guard.invalidate();
  releaseCreate({ id: 'run-old', status: 'not_started' });

  assert.equal(await restoration, null);
  assert.equal(starts, 0, '旧路由创建的运行绝不能在后台启动');
});

test('过期操作收尾不会清除较新的加载或重试状态', () => {
  const finishMatchingPracticeOperation = (practiceScopeModule as Record<string, unknown>).finishMatchingPracticeOperation as undefined | (<T extends { token: number }>(
    current: T | undefined,
    completedToken: number,
  ) => T | undefined);
  assert.ok(finishMatchingPracticeOperation, '异步操作状态需要按自身 token 收尾');
  const newer = { token: 4, attemptId: 'attempt-new' };

  assert.equal(finishMatchingPracticeOperation(newer, 3), newer);
  assert.equal(finishMatchingPracticeOperation(newer, 4), undefined);
});

test('旧版答题提交只接受当前范围中的同一道题', async () => {
  const submitGuardedLegacyAnswer = (practiceScopeModule as Record<string, unknown>).submitGuardedLegacyAnswer as undefined | (<T>(options: {
    token: number;
    questionId: string;
    isCurrent: (token: number) => boolean;
    currentQuestionId: () => string | undefined;
    submit: () => Promise<T>;
  }) => Promise<T | null>);
  assert.ok(submitGuardedLegacyAnswer, '旧版提交需要同时校验请求版本与题目身份');
  const guard = pendingPracticeScope.createPracticeRequestGuard?.();
  assert.ok(guard);
  const token = guard.start();
  let currentQuestionId = 'question-old';
  let releaseSubmit!: (result: { correct: boolean }) => void;
  const submitted = new Promise<{ correct: boolean }>(resolve => { releaseSubmit = resolve; });
  const response = submitGuardedLegacyAnswer({
    token,
    questionId: currentQuestionId,
    isCurrent: guard.isCurrent,
    currentQuestionId: () => currentQuestionId,
    submit: () => submitted,
  });

  currentQuestionId = 'question-new';
  guard.invalidate();
  releaseSubmit({ correct: true });
  assert.equal(await response, null);
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

test('推荐链接兼容两种知识库参数并安全读取知识点范围', () => {
  assert.deepEqual(
    pendingPracticeScope.requestedPracticeScope?.(new URLSearchParams('workspace_id=workspace-1&knowledge_point_id=point-1')),
    { workspaceId: 'workspace-1', knowledgePointId: 'point-1' },
  );
  assert.deepEqual(
    pendingPracticeScope.requestedPracticeScope?.(new URLSearchParams('workspace=preferred&workspace_id=legacy&knowledge_point_id=%20')),
    { workspaceId: 'preferred', knowledgePointId: undefined },
  );
});

test('推荐知识点只在当前知识库和可用资料范围内生效', () => {
  const points = [
    { id: 'valid', workspace_id: 'workspace-1', document_id: 'ready-document' },
    { id: 'wrong-workspace', workspace_id: 'workspace-2', document_id: 'ready-document' },
    { id: 'pending-document', workspace_id: 'workspace-1', document_id: 'pending-document' },
  ];

  assert.equal(pendingPracticeScope.resolveRequestedKnowledgePointId?.(points, 'valid', 'workspace-1', ['ready-document']), 'valid');
  assert.equal(pendingPracticeScope.resolveRequestedKnowledgePointId?.(points, 'wrong-workspace', 'workspace-1', ['ready-document']), undefined);
  assert.equal(pendingPracticeScope.resolveRequestedKnowledgePointId?.(points, 'pending-document', 'workspace-1', ['ready-document']), undefined);
});

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildScopePayload,
  scopeChoiceFromPayload,
  scopeSummaryLabel,
  scopeRequiresDocuments,
  scopeRequiresWorkspace,
  scopeNoticeText,
} from '../src/pages/learningScope';

const input = {
  workspaceId: 'ws-ai',
  documentIds: ['doc-1', 'doc-2'],
  knowledgePointId: 'kp-1',
  allowWorkspaceExpansion: false,
};

test('smart scope keeps the workspace as the starting point and allows expansion', () => {
  const scope = buildScopePayload('smart', input);

  assert.equal(scope.mode, 'smart');
  assert.deepEqual(scope.workspace_ids, ['ws-ai']);
  assert.deepEqual(scope.document_ids, []);
  assert.equal(scope.allow_workspace_expansion, true);
});

test('workspace scope is strict and never expands', () => {
  const scope = buildScopePayload('workspace', input);

  assert.equal(scope.mode, 'strict');
  assert.deepEqual(scope.workspace_ids, ['ws-ai']);
  assert.equal(scope.allow_workspace_expansion, false);
});

test('document scope keeps exactly one file', () => {
  const scope = buildScopePayload('document', input);

  assert.equal(scope.mode, 'strict');
  assert.deepEqual(scope.document_ids, ['doc-1']);
});

test('documents scope maps the expansion switch to focused mode', () => {
  const strict = buildScopePayload('documents', { ...input, allowWorkspaceExpansion: false });
  const focused = buildScopePayload('documents', { ...input, allowWorkspaceExpansion: true });

  assert.equal(strict.mode, 'strict');
  assert.equal(focused.mode, 'focused');
  assert.equal(focused.allow_workspace_expansion, true);
  assert.deepEqual(focused.document_ids, ['doc-1', 'doc-2']);
});

test('global scope drops the workspace constraint', () => {
  const scope = buildScopePayload('global', input);

  assert.equal(scope.mode, 'global');
  assert.deepEqual(scope.workspace_ids, []);
});

test('scope choice round trips for session restore', () => {
  for (const choice of ['smart', 'workspace', 'document', 'documents', 'global'] as const) {
    const scope = buildScopePayload(choice, input);
    assert.equal(scopeChoiceFromPayload(scope), choice);
  }
});

test('summary and requirements stay user facing', () => {
  assert.equal(scopeSummaryLabel('documents', 3), '指定资料 · 3 个文件');
  assert.equal(scopeSummaryLabel('smart', 0), '智能选择');
  assert.equal(scopeRequiresWorkspace('workspace'), true);
  assert.equal(scopeRequiresWorkspace('smart'), false);
  assert.equal(scopeRequiresDocuments('document'), true);
  assert.equal(scopeRequiresDocuments('global'), false);
});

test('scope notice explains expansion in plain language and stays silent otherwise', () => {
  assert.equal(scopeNoticeText(null), null);
  assert.equal(scopeNoticeText({ mode: 'smart', expanded: false, dropped: 0 }), null);
  assert.match(
    scopeNoticeText({ mode: 'smart', expanded: true, dropped: 0 }) || '',
    /全部知识库/,
  );
  assert.match(
    scopeNoticeText({ mode: 'global', expanded: true, dropped: 0 }) || '',
    /更大范围/,
  );
  assert.match(
    scopeNoticeText({ mode: 'smart', expanded: false, dropped: 2 }) || '',
    /已忽略 2 个/,
  );
});

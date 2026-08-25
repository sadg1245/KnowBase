import assert from 'node:assert/strict';
import test from 'node:test';

import * as documentScope from '../src/pages/documentScope.ts';

const { documentOptionLabel, resetDocumentScope } = documentScope;

test('资料范围列出所有文件并禁用尚不可用的文件', () => {
  const documents = [
    { id: 'ready', filename: 'ready.pdf', status: 'ready', created_at: '2026-08-21T10:00:00Z' },
    { id: 'processing', filename: 'processing.pdf', status: 'processing', created_at: '2026-08-21T10:00:00Z' },
    { id: 'failed', filename: 'failed.pdf', status: 'failed', created_at: '2026-08-21T10:00:00Z' },
  ];
  const optionBuilder = (documentScope as Record<string, unknown>).documentSelectionOption;

  assert.equal(typeof optionBuilder, 'function');
  const options = documents.map((document) => (optionBuilder as (value: typeof documents[number]) => { label: string; value: string; disabled: boolean })(document));
  assert.deepEqual(options.map((option) => option.value), ['ready', 'processing', 'failed']);
  assert.deepEqual(options.map((option) => option.disabled), [false, true, true]);
  assert.match(options[0].label, /已解析/);
  assert.match(options[1].label, /解析中/);
  assert.match(options[2].label, /解析失败/);
});

test('切换知识库时恢复为全部文件', () => {
  assert.deepEqual(resetDocumentScope(), []);
});

test('恢复历史会话时保留会话限定的文件范围', () => {
  const resolver = (documentScope as Record<string, unknown>).resolveDocumentScopeOnWorkspaceLoad;

  assert.equal(typeof resolver, 'function');
  const resolve = resolver as (pending?: string[]) => string[];
  assert.deepEqual(resolve(['document-a', 'document-b']), ['document-a', 'document-b']);
  assert.deepEqual(resolve(), []);
});

test('同名文件使用导入时间加以区分', () => {
  const first = documentOptionLabel({ filename: '报告.pdf', created_at: '2026-08-21T10:00:00Z' });
  const second = documentOptionLabel({ filename: '报告.pdf', created_at: '2026-08-21T11:00:00Z' });

  assert.match(first, /^报告\.pdf · /);
  assert.notEqual(first, second);
});

test('AI 学习页只有一个知识库时自动选中', () => {
  const resolver = (documentScope as Record<string, unknown>).resolveWorkspaceSelection;

  assert.equal(typeof resolver, 'function');
  const resolve = resolver as (items: { id: string }[], current?: string) => string | undefined;
  assert.equal(resolve([{ id: 'only-workspace' }]), 'only-workspace');
  assert.equal(resolve([{ id: 'first' }, { id: 'second' }]), undefined);
  assert.equal(resolve([{ id: 'first' }, { id: 'second' }], 'second'), 'second');
  assert.equal(resolve([{ id: 'first' }], 'missing'), 'first');
});

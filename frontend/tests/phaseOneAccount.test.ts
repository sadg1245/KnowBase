import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveAuthScreen } from '../src/features/account/authScreen.ts';
import { workspaceCardViewModel } from '../src/pages/workspaceCard.ts';
import type { Workspace } from '../src/services/api.ts';

const status = (configured: boolean, setupRequired: boolean) => ({
  configured,
  setup_required: setupRequired,
  login_required: true,
});

test('未建号时进入首次建号，已建号时进入登录', () => {
  assert.equal(resolveAuthScreen(status(false, true), false), 'setup');
  assert.equal(resolveAuthScreen(status(true, false), false), 'login');
});

test('已有令牌时直接进入应用，认证状态不可用时按登录处理', () => {
  assert.equal(resolveAuthScreen(status(true, false), true), 'app');
  assert.equal(resolveAuthScreen(status(false, true), true), 'app');
  assert.equal(resolveAuthScreen(null, false), 'login');
});

test('知识库卡片展示封面、领域、学习状态与真实统计', () => {
  const workspace = {
    id: 'ws', name: '线性代数', description: '', document_count: 3, created_at: '',
    domain: '数学', learning_status: 'learning', knowledge_point_count: 7,
    learning_progress: 62.4, last_studied_at: '2026-09-16T08:00:00Z',
    cover_url: 'https://example.com/cover.png',
  } as Workspace;

  const card = workspaceCardViewModel(workspace);
  assert.equal(card.domainLabel, '数学');
  assert.equal(card.statusLabel, '学习中');
  assert.equal(card.statsLabel, '3 份资料 · 7 个知识点');
  assert.equal(card.progressPercent, 62);
  assert.equal(card.coverUrl, 'https://example.com/cover.png');
  assert.equal(card.lastStudiedLabel, '2026-09-16');
});

test('空统计显示为 0、未分类与未开始', () => {
  const workspace = {
    id: 'ws', name: '空', description: '', document_count: 0, created_at: '',
  } as Workspace;

  const card = workspaceCardViewModel(workspace);
  assert.equal(card.domainLabel, '未分类');
  assert.equal(card.statusLabel, '未开始');
  assert.equal(card.statsLabel, '0 份资料 · 0 个知识点');
  assert.equal(card.progressPercent, 0);
  assert.equal(card.coverUrl, '');
  assert.equal(card.lastStudiedLabel, null);
});

test('进度百分比被限制在 0-100 之间', () => {
  const base = { id: 'ws', name: 'x', description: '', document_count: 0, created_at: '' } as Workspace;
  assert.equal(workspaceCardViewModel({ ...base, learning_progress: 130 }).progressPercent, 100);
  assert.equal(workspaceCardViewModel({ ...base, learning_progress: -5 }).progressPercent, 0);
});

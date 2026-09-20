import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  buildFeishuSettingsPayload,
  FeishuBotCard,
  feishuSourceLabel,
  feishuStatusLabel,
} from '../src/components/settings/FeishuBotCard';
import type { FeishuSettings } from '../src/services/api';


const settings = (overrides: Partial<FeishuSettings> = {}): FeishuSettings => ({
  app_id: 'cli_demo123',
  app_secret_masked: 'supe****alue',
  configured: true,
  source: 'settings',
  bot: { state: 'connected', detail: null, app_id: 'cli_demo123', updated_at: '2026-09-20T08:00:00Z', stale: false },
  ...overrides,
});

test('状态标签把每种机器人状态翻译成人话，过期状态不算已连接', () => {
  assert.deepEqual(feishuStatusLabel(settings().bot), { text: '机器人已连接', color: 'green' });
  assert.deepEqual(
    feishuStatusLabel({ ...settings().bot, state: 'pending' }),
    { text: '等待填写凭证', color: 'orange' },
  );
  assert.deepEqual(
    feishuStatusLabel({ ...settings().bot, state: 'restart_required' }),
    { text: '需要重启机器人', color: 'gold' },
  );
  assert.deepEqual(
    feishuStatusLabel({ ...settings().bot, state: 'error' }),
    { text: '机器人连接失败', color: 'red' },
  );
  assert.deepEqual(
    feishuStatusLabel({ ...settings().bot, stale: true }),
    { text: '机器人状态未更新', color: 'default' },
  );
  assert.deepEqual(feishuStatusLabel(null), { text: '机器人状态未知', color: 'default' });
});

test('保存载荷只带上用户真正填写的字段，留空表示不改', () => {
  assert.deepEqual(buildFeishuSettingsPayload({ app_id: ' cli_new ' }), { app_id: 'cli_new' });
  assert.deepEqual(
    buildFeishuSettingsPayload({ app_id: '', app_secret: '  secret  ' }),
    { app_secret: 'secret' },
  );
  assert.deepEqual(buildFeishuSettingsPayload({}), {});
});

test('凭据来源有明确文案', () => {
  assert.equal(feishuSourceLabel(settings()), '凭据来自本页设置');
  assert.equal(feishuSourceLabel(settings({ source: 'env' })), '凭据来自 .env 文件');
  assert.equal(feishuSourceLabel(settings({ configured: false })), '还没有配置');
  assert.equal(feishuSourceLabel(null), '还没有配置');
});

test('卡片给出状态、来源与三步接入指引', () => {
  const html = renderToStaticMarkup(<FeishuBotCard
    settings={settings()}
    onSave={() => undefined}
    onClear={() => undefined}
  />);

  assert.match(html, /飞书机器人/);
  assert.match(html, /机器人已连接/);
  assert.match(html, /凭据来自本页设置/);
  assert.match(html, /App Secret：supe\*\*\*\*alue（已保存，留空表示不改）/);
  assert.match(html, /im\.message\.receive_v1/);
  assert.match(html, /保存飞书配置/);
  assert.match(html, /清除配置/);
});

test('未配置时不显示清除按钮，并提示等待填写凭证', () => {
  const html = renderToStaticMarkup(<FeishuBotCard
    settings={settings({ app_id: null, app_secret_masked: null, configured: false, source: 'none', bot: { state: 'pending', detail: '设置页里还没有填写飞书 App ID / App Secret', stale: false } })}
    onSave={() => undefined}
    onClear={() => undefined}
  />);

  assert.match(html, /等待填写凭证/);
  assert.match(html, /还没有配置/);
  assert.match(html, /设置页里还没有填写飞书 App ID \/ App Secret/);
  assert.match(html, /disabled/);
});

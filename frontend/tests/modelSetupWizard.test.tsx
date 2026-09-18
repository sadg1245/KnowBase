import React from 'react';
import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';

import { ModelSetupWizard } from '../src/features/account/ModelSetupWizard.tsx';
import { defaultModelFor, providerNeedsKey, PROVIDERS } from '../src/features/account/llmProviders.ts';
import {
  isWizardDismissed, rememberWizardDismissed, shouldShowModelWizard, WIZARD_DISMISS_KEY,
} from '../src/features/account/setupWizard.ts';

test('刚建号一定引导一次，之后只在模型没配好时引导', () => {
  assert.equal(
    shouldShowModelWizard({ freshAccount: true, configured: true, dismissed: true }),
    true,
  );
  assert.equal(
    shouldShowModelWizard({ freshAccount: false, configured: false, dismissed: false }),
    true,
  );
  assert.equal(
    shouldShowModelWizard({ freshAccount: false, configured: true, dismissed: false }),
    false,
  );
});

test('用户选择稍后配置后不再打扰，接口失败时也不打扰', () => {
  assert.equal(
    shouldShowModelWizard({ freshAccount: false, configured: false, dismissed: true }),
    false,
  );
  assert.equal(
    shouldShowModelWizard({ freshAccount: false, configured: null, dismissed: false }),
    false,
  );
});

test('稍后配置的标记写在本地存储里，隐私模式失败也不抛错', () => {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value); },
  };
  assert.equal(isWizardDismissed(storage), false);
  rememberWizardDismissed(storage);
  assert.equal(store.get(WIZARD_DISMISS_KEY), '1');
  assert.equal(isWizardDismissed(storage), true);
  assert.equal(isWizardDismissed(null), false);
  rememberWizardDismissed(null);
  assert.equal(isWizardDismissed({ getItem: () => { throw new Error('blocked'); } }), false);
});

test('每个提供商都有默认模型，只有 Ollama 不需要 API Key', () => {
  for (const provider of PROVIDERS.map(option => option.value)) {
    assert.ok(defaultModelFor(provider), `${provider} 缺少默认模型`);
  }
  assert.equal(providerNeedsKey('deepseek'), true);
  assert.equal(providerNeedsKey('ollama'), false);
});

test('向导用用户能看懂的话说明 Key 只保存在本机，并提供跳过入口', () => {
  const html = renderToStaticMarkup(<ModelSetupWizard finish={() => undefined} />);
  assert.match(html, /配置你的 AI/);
  assert.match(html, /只保存在这台设备上/);
  assert.match(html, /API Key/);
  assert.match(html, /稍后配置/);
  assert.match(html, /保存并开始/);
});

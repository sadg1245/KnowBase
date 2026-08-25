import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const css = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8');

test('减少动态效果时仍保留极短时长，让消息退出事件能完成', () => {
  const reducedMotionBlock = css.match(
    /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([^}]|\}(?!\s*\}))*\}/,
  )?.[0] ?? '';

  assert.match(reducedMotionBlock, /animation-duration:\s*\.01ms\s*!important/);
  assert.match(reducedMotionBlock, /transition-duration:\s*\.01ms\s*!important/);
  assert.doesNotMatch(reducedMotionBlock, /animation:\s*none\s*!important/);
  assert.doesNotMatch(reducedMotionBlock, /transition:\s*none\s*!important/);
});

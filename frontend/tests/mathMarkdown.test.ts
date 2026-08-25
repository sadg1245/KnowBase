import assert from 'node:assert/strict';
import test from 'node:test';

import { normalizeMathDelimiters } from '../src/features/learning/mathMarkdown.ts';


test('将模型输出的反斜杠公式分隔符转换为 Markdown 数学语法', () => {
  const source = [
    '权重为 \\(w^{(1)}_{12}\\)。',
    '',
    '\\[',
    'y = wx + b',
    '\\]',
  ].join('\n');

  assert.equal(
    normalizeMathDelimiters(source),
    ['权重为 $w^{(1)}_{12}$。', '', '$$', 'y = wx + b', '$$'].join('\n'),
  );
});

test('不转换行内代码和围栏代码块中的公式样例', () => {
  const source = [
    '正文 \\(x + 1\\)，代码 `\\(x + 1\\)`。',
    '',
    '```text',
    '\\[x + 1\\]',
    '```',
  ].join('\n');

  assert.equal(
    normalizeMathDelimiters(source),
    ['正文 $x + 1$，代码 `\\(x + 1\\)`。', '', '```text', '\\[x + 1\\]', '```'].join('\n'),
  );
});

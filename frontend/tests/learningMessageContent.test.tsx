import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { LearningMessageContent } from '../src/components/learning/LearningMessageContent.tsx';


test('把 AI 回答中的行内和块级 LaTeX 渲染为 KaTeX', () => {
  const html = renderToStaticMarkup(
    <LearningMessageContent content={'权重为 \\(w^{(1)}_{12}\\)。\n\n\\[y = wx + b\\]'} />,
  );

  assert.match(html, /class="katex"/);
  assert.match(html, /class="katex-display"/);
  assert.doesNotMatch(html, /\\\(|\\\)|\\\[|\\\]/);
});

test('继续渲染回答中的 Markdown，同时保留代码中的 LaTeX 原文', () => {
  const html = renderToStaticMarkup(
    <LearningMessageContent content={'**重点**\n\n`\\(literal\\)`'} />,
  );

  assert.match(html, /<strong>重点<\/strong>/);
  assert.match(html, /<code>\\\(literal\\\)<\/code>/);
});

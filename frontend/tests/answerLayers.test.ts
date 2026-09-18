import assert from 'node:assert/strict';
import test from 'node:test';

import { answerPolicyLabel, layerNotice, splitAnswerSections } from '../src/features/learning/answerLayers';

test('answer sections are split on the three tutor headings', () => {
  const sections = splitAnswerSections([
    '## 来自私人资料',
    '向量检索用余弦相似度。[资料1]',
    '',
    '## AI 补充（模型记忆）',
    '这是模型通用知识。',
  ].join('\n'));

  assert.deepEqual(sections.map(section => section.key), ['sources', 'model']);
  assert.equal(sections[0].title, '来自私人资料');
  assert.match(sections[1].body, /模型通用知识/);
});

test('unstructured answers stay in one section', () => {
  const sections = splitAnswerSections('没有标题的一段回答。');

  assert.deepEqual(sections, [{ key: 'mixed', title: undefined, body: '没有标题的一段回答。' }]);
});

test('model sections are labelled as not belonging to the learner', () => {
  assert.match(layerNotice('model') ?? '', /不是你的资料/);
  assert.equal(layerNotice('sources'), undefined);
});

test('answer policy labels describe retrieval outcome', () => {
  assert.equal(answerPolicyLabel('supported'), '资料命中');
  assert.equal(answerPolicyLabel('model_only'), '仅模型补充');
  assert.equal(answerPolicyLabel('insufficient'), '资料不足，已用模型补充');
  assert.equal(answerPolicyLabel(undefined), '尚未检索');
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeDocumentCardSelection } from '../src/pages/documentCardSelection';

test('normalizes a same-chunk parsed-text selection', () => {
  assert.deepEqual(normalizeDocumentCardSelection({
    text: '  遗忘\n曲线会下降  ',
    startChunkId: 'chunk-1',
    endChunkId: 'chunk-1',
    page: 3,
    heading: '长期记忆',
  }), {
    excerpt: '遗忘 曲线会下降',
    chunkId: 'chunk-1',
    page: 3,
    heading: '长期记忆',
  });
});

test('rejects empty and cross-chunk selections', () => {
  assert.equal(normalizeDocumentCardSelection({ text: ' ', startChunkId: 'a', endChunkId: 'a' }), null);
  assert.equal(normalizeDocumentCardSelection({ text: 'text', startChunkId: 'a', endChunkId: 'b' }), null);
  assert.equal(normalizeDocumentCardSelection({ text: 'text', startChunkId: '', endChunkId: '' }), null);
});


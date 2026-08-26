import assert from 'node:assert/strict';
import test from 'node:test';
import { linkifySourceCitations, sourceDetailTarget } from '../src/features/learning/sourceNavigation';

test('linkifies citations outside inline and fenced code', () => {
  const input = '结论[资料1]\n\n`示例[资料1]`\n\n```txt\n[资料1]\n```';
  const output = linkifySourceCitations(input, 1);
  assert.match(output, /knowbase-source:\/\/1/);
  assert.match(output, /`示例\[资料1\]`/);
  assert.match(output, /```txt\n\[资料1\]\n```/);
});

test('builds exact source target', () => {
  assert.equal(sourceDetailTarget('ws', { filename: 'book.pdf', page_number: 8, content: '', score: 1, document_id: 'doc', chunk_id: 'doc_chunk_3' }), '/knowledge/ws/documents/doc?chunk=doc_chunk_3&page=8');
});


import assert from 'node:assert/strict';
import test from 'node:test';
import { buildOutline, pdfPageFragment, resolveSelectedChunk } from '../src/pages/documentDetailState';
import type { DocumentSection } from '../src/services/api';

const items: DocumentSection[] = [
  { chunk_id: 'doc_chunk_1', chunk_index: 0, page_num: 1, heading: 'Intro', section_path: ['Intro'], content: 'a' },
  { chunk_id: 'doc_chunk_2', chunk_index: 1, page_num: 8, heading: 'Chapter', section_path: ['Chapter'], content: 'b' },
  { chunk_id: 'doc_chunk_3', chunk_index: 2, page_num: 8, heading: 'Chapter', section_path: ['Chapter'], content: 'c' },
];

test('chunk query parameter has priority', () => {
  assert.equal(resolveSelectedChunk(items, 'doc_chunk_2', 1)?.chunk_id, 'doc_chunk_2');
});

test('falls back to page and builds a PDF fragment', () => {
  assert.equal(resolveSelectedChunk(items, undefined, 8)?.page_num, 8);
  assert.equal(pdfPageFragment(8), '#page=8');
  assert.equal(pdfPageFragment(0), '');
});

test('outline keeps source order and removes duplicate locations', () => {
  assert.deepEqual(buildOutline(items).map(item => item.chunk_id), ['doc_chunk_1', 'doc_chunk_2']);
});


import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { RetrievalDiagnosticsPanel } from '../src/components/learning/RetrievalDiagnostics';
import {
  evidenceDiagnosticLines, hitRows, runSummary,
} from '../src/features/learning/retrievalDiagnostics';

const detail = {
  run: {
    id: 'run-1', query: '条件概率是什么', scope_mode: 'smart', evidence_status: 'limited',
    top_score: 0.51, vector_succeeded: true, keyword_succeeded: false,
    degradation_reason: '关键词检索不可用', expanded_scope: true, expansion_rounds: 1,
  },
  hits: [
    {
      chunk_id: 'doc_chunk_1', source_file: 'notes.md', page_num: 3, heading: '1.1 定义',
      vector_rank: 1, keyword_rank: null, vector_score: 0.82, keyword_score: 0,
      fusion_score: 0.5, rerank_score: 0.51, profile_bonus: 0.1,
      vector_kinds: ['content', 'summary'], final_rank: 1,
    },
    {
      chunk_id: 'doc_chunk_2', source_file: 'exam.pdf', page_num: 9, heading: null,
      vector_rank: 2, keyword_rank: 1, vector_score: 0.4, keyword_score: 0.3,
      fusion_score: 0.3, rerank_score: 0.35, profile_bonus: 0,
      vector_kinds: ['content'], final_rank: 2,
    },
  ],
} as any;

test('diagnostic lines only surface optional keys that are present', () => {
  const lines = evidenceDiagnosticLines({
    status: 'limited',
    queryIntent: 'concept',
    degradationReason: '关键词检索不可用',
    rerankDegraded: 'reranker_timeout',
    indexStale: true,
    indexStaleReasons: ['ws-1:index_stale:embedding_dimension'],
    contextNotes: ['shared_parent:doc_parent_0', 'duplicate_chunk:c1'],
  });

  const labels = lines.map(line => line.label);
  assert.deepEqual(labels, [
    '证据状态', '查询意图', '检索降级', '重排降级', '索引需要重建', '上下文处理', '上下文处理',
  ]);
  assert.equal(lines[0].tone, 'info');
  assert.equal(lines[4].value, 'ws-1:index_stale:embedding_dimension');
  assert.deepEqual(evidenceDiagnosticLines(null), []);
  assert.deepEqual(evidenceDiagnosticLines({ status: 'supported' }).map(line => line.tone), ['ok']);
});

test('hit rows expose component scores, kinds and profile bonus', () => {
  const rows = hitRows(detail);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].chunkId, 'doc_chunk_1');
  assert.match(rows[0].source, /第 3 页/);
  assert.equal(rows[0].rank, 'V1 / K- → #1');
  assert.match(rows[0].scores, /融合 0.500 · 重排 0.510/);
  assert.equal(rows[0].kinds, 'content+summary');
  assert.equal(rows[0].bonus, '+0.100');
  assert.equal(rows[1].bonus, '0');
  assert.deepEqual(hitRows(null), []);
});

test('run summary reports scope, evidence and degradation', () => {
  const summary = runSummary(detail) || '';
  assert.match(summary, /范围 smart/);
  assert.match(summary, /证据 limited/);
  assert.match(summary, /已扩展 1 轮/);
  assert.match(summary, /关键词不可用/);
  assert.equal(runSummary(null), null);
});

test('panel renders diagnostics, hits and empty state', () => {
  const html = renderToStaticMarkup(<RetrievalDiagnosticsPanel
    detail={detail}
    evidence={{ status: 'limited', indexStale: true, indexStaleReasons: ['dimension'] }}
    onReload={() => undefined}
  />);
  assert.match(html, /索引需要重建/);
  assert.match(html, /doc_chunk_1/);
  assert.match(html, /画像 \+0.100/);
  assert.match(html, /刷新/);

  const empty = renderToStaticMarkup(<RetrievalDiagnosticsPanel
    detail={{ run: detail.run, hits: [] } as any}
    evidence={null}
  />);
  assert.match(empty, /这次检索没有保留候选/);

  const failed = renderToStaticMarkup(<RetrievalDiagnosticsPanel
    detail={null}
    error="boom"
  />);
  assert.match(failed, /检索详情暂时取不到/);
});

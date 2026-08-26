import React from 'react';
import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { StructuredLearningPanel } from '../src/pages/DocumentDetail';
import { KnowledgeDocumentList } from '../src/components/knowledge/KnowledgeDocumentList';
import { KnowledgeOverview } from '../src/components/knowledge/KnowledgeOverview';
import { KnowledgePointManager } from '../src/components/knowledge/KnowledgePointManager';
import type { Document, KnowledgeBaseDetail, KnowledgePoint } from '../src/services/api';

const documentFixture = {
  id: 'doc', workspace_id: 'ws', filename: 'book.pdf', file_type: '.pdf', file_size: 10,
  chunk_count: 2, status: 'ready', learning_status: 'ready', tags: ['AI'],
  chapter_summaries: [{ title: '第一章', summary: '摘要' }], core_concepts: ['概念'],
  important_terms: ['术语'], common_mistakes: ['易错'], prerequisites: ['前置'],
  learning_order: ['第一步'], review_points: ['复习'], created_at: '', updated_at: '',
} as Document;

test('structured learning panel renders every learning category', () => {
  const html = renderToStaticMarkup(<StructuredLearningPanel document={documentFixture} />);
  for (const label of ['章节摘要', '重要术语', '易错点', '前置知识', '推荐学习顺序', '复习知识点']) assert.match(html, new RegExp(label));
});

test('knowledge detail components render statuses, activity, recommendation and controls', () => {
  const point = { id: 'p', workspace_id: 'ws', title: 'Concept', summary: 'S', explanation: 'E', importance: 5, difficulty: 3, mastery: 1, tags: ['A'], is_key: true, mastery_status: 'mastered', created_at: '' } as KnowledgePoint;
  const detail = { id: 'ws', name: 'KB', description: '', document_count: 1, created_at: '', progress: 50, card_count: 1, quiz_count: 1, documents: [{ ...documentFixture, error_message: 'failure reason', outline_items: [{ chunk_id: 'doc_chunk_0', section_path: ['第一章'], page_num: 1 }] }], knowledge_points: [point], recent_activities: [{ id: 'a', type: 'read', title: 'Recent study', duration_seconds: 10, created_at: new Date().toISOString() }], recommendations: [{ type: 'continue_chat', title: 'Continue learning' }] } as KnowledgeBaseDetail;
  const overview = renderToStaticMarkup(<KnowledgeOverview detail={detail} onRecommendation={() => undefined} onStart={() => undefined} />);
  assert.match(overview, /Recent study/); assert.match(overview, /Continue learning/); assert.match(overview, /第一章/);
  const documents = renderToStaticMarkup(<KnowledgeDocumentList documents={detail.documents} onOpen={() => undefined} onReprocess={() => undefined} onRegenerate={() => undefined} onDelete={() => undefined} />);
  assert.match(documents, /failure reason/); assert.match(documents, /重新解析/); assert.match(documents, /学习内容/);
  const points = renderToStaticMarkup(<KnowledgePointManager points={[point]} onUpdate={async () => undefined} onDelete={() => undefined} onMerge={async () => undefined} onCard={async () => undefined} onQuiz={async () => undefined} />);
  for (const pattern of [/重点/, /已掌握/, /编\s*辑/, /删\s*除/, /生成卡片/, /生成练习/]) assert.match(points, pattern);
});

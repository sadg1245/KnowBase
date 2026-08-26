import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Alert, App, Button, Card, Empty, Form, Input, Modal, Space, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Document,
  DocumentSection,
  getDocument,
  getDocumentObjectUrl,
  getDocumentSections,
  regenerateDocumentLearning,
  reprocessDocument,
  updateDocument,
} from '../services/api';
import { buildOutline, pdfPageFragment, resolveSelectedChunk } from './documentDetailState';

const { Title, Paragraph, Text } = Typography;

const textOf = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object') {
    const row = value as Record<string, unknown>;
    return [row.title, row.term, row.name, row.summary, row.explanation, row.description]
      .filter(item => typeof item === 'string').join('：') || JSON.stringify(value);
  }
  return String(value ?? '');
};

const LearningList = ({ title, values }: { title: string; values: unknown[] }) => <section className="learning-block">
  <Title level={4}>{title}</Title>
  {values.length ? <ul>{values.map((value, index) => <li key={`${title}-${index}`}>{textOf(value)}</li>)}</ul> : <Text type="secondary">暂无内容</Text>}
</section>;

export const StructuredLearningPanel = ({ document }: { document: Document }) => <div className="structured-learning-panel">
  <Title level={3}>结构化学习内容</Title>
  <LearningList title="章节摘要" values={document.chapter_summaries || []} />
  <LearningList title="核心概念" values={document.core_concepts || []} />
  <LearningList title="重要术语" values={document.important_terms || []} />
  <LearningList title="易错点" values={document.common_mistakes || []} />
  <LearningList title="前置知识" values={document.prerequisites || []} />
  <LearningList title="推荐学习顺序" values={document.learning_order || []} />
  <LearningList title="复习知识点" values={document.review_points || []} />
</div>;

const DocumentDetail: React.FC = () => {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { workspaceId, documentId } = useParams<{ workspaceId: string; documentId: string }>();
  const [params, setParams] = useSearchParams();
  const [document, setDocument] = useState<Document | null>(null);
  const [sections, setSections] = useState<DocumentSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string>();
  const [form] = Form.useForm();
  const selectedRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (quiet = false) => {
    if (!documentId) return;
    if (!quiet) setLoading(true);
    try {
      const [nextDocument, response] = await Promise.all([getDocument(documentId), getDocumentSections(documentId)]);
      setDocument(nextDocument);
      setSections(response.items);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '文档详情加载失败');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [documentId, message]);

  useEffect(() => { void load(); }, [load]);
  const active = document && (['pending', 'processing'].includes(document.status) || ['queued', 'generating'].includes(document.learning_status));
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(true), 2500);
    return () => window.clearInterval(timer);
  }, [active, load]);

  const selected = useMemo(() => resolveSelectedChunk(
    sections,
    params.get('chunk'),
    Number(params.get('page')) || undefined,
  ), [params, sections]);
  useEffect(() => selectedRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), [selected?.chunk_id]);

  useEffect(() => {
    if (!document || document.file_type !== '.pdf') { setBlobUrl(undefined); return; }
    let current: string | undefined;
    getDocumentObjectUrl(document.id).then(url => { current = url; setBlobUrl(url); }).catch(() => message.error('PDF 原文加载失败'));
    return () => { if (current) URL.revokeObjectURL(current); };
  }, [document?.id, document?.file_type, message]);

  const choose = (section: DocumentSection) => setParams({ chunk: section.chunk_id, ...(section.page_num ? { page: String(section.page_num) } : {}) });
  const run = async (kind: 'parse' | 'learn') => {
    if (!document) return;
    setBusy(true);
    try {
      const next = kind === 'parse' ? await reprocessDocument(document.id) : await regenerateDocumentLearning(document.id);
      setDocument(next);
      message.success(kind === 'parse' ? '已重新提交解析' : '已重新提交学习内容生成');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '操作失败');
    } finally { setBusy(false); }
  };

  if (loading) return <Spin size="large" />;
  if (!document) return <Empty description="文档不存在" />;
  const outline = buildOutline(sections);

  return <div className="document-detail-page">
    <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/knowledge/${workspaceId}`)}>返回知识库</Button>
    <div className="document-detail-header">
      <div><Title level={1} className="page-title">{document.filename}</Title><Space wrap>
        <Tag color={document.status === 'ready' ? 'success' : document.status === 'failed' ? 'error' : 'processing'}>解析：{document.status}</Tag>
        <Tag color={document.learning_status === 'ready' ? 'success' : document.learning_status === 'failed' ? 'error' : 'processing'}>学习内容：{document.learning_status}</Tag>
        {document.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}
      </Space></div>
      <Space wrap><Button icon={<EditOutlined />} onClick={() => { form.setFieldsValue({ filename: document.filename, tags: document.tags.join(', ') }); setEditOpen(true); }}>编辑</Button>
        <Button loading={busy} icon={<ReloadOutlined />} onClick={() => void run('parse')}>重新解析</Button>
        <Button loading={busy} type="primary" onClick={() => void run('learn')} disabled={document.status !== 'ready'}>重新生成学习内容</Button></Space>
    </div>
    {document.error_message && <Alert type="error" showIcon message="解析失败" description={document.error_message} />}
    {document.learning_error_message && <Alert type="error" showIcon message="学习内容生成失败" description={document.learning_error_message} />}
    {document.summary && <Card className="paper-card"><Title level={3}>文档摘要</Title><Paragraph>{document.summary}</Paragraph></Card>}

    <div className="document-detail-grid">
      <aside className="document-outline paper-card"><Title level={3}>章节目录</Title>{outline.length ? outline.map(item => <Button key={item.chunk_id} type={selected?.chunk_id === item.chunk_id ? 'primary' : 'text'} block onClick={() => choose(item)}>{item.section_path.join(' › ') || item.heading || `第 ${item.page_num ?? item.chunk_index + 1} 节`}</Button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无目录" />}</aside>
      <main className="document-source paper-card"><Title level={3}>原文预览</Title>
        {document.file_type === '.pdf' && blobUrl ? <iframe title={document.filename} src={`${blobUrl}${pdfPageFragment(selected?.page_num)}`} className="pdf-preview" /> :
          sections.length ? sections.map(item => <article id={`source-${item.chunk_id}`} ref={selected?.chunk_id === item.chunk_id ? selectedRef : undefined} key={item.chunk_id} className={`source-card ${selected?.chunk_id === item.chunk_id ? 'selected' : ''}`} onClick={() => choose(item)}><Space><Tag>{item.page_num ? `第 ${item.page_num} 页` : `片段 ${item.chunk_index + 1}`}</Tag>{item.heading && <Text strong>{item.heading}</Text>}</Space><Paragraph>{item.content}</Paragraph></article>) : <Empty description="暂无解析内容" />}
      </main>
      <aside className="document-learning paper-card"><StructuredLearningPanel document={document} /></aside>
    </div>

    <Modal title="编辑文档信息" open={editOpen} onCancel={() => setEditOpen(false)} onOk={() => form.submit()}>
      <Form form={form} layout="vertical" onFinish={async values => {
        const next = await updateDocument(document.id, { filename: values.filename, tags: String(values.tags || '').split(',') });
        setDocument(next); setEditOpen(false); message.success('文档信息已更新');
      }}><Form.Item name="filename" label="文档名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="tags" label="标签（逗号分隔）"><Input /></Form.Item></Form>
    </Modal>
  </div>;
};

export default DocumentDetail;


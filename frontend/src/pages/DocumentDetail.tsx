import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Alert, App, Button, Card, Empty, Form, Input, Modal, Space, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, BulbOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  CardDraft,
  createSelectionCard,
  Document,
  DocumentSection,
  getDocument,
  getDocumentObjectUrl,
  getDocumentSections,
  regenerateDocumentLearning,
  reprocessDocument,
  updateDocument,
  Workspace,
} from '../services/api';
import { buildOutline, pdfPageFragment, resolveSelectedChunk } from './documentDetailState';
import { CardEditorModal } from '../components/review/CardEditorModal';
import { DocumentCardSelection, normalizeDocumentCardSelection } from './documentCardSelection';
import { useActiveStudySession } from '../hooks/useActiveStudySession';

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
  const [cardBusy, setCardBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [cardEditorOpen, setCardEditorOpen] = useState(false);
  const [cardSelection, setCardSelection] = useState<DocumentCardSelection | null>(null);
  const [blobUrl, setBlobUrl] = useState<string>();
  const [form] = Form.useForm();
  const selectedRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<HTMLElement>(null);
  useActiveStudySession({
    contextType: 'document', contextId: document?.id, workspaceId,
    enabled: Boolean(document),
  });

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
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [selected?.chunk_id]);

  useEffect(() => {
    if (!document || document.file_type !== '.pdf') { setBlobUrl(undefined); return; }
    let current: string | undefined;
    getDocumentObjectUrl(document.id).then(url => { current = url; setBlobUrl(url); }).catch(() => message.error('PDF 原文加载失败'));
    return () => { if (current) URL.revokeObjectURL(current); };
  }, [document?.id, document?.file_type, message]);

  const choose = (section: DocumentSection) => setParams({ chunk: section.chunk_id, ...(section.page_num ? { page: String(section.page_num) } : {}) });
  const selectionInitialValues = useMemo<Partial<CardDraft>>(() => ({
    workspace_id: workspaceId,
    front: '',
    back: cardSelection?.excerpt || '',
    source_label: [document?.filename, cardSelection?.heading, cardSelection?.page ? `第 ${cardSelection.page} 页` : ''].filter(Boolean).join(' · '),
    difficulty: 2,
    tags: document?.tags || [],
  }), [cardSelection, document?.filename, document?.tags, workspaceId]);
  const workspaceOptions = useMemo<Workspace[]>(() => workspaceId ? [{
    id: workspaceId, name: '当前知识库', description: '', document_count: 1, created_at: '',
  }] : [], [workspaceId]);

  const captureSelection = (event: React.MouseEvent<HTMLElement>) => {
    if ((event.target as Element).closest('button')) return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) { setCardSelection(null); return; }
    const range = selection.getRangeAt(0);
    const closestSource = (node: Node): HTMLElement | null => {
      const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
      return element?.closest<HTMLElement>('article[data-chunk-id]') || null;
    };
    const start = closestSource(range.startContainer);
    const end = closestSource(range.endContainer);
    if (!start || !end || !sourceRef.current?.contains(start) || !sourceRef.current.contains(end)) { setCardSelection(null); return; }
    setCardSelection(normalizeDocumentCardSelection({
      text: selection.toString(),
      startChunkId: start.dataset.chunkId,
      endChunkId: end.dataset.chunkId,
      page: start.dataset.page ? Number(start.dataset.page) : undefined,
      heading: start.dataset.heading,
    }));
  };

  const saveSelectionCard = async (values: CardDraft) => {
    if (!cardSelection || !documentId || !workspaceId) return;
    setCardBusy(true);
    try {
      await createSelectionCard({
        ...values,
        workspace_id: workspaceId,
        document_id: documentId,
        source_excerpt: cardSelection.excerpt,
        source_page: cardSelection.page,
        source_heading: cardSelection.heading,
      });
      setCardEditorOpen(false);
      setCardSelection(null);
      window.getSelection()?.removeAllRanges();
      message.success('已从原文选段生成卡片');
    } catch (error: any) { message.error(error?.response?.data?.detail || '选段卡片创建失败'); }
    finally { setCardBusy(false); }
  };
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
        <Button icon={<BulbOutlined />} disabled={document.status !== 'ready'} onClick={() => navigate(`/learn?workspace=${workspaceId}&document_id=${documentId}&mode=simple`)}>用 AI 学习此文档</Button>
        <Button loading={busy} icon={<ReloadOutlined />} onClick={() => void run('parse')}>重新解析</Button>
        <Button loading={busy} type="primary" onClick={() => void run('learn')} disabled={document.status !== 'ready'}>重新生成学习内容</Button></Space>
    </div>
    {document.error_message && <Alert type="error" showIcon message="解析失败" description={document.error_message} />}
    {document.learning_error_message && document.learning_status !== 'partial' && <Alert type="error" showIcon message="学习内容生成失败" description={document.learning_error_message} />}
    {document.learning_status === 'partial' ? <Alert
      type="warning"
      showIcon
      message={`学习内容部分完成（${document.learning_coverage?.chapters_ready ?? 0}/${document.learning_coverage?.chapters_total ?? '?'} 章）`}
      description={document.learning_error_message || '缺失章节可点击"重新生成学习内容"补齐，已生成的章节不受影响。'}
    /> : null}
    {document.parse_degraded ? <Alert
      type="warning"
      showIcon
      message={document.parse_degraded === 'scanned_pdf' ? '该文件是扫描件，暂不参与检索' : '这份资料没有可提取的正文'}
      description={(document.parse_quality?.notes as string[] | undefined)?.join(' ') || '当前未做 OCR，检索与问答不会引用这份资料。'}
    /> : null}
    {document.enrichment_state && document.enrichment_state !== 'skipped' ? <Alert
      type={document.enrichment_state === 'failed' ? 'warning' : 'info'}
      showIcon
      message={{
        pending: '后台增强中：正在生成摘要与问题向量',
        partial: '后台增强部分完成，可重试缺失部分',
        ready: '后台增强完成：摘要与问题向量已加入检索',
        failed: '后台增强未成功，可点击下方"重新解析"或补跑富化',
      }[document.enrichment_state] || `后台增强状态：${document.enrichment_state}`}
      description={document.enrichment_progress?.chunks_total
        ? `已处理 ${document.enrichment_progress.chunks_ready ?? 0}/${document.enrichment_progress.chunks_total} 个片段`
          + (document.enrichment_progress.chunks_failed ? `，失败 ${document.enrichment_progress.chunks_failed} 个` : '')
        : undefined}
    /> : null}
    {document.summary && <Card className="paper-card"><Title level={3}>文档摘要</Title><Paragraph>{document.summary}</Paragraph></Card>}

    <div className="document-detail-grid">
      <aside className="document-outline paper-card"><Title level={3}>章节目录</Title>{outline.length ? outline.map(item => <Button key={item.chunk_id} type={selected?.chunk_id === item.chunk_id ? 'primary' : 'text'} block onClick={() => choose(item)}>{item.section_path.join(' › ') || item.heading || `第 ${item.page_num ?? item.chunk_index + 1} 节`}</Button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无目录" />}</aside>
      <main ref={sourceRef} className="document-source paper-card" onMouseUp={captureSelection}><div className="document-source-heading"><Title level={3}>原文预览</Title>{cardSelection && <Button type="primary" icon={<PlusOutlined />} onClick={() => setCardEditorOpen(true)}>从选段生成卡片</Button>}</div>
        {cardSelection && <div className="document-selection-hint">已选择：{cardSelection.excerpt}</div>}
        {document.file_type === '.pdf' && blobUrl ? <iframe title={document.filename} src={`${blobUrl}${pdfPageFragment(selected?.page_num)}`} className="pdf-preview" /> :
          sections.length ? sections.map(item => <article id={`source-${item.chunk_id}`} data-chunk-id={item.chunk_id} data-page={item.page_num ?? undefined} data-heading={item.heading ?? undefined} ref={selected?.chunk_id === item.chunk_id ? selectedRef : undefined} key={item.chunk_id} className={`source-card ${selected?.chunk_id === item.chunk_id ? 'selected' : ''}`} onClick={() => choose(item)}><Space><Tag>{item.page_num ? `第 ${item.page_num} 页` : `片段 ${item.chunk_index + 1}`}</Tag>{item.heading && <Text strong>{item.heading}</Text>}</Space><Paragraph>{item.content}</Paragraph></article>) : <Empty description="暂无解析内容" />}
      </main>
      <aside className="document-learning paper-card"><StructuredLearningPanel document={document} /></aside>
    </div>

    <Modal title="编辑文档信息" open={editOpen} onCancel={() => setEditOpen(false)} onOk={() => form.submit()}>
      <Form form={form} layout="vertical" onFinish={async values => {
        const next = await updateDocument(document.id, { filename: values.filename, tags: String(values.tags || '').split(',') });
        setDocument(next); setEditOpen(false); message.success('文档信息已更新');
      }}><Form.Item name="filename" label="文档名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="tags" label="标签（逗号分隔）"><Input /></Form.Item></Form>
    </Modal>
    <CardEditorModal
      open={cardEditorOpen}
      workspaces={workspaceOptions}
      initialValues={selectionInitialValues}
      sourceExcerpt={cardSelection?.excerpt}
      lockWorkspace
      submitting={cardBusy}
      onCancel={() => setCardEditorOpen(false)}
      onSubmit={saveSelectionCard}
    />
  </div>;
};

export default DocumentDetail;


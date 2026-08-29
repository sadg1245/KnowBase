import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { App, Button, Empty, Modal, Space, Spin, Tabs, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, PlayCircleOutlined } from '@ant-design/icons';
import {
  deleteDocument, deleteKnowledgePoint, getKnowledgeBaseDetail, KnowledgeBaseDetail,
  generateWorkspaceCards,
  knowledgePointToCard, knowledgePointToQuiz, mergeKnowledgePoints,
  regenerateDocumentLearning, reprocessDocument, updateKnowledgePoint,
} from '../services/api';
import { KnowledgeOverview } from '../components/knowledge/KnowledgeOverview';
import { KnowledgeDocumentList } from '../components/knowledge/KnowledgeDocumentList';
import { KnowledgePointManager } from '../components/knowledge/KnowledgePointManager';

const KnowledgeBase: React.FC = () => {
  const { message } = App.useApp();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<KnowledgeBaseDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (quiet = false) => {
    if (!id) return;
    if (!quiet) setLoading(true);
    try { setData(await getKnowledgeBaseDetail(id)); }
    catch (error: any) { message.error(error?.response?.data?.detail || '知识库加载失败'); }
    finally { if (!quiet) setLoading(false); }
  }, [id, message]);

  useEffect(() => { void load(); }, [load]);
  const active = useMemo(() => data?.documents.some(document =>
    ['pending', 'processing'].includes(document.status) || ['queued', 'generating'].includes(document.learning_status),
  ), [data?.documents]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(true), 2500);
    return () => window.clearInterval(timer);
  }, [active, load]);

  const action = async (operation: () => Promise<unknown>, success: string) => {
    try { await operation(); message.success(success); await load(true); }
    catch (error: any) { message.error(error?.response?.data?.detail || '操作失败'); }
  };

  const generateCards = async (pointIds: string[]) => {
    if (!id) return;
    try {
      const result = await generateWorkspaceCards(id, pointIds);
      message.success(`已生成 ${result.created_count} 张卡片`);
      await load(true);
    } catch (error: any) { message.error(error?.response?.data?.detail || '批量生成卡片失败'); }
  };

  if (loading) return <Spin size="large" />;
  if (!data) return <Empty description="没有找到这个知识库" />;
  const openDocument = (documentId: string) => navigate(`/knowledge/${data.id}/documents/${documentId}`);

  return <div>
    <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/knowledge')}>返回知识库</Button>
    <div className="document-detail-header"><div><Space><Tag color={data.accent_color}>{data.domain}</Tag><Typography.Text type="secondary">{data.documents.length} 份资料</Typography.Text></Space><Typography.Title className="page-title" level={1}>{data.name}</Typography.Title><Typography.Paragraph>{data.learning_goal || data.description || '设置一个清晰的学习目标。'}</Typography.Paragraph></div><Button type="primary" icon={<PlayCircleOutlined />} onClick={() => navigate(`/learn?workspace=${data.id}`)}>开始学习</Button></div>
    <Tabs size="large" items={[
      { key: 'overview', label: '学习概览', children: <KnowledgeOverview detail={data} onStart={() => navigate(`/learn?workspace=${data.id}`)} onRecommendation={recommendation => {
        if (recommendation.document_id && ['retry_document', 'retry_learning', 'generate_learning'].includes(recommendation.type)) openDocument(recommendation.document_id);
        else if (recommendation.type === 'continue_chat') navigate(`/learn?workspace=${data.id}`);
        else document.getElementById(`point-${recommendation.knowledge_point_id}`)?.scrollIntoView({ behavior: 'smooth' });
      }} /> },
      { key: 'documents', label: `文档 ${data.documents.length}`, children: <KnowledgeDocumentList documents={data.documents} onOpen={openDocument} onReprocess={docId => void action(() => reprocessDocument(docId), '已重新提交解析')} onRegenerate={docId => void action(() => regenerateDocumentLearning(docId), '已重新提交学习内容生成')} onDelete={docId => Modal.confirm({ title: '删除这份资料？', content: '相关切片和知识点也会删除。', onOk: () => action(() => deleteDocument(docId), '文档已删除') })} /> },
      { key: 'points', label: `知识点 ${data.knowledge_points.length}`, children: <KnowledgePointManager points={data.knowledge_points} onUpdate={(pointId, values) => action(() => updateKnowledgePoint(pointId, values), '知识点已更新')} onDelete={pointId => Modal.confirm({ title: '删除知识点？', onOk: () => action(() => deleteKnowledgePoint(pointId), '知识点已删除') })} onMerge={(target, sources) => action(() => mergeKnowledgePoints(target, sources), '知识点已合并')} onCard={pointId => action(() => knowledgePointToCard(pointId), '复习卡片已生成')} onQuiz={pointId => action(() => knowledgePointToQuiz(pointId), '练习已生成')} onGenerateCards={generateCards} /> },
    ]} />
  </div>;
};

export default KnowledgeBase;


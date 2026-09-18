import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { App, Button, Col, Empty, Form, Input, Modal, Progress, Row, Select, Space, Spin, Tabs, Tag, Typography, Upload } from 'antd';
import { ArrowLeftOutlined, EditOutlined, PlayCircleOutlined, UploadOutlined } from '@ant-design/icons';
import {
  deleteDocument, deleteKnowledgePoint, getKnowledgeBaseDetail, KnowledgeBaseDetail,
  generateWorkspaceCards, getLearningDomains,
  knowledgePointToCard, knowledgePointToQuiz, mergeKnowledgePoints,
  regenerateDocumentLearning, reprocessDocument, updateKnowledgePoint,
  clearWorkspaceCover, LearningDomain, LearningStatus, LEARNING_STATUS_LABELS,
  updateWorkspace, uploadWorkspaceCover,
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
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [domains, setDomains] = useState<LearningDomain[]>([]);
  const [coverUrl, setCoverUrl] = useState('');
  const [form] = Form.useForm();

  const load = useCallback(async (quiet = false) => {
    if (!id) return;
    if (!quiet) setLoading(true);
    try { setData(await getKnowledgeBaseDetail(id)); }
    catch (error: any) { message.error(error?.response?.data?.detail || '知识库加载失败'); }
    finally { if (!quiet) setLoading(false); }
  }, [id, message]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { getLearningDomains().then(setDomains).catch(() => setDomains([])); }, []);
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

  const openEditor = () => {
    if (!data) return;
    form.setFieldsValue({
      name: data.name, description: data.description || '', learning_goal: data.learning_goal || '',
      domain_id: data.domain_id || undefined, learning_status: data.learning_status || 'not_started',
      archived: Boolean(data.archived), accent_color: data.accent_color,
    });
    setCoverUrl(data.cover_url || '');
    setEditing(true);
  };

  const saveWorkspace = async () => {
    if (!data) return;
    let values;
    try { values = await form.validateFields(); } catch { return; }
    setSaving(true);
    try {
      await updateWorkspace(data.id, {
        ...values,
        domain_id: values.domain_id || null,
        cover_url: coverUrl || null,
        clear_cover: !coverUrl,
      });
      message.success('知识库已更新');
      setEditing(false);
      await load(true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spin size="large" />;
  if (!data) return <Empty description="没有找到这个知识库" />;
  const openDocument = (documentId: string) => navigate(`/knowledge/${data.id}/documents/${documentId}`);

  return <div>
    <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/knowledge')}>返回知识库</Button>
    <div className="document-detail-header"><div>{data.cover_url && <img src={data.cover_url} alt={`${data.name} 封面`} style={{ width: '100%', maxHeight: 180, objectFit: 'cover', borderRadius: 12, marginBottom: 16, display: 'block' }} />}<Space wrap><Tag color={data.accent_color}>{data.domain}</Tag><Tag bordered={false}>{LEARNING_STATUS_LABELS[(data.learning_status || 'not_started') as LearningStatus]}</Tag><Typography.Text type="secondary">{data.documents.length} 份资料 · {data.knowledge_points.length} 个知识点</Typography.Text></Space><Typography.Title className="page-title" level={1}>{data.name}</Typography.Title><Typography.Paragraph>{data.learning_goal || data.description || '设置一个清晰的学习目标。'}</Typography.Paragraph><Progress percent={data.learning_progress || data.progress || 0} size="small" style={{ maxWidth: 320 }} format={value => `掌握 ${value || 0}%`} /></div><Space direction="vertical" align="end"><Button icon={<EditOutlined />} onClick={openEditor}>编辑知识库</Button><Button type="primary" icon={<PlayCircleOutlined />} onClick={() => navigate(`/learn?workspace=${data.id}`)}>开始学习</Button></Space></div>
    <Tabs size="large" items={[
      { key: 'overview', label: '学习概览', children: <KnowledgeOverview detail={data} onStart={() => navigate(`/learn?workspace=${data.id}`)} onRecommendation={recommendation => {
        if (recommendation.document_id && ['retry_document', 'retry_learning', 'generate_learning'].includes(recommendation.type)) openDocument(recommendation.document_id);
        else if (recommendation.type === 'continue_chat') navigate(`/learn?workspace=${data.id}`);
        else document.getElementById(`point-${recommendation.knowledge_point_id}`)?.scrollIntoView({ behavior: 'smooth' });
      }} /> },
      { key: 'documents', label: `文档 ${data.documents.length}`, children: <KnowledgeDocumentList documents={data.documents} onOpen={openDocument} onReprocess={docId => void action(() => reprocessDocument(docId), '已重新提交解析')} onRegenerate={docId => void action(() => regenerateDocumentLearning(docId), '已重新提交学习内容生成')} onDelete={docId => Modal.confirm({ title: '删除这份资料？', content: '相关切片和知识点也会删除。', onOk: () => action(() => deleteDocument(docId), '文档已删除') })} /> },
      { key: 'points', label: `知识点 ${data.knowledge_points.length}`, children: <KnowledgePointManager points={data.knowledge_points} onUpdate={(pointId, values) => action(() => updateKnowledgePoint(pointId, values), '知识点已更新')} onDelete={pointId => Modal.confirm({ title: '删除知识点？', onOk: () => action(() => deleteKnowledgePoint(pointId), '知识点已删除') })} onMerge={(target, sources) => action(() => mergeKnowledgePoints(target, sources), '知识点已合并')} onCard={pointId => action(() => knowledgePointToCard(pointId), '复习卡片已生成')} onQuiz={pointId => action(() => knowledgePointToQuiz(pointId), '练习已生成')} onGenerateCards={generateCards} /> },
    ]} />
    <Modal title="编辑知识库" open={editing} onOk={saveWorkspace} confirmLoading={saving} onCancel={() => setEditing(false)} okText="保存" cancelText="取消" width={560}>
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item name="name" label="知识库名称" rules={[{ required: true, message: '请输入知识库名称' }]}><Input /></Form.Item>
        <Form.Item name="learning_goal" label="学习目标"><Input.TextArea rows={3} /></Form.Item>
        <Form.Item name="description" label="简短说明"><Input /></Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="domain_id" label="学习领域"><Select allowClear placeholder="未分类" options={domains.map(item => ({ label: item.name, value: item.id }))} /></Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="learning_status" label="学习状态"><Select options={(Object.keys(LEARNING_STATUS_LABELS) as LearningStatus[]).map(value => ({ label: LEARNING_STATUS_LABELS[value], value }))} /></Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item label="封面外链（https）"><Input value={coverUrl} placeholder="https://example.com/cover.png" onChange={event => setCoverUrl(event.target.value)} /></Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="本地上传封面">
              <Space wrap>
                <Upload accept="image/png,image/jpeg,image/webp,image/gif" showUploadList={false} beforeUpload={async file => {
                  try {
                    const updated = await uploadWorkspaceCover(data.id, file as File);
                    setCoverUrl(updated.cover_url || '');
                    message.success('封面已更新');
                    await load(true);
                  } catch (error: any) {
                    message.error(error?.response?.data?.detail || '封面上传失败');
                  }
                  return false;
                }}><Button icon={<UploadOutlined />}>上传封面</Button></Upload>
                <Button onClick={async () => {
                  try {
                    await clearWorkspaceCover(data.id);
                    setCoverUrl('');
                    message.success('封面已清除');
                    await load(true);
                  } catch { message.error('清除封面失败'); }
                }}>清除封面</Button>
              </Space>
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  </div>;
};

export default KnowledgeBase;


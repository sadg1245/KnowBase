import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App, Button, Col, Empty, Form, Input, Modal, Progress, Row, Select, Space, Tag, Typography } from 'antd';
import { ArrowRightOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  LearningDomain, LearningStatus, LEARNING_STATUS_LABELS, Workspace,
  createLearningDomain, createWorkspace, deleteWorkspace, getLearningDomains, getWorkspaces,
} from '../services/api';
import { workspaceCardViewModel } from './workspaceCard';

const { Title, Text } = Typography;
const colors = ['#167d8d', '#6e71a8', '#d9913b', '#3f8f6b', '#c45f72'];
const STATUS_COLORS: Record<LearningStatus, string> = {
  not_started: 'default',
  learning: 'processing',
  paused: 'warning',
  completed: 'success',
};

type WorkspaceDeletionConfirmation = {
  title: string;
  content: string;
  okText: string;
  cancelText: string;
  centered: boolean;
  okButtonProps: { danger: boolean };
  onOk: () => Promise<void>;
};

type WorkspaceDeletionActions = {
  confirm: (confirmation: WorkspaceDeletionConfirmation) => void;
  remove: (workspaceId: string) => Promise<void>;
  onSuccess: (workspaceName: string) => void;
  onError: (error: unknown) => void;
};

export const requestWorkspaceDeletion = (
  workspace: Pick<Workspace, 'id' | 'name'>,
  actions: WorkspaceDeletionActions,
) => {
  actions.confirm({
    title: `删除知识库“${workspace.name}”？`,
    content: '相关资料和学习记录将一起删除，此操作不可撤销。',
    okText: '确定删除',
    cancelText: '取消',
    centered: true,
    okButtonProps: { danger: true },
    onOk: async () => {
      try {
        await actions.remove(workspace.id);
        actions.onSuccess(workspace.name);
      } catch (error) {
        actions.onError(error);
        throw error;
      }
    },
  });
};

const Workspaces: React.FC = () => {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState<Workspace[]>([]);
  const [domains, setDomains] = useState<LearningDomain[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = () => {
    setLoading(true);
    getWorkspaces().then(setItems).catch(() => message.error('知识库没有加载成功')).finally(() => setLoading(false));
  };
  const loadDomains = () => { getLearningDomains().then(setDomains).catch(() => setDomains([])); };
  useEffect(() => { load(); loadDomains(); }, []);

  const createDomain = () => {
    let name = '';
    modal.confirm({
      title: '新建学习领域',
      content: <Input autoFocus placeholder="领域名称" onChange={event => { name = event.target.value; }} />,
      okText: '创建',
      cancelText: '取消',
      onOk: async () => {
        if (!name.trim()) { message.warning('请填写领域名称'); throw new Error('empty'); }
        try {
          await createLearningDomain({ name: name.trim() });
          message.success('学习领域已创建');
          loadDomains();
        } catch (error: any) {
          message.error(error?.response?.data?.detail || '创建学习领域失败');
          throw error;
        }
      },
    });
  };

  const create = async () => {
    let values;
    try { values = await form.validateFields(); } catch { return; }
    setSaving(true);
    try {
      await createWorkspace(values.name, values.description || '', {
        learning_goal: values.learning_goal,
        learning_status: values.learning_status,
        domain_id: values.domain_id || null,
        cover_url: values.cover_url || null,
        accent_color: values.accent_color,
      });
      message.success('知识库已创建');
      setOpen(false);
      form.resetFields();
      load();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '创建失败');
    } finally {
      setSaving(false);
    }
  };

  return <div>
    <Row align="bottom" justify="space-between" gutter={[16, 16]}>
      <Col>
        <div className="page-eyebrow">Library · 你的学习书架</div>
        <Title className="page-title" level={1}>我的知识库</Title>
        <p className="page-lead">按目标整理资料，而不是让文件堆在一起。每个知识库都是一段可以继续的学习旅程。</p>
      </Col>
      <Col><Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建知识库</Button></Col>
    </Row>
    {!loading && !items.length
      ? <div className="paper-card empty-guide" style={{ marginTop: 32 }}><Empty description="从一个真正想弄懂的主题开始" /><Button type="primary" onClick={() => setOpen(true)}>创建第一个知识库</Button></div>
      : <Row gutter={[18, 18]} style={{ marginTop: 32 }}>{items.filter(i => !i.archived).map((item, index) => {
        const card = workspaceCardViewModel(item);
        return <Col xs={24} md={12} xl={8} key={item.id}>
        <article className="paper-card lift" style={{ padding: 22, minHeight: 225, borderTop: `5px solid ${item.accent_color || colors[index % colors.length]}`, display: 'flex', flexDirection: 'column' }}>
          {card.coverUrl && <div style={{ margin: '-22px -22px 16px', height: 120, overflow: 'hidden' }}>
            <img src={card.coverUrl} alt={`${item.name} 封面`} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
          </div>}
          <Space style={{ justifyContent: 'space-between' }}>
            <Space size={6}>
              <Tag bordered={false}>{card.domainLabel}</Tag>
              <Tag bordered={false} color={STATUS_COLORS[card.status]}>{card.statusLabel}</Tag>
            </Space>
            <Button type="text" danger size="small" aria-label={`删除知识库 ${item.name}`} icon={<DeleteOutlined />} onClick={() => requestWorkspaceDeletion(item, { confirm: confirmation => { modal.confirm(confirmation); }, remove: deleteWorkspace, onSuccess: workspaceName => { message.success(`知识库“${workspaceName}”已删除`); load(); }, onError: () => message.error('删除失败，请稍后重试') })} />
          </Space>
          <Title level={3} style={{ margin: '16px 0 7px' }}>{item.name}</Title>
          <Text type="secondary" ellipsis={{ tooltip: item.learning_goal || item.description }}>{item.learning_goal || item.description || '还没有写下学习目标'}</Text>
          <div style={{ marginTop: 'auto', paddingTop: 18 }}>
            <Text type="secondary">{card.statsLabel}</Text>
            <Progress percent={card.progressPercent} size="small" format={value => `掌握 ${value || 0}%`} />
            {card.lastStudiedLabel && <Text type="secondary" style={{ fontSize: 12 }}>最近学习 {card.lastStudiedLabel}</Text>}
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button type="link" onClick={() => navigate(`/knowledge/${item.id}`)}>继续学习 <ArrowRightOutlined /></Button>
            </Space>
          </div>
        </article>
      </Col>;
      })}</Row>}
    <Modal title="新建一个学习主题" open={open} onOk={create} confirmLoading={saving} onCancel={() => setOpen(false)} okText="创建知识库" cancelText="取消" width={560}>
      <Form form={form} layout="vertical" initialValues={{ learning_status: 'not_started', accent_color: colors[0] }} style={{ marginTop: 20 }}>
        <Form.Item name="name" label="知识库名称" rules={[{ required: true, message: '写下你想学习的主题' }]}><Input size="large" placeholder="例如：系统学习 Python" /></Form.Item>
        <Form.Item name="learning_goal" label="我想达到什么目标"><Input.TextArea rows={3} placeholder="例如：能独立完成一个数据分析项目" /></Form.Item>
        <Form.Item name="description" label="简短说明"><Input placeholder="这组资料主要包含什么？" /></Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="domain_id" label="学习领域">
              <Space.Compact style={{ width: '100%' }}>
                <Select allowClear placeholder="未分类" options={domains.map(item => ({ label: item.name, value: item.id }))} />
                <Button onClick={createDomain}>新建</Button>
              </Space.Compact>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="learning_status" label="学习状态">
              <Select options={(Object.keys(LEARNING_STATUS_LABELS) as LearningStatus[]).map(value => ({ label: LEARNING_STATUS_LABELS[value], value }))} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="cover_url" label="封面外链（https）" rules={[{ pattern: /^https:\/\/.+/i, message: '封面外链必须以 https:// 开头' }]}>
              <Input placeholder="https://example.com/cover.png" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="accent_color" label="书脊颜色">
              <Select options={colors.map(c => ({ label: <Space><span style={{ width: 12, height: 12, borderRadius: 4, background: c, display: 'inline-block' }} />{c}</Space>, value: c }))} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  </div>;
};

export default Workspaces;

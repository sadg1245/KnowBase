import React, { useState } from 'react';
import { Button, Card, Checkbox, Form, Input, InputNumber, Modal, Progress, Space, Tag, Typography } from 'antd';
import type { KnowledgePoint } from '../../services/api';

export const KnowledgePointManager = ({ points, onUpdate, onDelete, onMerge, onCard, onQuiz, onGenerateCards }: {
  points: KnowledgePoint[];
  onUpdate: (id: string, values: Partial<KnowledgePoint>) => Promise<void>;
  onDelete: (id: string) => void;
  onMerge: (targetId: string, sourceIds: string[]) => Promise<void>;
  onCard: (id: string) => Promise<void>;
  onQuiz: (id: string) => Promise<void>;
  onGenerateCards: (ids: string[]) => Promise<void>;
}) => {
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<KnowledgePoint>();
  const [form] = Form.useForm();
  const toggle = (id: string, checked: boolean) => setSelected(current => checked ? [...current, id] : current.filter(value => value !== id));
  const merge = () => {
    if (selected.length < 2) return;
    Modal.confirm({ title: '合并知识点？', content: '将其他选中知识点合并到第一个知识点。', onOk: async () => { await onMerge(selected[0], selected.slice(1)); setSelected([]); } });
  };
  return <div>
    <Space wrap style={{ marginBottom: 12 }}>
      <Button type="primary" disabled={!points.length} onClick={() => void onGenerateCards(selected)}>批量生成卡片{selected.length ? `（已选 ${selected.length}）` : ''}</Button>
      <Button disabled={selected.length < 2} onClick={merge}>合并选中的知识点</Button>
    </Space>
    <Space direction="vertical" size={12} style={{ width: '100%' }}>{points.map(point => <Card key={point.id} className="paper-card" title={<Space><Checkbox checked={selected.includes(point.id)} onChange={event => toggle(point.id, event.target.checked)} /><Typography.Text strong>{point.title}</Typography.Text>{point.is_key && <Tag color="gold">重点</Tag>}{point.mastery_status === 'mastered' && <Tag color="success">已掌握</Tag>}</Space>}>
      <Typography.Paragraph>{point.explanation || point.summary}</Typography.Paragraph><Progress percent={Math.round(point.mastery * 100)} size="small" />
      <Space wrap>{point.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}</Space>
      <Space wrap style={{ marginTop: 12 }}><Button onClick={() => { setEditing(point); form.setFieldsValue({ ...point, tags: point.tags.join(', ') }); }}>编辑</Button><Button onClick={() => void onUpdate(point.id, { is_key: !point.is_key })}>{point.is_key ? '取消重点' : '标为重点'}</Button><Button onClick={() => void onUpdate(point.id, { mastery_status: 'mastered' })}>标记已掌握</Button><Button onClick={() => void onCard(point.id)}>生成卡片</Button><Button onClick={() => void onQuiz(point.id)}>生成练习</Button><Button danger onClick={() => onDelete(point.id)}>删除</Button></Space>
    </Card>)}</Space>
    <Modal title="编辑知识点" open={!!editing} onCancel={() => setEditing(undefined)} onOk={() => form.submit()}><Form form={form} layout="vertical" onFinish={async values => { if (!editing) return; await onUpdate(editing.id, { ...values, tags: String(values.tags || '').split(',').map((tag: string) => tag.trim()).filter(Boolean) }); setEditing(undefined); }}>
      <Form.Item name="title" label="标题" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="summary" label="简要解释"><Input.TextArea /></Form.Item><Form.Item name="explanation" label="详细解释"><Input.TextArea rows={4} /></Form.Item><Form.Item name="importance" label="重要程度"><InputNumber min={1} max={5} /></Form.Item><Form.Item name="difficulty" label="难度"><InputNumber min={1} max={5} /></Form.Item><Form.Item name="tags" label="标签"><Input /></Form.Item>
    </Form></Modal>
  </div>;
};


import React, { useEffect } from 'react';
import { Form, Input, InputNumber, Modal, Select } from 'antd';
import type { CardDraft, Flashcard, Workspace } from '../../services/api';

interface CardEditorModalProps {
  open: boolean;
  card?: Flashcard | null;
  workspaces: Workspace[];
  initialValues?: Partial<CardDraft>;
  sourceExcerpt?: string;
  lockWorkspace?: boolean;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (values: CardDraft) => Promise<void> | void;
}

interface EditorValues extends Omit<CardDraft, 'tags'> { tags?: string[] }

export const CardEditorModal: React.FC<CardEditorModalProps> = ({
  open, card, workspaces, initialValues, sourceExcerpt, lockWorkspace = false, submitting, onCancel, onSubmit,
}) => {
  const [form] = Form.useForm<EditorValues>();
  useEffect(() => {
    if (!open) return;
    form.setFieldsValue(card ? {
      workspace_id: card.workspace_id,
      front: card.front,
      back: card.back,
      source_label: card.source_label,
      tags: card.tags,
      difficulty: card.difficulty,
    } : {
      workspace_id: workspaces[0]?.id,
      front: '', back: '', source_label: '', tags: [], difficulty: 2,
      ...initialValues,
    });
  }, [card, form, initialValues, open, workspaces]);

  return <Modal
    title={card ? '编辑卡片' : sourceExcerpt ? '从选段生成卡片' : '新建卡片'}
    open={open}
    okText={card ? '保存修改' : '创建卡片'}
    cancelText="取消"
    confirmLoading={submitting}
    onCancel={onCancel}
    onOk={() => form.submit()}
    destroyOnHidden
  >
    <Form form={form} layout="vertical" onFinish={values => onSubmit({ ...values, tags: values.tags || [] })}>
      <Form.Item name="workspace_id" label="所属知识库" rules={[{ required: true, message: '请选择知识库' }]}>
        <Select disabled={lockWorkspace} placeholder="选择知识库" options={workspaces.map(workspace => ({ value: workspace.id, label: workspace.name }))} />
      </Form.Item>
      {sourceExcerpt && <div className="review-source-excerpt"><strong>原文选段</strong><p>{sourceExcerpt}</p></div>}
      <Form.Item name="front" label="正面问题" rules={[{ required: true, whitespace: true, message: '请输入正面问题' }]}>
        <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} maxLength={1000} showCount placeholder="用一个清楚的问题触发回忆" />
      </Form.Item>
      <Form.Item name="back" label="背面答案" rules={[{ required: true, whitespace: true, message: '请输入背面答案' }]}>
        <Input.TextArea autoSize={{ minRows: 4, maxRows: 9 }} maxLength={5000} showCount placeholder="写下简洁、准确的答案" />
      </Form.Item>
      <Form.Item name="source_label" label="来源引用">
        <Input maxLength={500} placeholder="例如：认知心理学 · 第 32 页" />
      </Form.Item>
      <Form.Item name="tags" label="标签">
        <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后按回车，可添加多个标签" />
      </Form.Item>
      <Form.Item name="difficulty" label="难度" rules={[{ required: true }]}>
        <InputNumber min={1} max={5} precision={0} style={{ width: '100%' }} />
      </Form.Item>
    </Form>
  </Modal>;
};

import React from 'react';
import { Alert, Button, Card, Empty, Space, Tag, Typography } from 'antd';
import type { KnowledgeBaseDetail } from '../../services/api';

export const KnowledgeDocumentList = ({ documents, onOpen, onReprocess, onRegenerate, onDelete }: {
  documents: KnowledgeBaseDetail['documents'];
  onOpen: (id: string) => void;
  onReprocess: (id: string) => void;
  onRegenerate: (id: string) => void;
  onDelete: (id: string) => void;
}) => documents.length ? <Space direction="vertical" size={14} style={{ width: '100%' }}>{documents.map(document => <Card key={document.id} className="paper-card" title={document.filename} extra={<Button type="link" onClick={() => onOpen(document.id)}>查看详情</Button>}>
  <Space wrap><Tag color={document.status === 'ready' ? 'success' : document.status === 'failed' ? 'error' : 'processing'}>解析：{document.status}</Tag><Tag color={document.learning_status === 'ready' ? 'success' : document.learning_status === 'failed' ? 'error' : 'processing'}>学习内容：{document.learning_status}</Tag>{document.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}</Space>
  {document.error_message && <Alert style={{ marginTop: 12 }} type="error" message={document.error_message} />}
  {document.learning_error_message && <Alert style={{ marginTop: 12 }} type="error" message={document.learning_error_message} />}
  {document.summary && <Typography.Paragraph style={{ marginTop: 12 }} ellipsis={{ rows: 3, expandable: true }}>{document.summary}</Typography.Paragraph>}
  <Space wrap style={{ marginTop: 10 }}><Button onClick={() => onReprocess(document.id)}>重新解析</Button><Button disabled={document.status !== 'ready'} onClick={() => onRegenerate(document.id)}>重新生成学习内容</Button><Button danger onClick={() => onDelete(document.id)}>删除</Button></Space>
</Card>)}</Space> : <Empty description="暂无文档" />;


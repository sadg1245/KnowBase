import React from 'react';
import { Button, Card, Col, Empty, List, Progress, Row, Space, Tag, Typography } from 'antd';
import type { KnowledgeBaseDetail } from '../../services/api';

export const KnowledgeOverview = ({ detail, onRecommendation, onStart }: {
  detail: KnowledgeBaseDetail;
  onRecommendation: (recommendation: KnowledgeBaseDetail['recommendations'][number]) => void;
  onStart: () => void;
}) => <div>
  <Row gutter={[16, 16]}>
    <Col xs={24} lg={16}><Card className="paper-card" title="学习目标"><Typography.Paragraph>{detail.learning_goal || detail.description || '尚未设置学习目标'}</Typography.Paragraph><Button type="primary" onClick={onStart}>开始学习</Button></Card></Col>
    <Col xs={24} lg={8}><Card className="paper-card" title="学习进度"><Progress percent={detail.progress} /><Space wrap><Tag>{detail.documents.length} 份文档</Tag><Tag>{detail.knowledge_points.length} 个知识点</Tag><Tag>{detail.card_count} 张卡片</Tag></Space></Card></Col>
  </Row>
  <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
    <Col xs={24} lg={14}><Card className="paper-card" title="推荐继续学习"><List dataSource={detail.recommendations} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无推荐" /> }} renderItem={item => <List.Item actions={[<Button key="go" type="link" onClick={() => onRecommendation(item)}>继续</Button>]}>{item.title}</List.Item>} /></Card></Col>
    <Col xs={24} lg={10}><Card className="paper-card" title="最近学习记录"><List dataSource={detail.recent_activities} locale={{ emptyText: '暂无学习记录' }} renderItem={item => <List.Item><List.Item.Meta title={item.title} description={`${item.type} · ${new Date(item.created_at).toLocaleString()}`} /></List.Item>} /></Card></Col>
  </Row>
  <Card className="paper-card" title="章节目录" style={{ marginTop: 16 }}>
    {detail.documents.some(doc => doc.outline_items?.length) ? detail.documents.map(doc => doc.outline_items?.length ? <section key={doc.id}><Typography.Text strong>{doc.filename}</Typography.Text><ul>{doc.outline_items.map(item => <li key={item.chunk_id}>{item.section_path.join(' › ') || item.heading || `第 ${item.page_num ?? 1} 页`}</li>)}</ul></section> : null) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="解析完成后显示章节" />}
  </Card>
</div>;


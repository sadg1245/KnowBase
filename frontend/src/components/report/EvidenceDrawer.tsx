import React from 'react';
import { Button, Drawer, Empty, Spin, Tag } from 'antd';

import type { ReportEvidenceItem } from '../../services/api';

export const EvidenceDrawer: React.FC<{
  open: boolean; title: string; items: ReportEvidenceItem[]; loading: boolean;
  hasMore: boolean; onLoadMore: () => void; onClose: () => void;
}> = ({ open, title, items, loading, hasMore, onLoadMore, onClose }) => <Drawer
  open={open} title={`${title} · 统计依据`} width={520} onClose={onClose}
>
  {items.length ? <div className="report-evidence-list">{items.map(item => <article key={item.id}>
    <div><strong>{item.title}</strong><Tag bordered={false}>{item.source_label}</Tag></div>
    <time dateTime={item.occurred_at}>{new Date(item.occurred_at).toLocaleString('zh-CN')}</time>
    <p>{item.workspace_name || '未关联知识库'}{item.duration_seconds ? ` · ${Math.round(item.duration_seconds / 60)} 分钟` : ''}</p>
  </article>)}</div> : loading ? <Spin /> : <Empty description="这个指标在当前周期没有记录" />}
  {hasMore ? <Button block loading={loading} onClick={onLoadMore}>加载更多证据</Button> : null}
</Drawer>;

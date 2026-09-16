import React from 'react';
import { Button, Drawer, Empty, Spin, Tag } from 'antd';

import type { ReportEvidenceItem } from '../../services/api';

export const evidenceDetail = (item: ReportEvidenceItem): string | null => {
  if (item.kind === 'quiz_attempt') {
    return `得分 ${item.score ?? 0}/${item.max_score ?? 0} · 已计入正确率`;
  }
  const payload = item.payload || {};
  if (item.activity_type === 'mastery_changed') {
    return `掌握度 ${payload.before_mastery ?? '—'} → ${payload.after_mastery ?? '—'} · 状态 ${payload.before_status ?? '—'} → ${payload.after_status ?? '—'}`;
  }
  if (item.activity_type === 'weakness_changed') {
    return `薄弱度 ${payload.before_score ?? '—'} → ${payload.after_score ?? '—'} · 分类 ${payload.before_category ?? '—'} → ${payload.after_category ?? '—'}`;
  }
  return null;
};

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
    {evidenceDetail(item) ? <p className="report-evidence-detail">{evidenceDetail(item)}</p> : null}
  </article>)}</div> : loading ? <Spin /> : <Empty description="这个指标在当前周期没有记录" />}
  {hasMore ? <Button block loading={loading} onClick={onLoadMore}>加载更多证据</Button> : null}
</Drawer>;

import React from 'react';
import { Empty, Tag } from 'antd';

import type { DashboardActivity } from '../../services/api';

const labels: Record<string, string> = {
  document_read: '阅读', question_asked: '提问', conversation_completed: '会话', card_created: '卡片',
  review_completed: '复习', quiz_completed: '测验', knowledge_mastered: '掌握', goal_changed: '目标',
};

export const ActivityTimeline: React.FC<{ activities: DashboardActivity[] }> = ({ activities }) => <section className="dashboard-section">
  <header className="dashboard-section-heading"><div><span className="dashboard-kicker">Learning trail</span><h2>最近学习记录</h2></div></header>
  {activities.length ? <div className="dashboard-activity-list">{activities.map(item => <article key={item.id}>
    <time dateTime={item.occurred_at || item.created_at}>{new Date(item.occurred_at || item.created_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}</time>
    <span className="dashboard-activity-dot" />
    <div><strong>{item.title}</strong><small>{item.duration_seconds ? `${Math.max(1, Math.round(item.duration_seconds / 60))} 分钟 · ` : ''}{item.source_type || '历史记录'}</small></div>
    <Tag bordered={false}>{labels[item.type] || '学习'}</Tag>
  </article>)}</div> : <div className="dashboard-empty dashboard-empty-compact"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="完成一次学习后，这里会留下记录" /></div>}
</section>;

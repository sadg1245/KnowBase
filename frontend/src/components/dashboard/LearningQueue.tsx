import React from 'react';
import { Button, Empty } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';

import type { DashboardLearningQueue, WorkspaceRecommendation } from '../../services/api';

export const LearningQueue: React.FC<{
  queue: DashboardLearningQueue;
  recommendations: WorkspaceRecommendation[];
  onNavigate: (path: string) => void;
}> = ({ queue, recommendations, onNavigate }) => <section className="dashboard-section">
  <header className="dashboard-section-heading"><div><span className="dashboard-kicker">Next up</span><h2>学习队列</h2></div></header>
  <div className="dashboard-queue-grid">
    <button className="dashboard-queue-count" onClick={() => onNavigate(queue.due_reviews.path)}>
      <span>待复习卡片</span><strong>{queue.due_reviews.count}</strong><small>进入复习中心 <ArrowRightOutlined /></small>
    </button>
    <button className="dashboard-queue-count is-warm" onClick={() => onNavigate(queue.mistakes.path)}>
      <span>待重做错题</span><strong>{queue.mistakes.count}</strong><small>打开错题本 <ArrowRightOutlined /></small>
    </button>
    <div className="dashboard-recommendations">
      <span className="dashboard-queue-label">推荐继续学习</span>
      {recommendations.length ? recommendations.map(item => <button key={item.workspace_id} onClick={() => onNavigate(item.path)}>
        <i style={{ background: item.accent_color }} /><span><strong>{item.name}</strong><small>{item.reason}</small></span><ArrowRightOutlined />
      </button>) : <div className="dashboard-empty dashboard-empty-compact">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有可推荐的知识库" />
        <Button type="link" onClick={() => onNavigate('/upload')}>导入一份资料</Button>
      </div>}
    </div>
  </div>
</section>;

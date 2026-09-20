import React from 'react';
import { Button, Empty } from 'antd';

import type { ProfileRecentLearning } from '../../services/api';

export const RecentLearningCard: React.FC<{
  items: ProfileRecentLearning[];
  observations?: string[];
  onOpenReport: () => void;
}> = ({ items, observations = [], onOpenReport }) => <section className="dashboard-section profile-recent" aria-labelledby="profile-recent-title">
  <header className="dashboard-section-heading">
    <div><span className="dashboard-kicker">Recent</span><h2 id="profile-recent-title">最近学习与趋势</h2></div>
    <Button type="link" onClick={onOpenReport}>查看报告</Button>
  </header>
  {items.length ? <ul className="profile-recent-list">{items.map(item => <li key={item.date}>
    <span className="profile-recent-day">{item.label}</span>
    <div>
      {item.areas.map(area => <p key={`${item.date}-${area.name}`}>
        <strong>{area.name}</strong><small>{Math.round(area.minutes)} 分钟</small>
      </p>)}
      {!item.areas.length ? <p><strong>学习记录</strong><small>{item.activity_count} 次活动</small></p> : null}
    </div>
    <span className="profile-recent-total">{Math.round(item.minutes)}<small>分钟</small></span>
  </li>)}</ul> : <div className="dashboard-empty dashboard-empty-compact"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="完成一次学习后，这里会留下每天的记录" /></div>}
  {observations.length ? <div className="profile-observations">
    <strong>系统观察</strong>
    <ul>{observations.map(note => <li key={note}>{note}</li>)}</ul>
  </div> : null}
</section>;

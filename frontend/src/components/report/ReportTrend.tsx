import React from 'react';
import type { LearningReport } from '../../services/api';

export const ReportTrend: React.FC<{ trend: LearningReport['trend'] }> = ({ trend }) => {
  const maximum = Math.max(1, ...trend.map(item => item.active_seconds));
  return <section className="report-trend" aria-label="学习时长趋势">
    <header><div><span className="dashboard-kicker">Rhythm</span><h2>学习节奏</h2></div><small>每根柱显示当天有效学习时长</small></header>
    <div className="report-trend-bars">{trend.map(item => {
      const minutes = Math.round(item.active_seconds / 60);
      return <div key={item.date} className="report-trend-column">
        <span className="report-trend-value">{minutes} 分</span>
        <span className="report-trend-bar" style={{ height: `${Math.max(3, item.active_seconds / maximum * 100)}%` }} />
        <time dateTime={item.date}>{item.date.slice(5)}</time>
      </div>;
    })}</div>
  </section>;
};

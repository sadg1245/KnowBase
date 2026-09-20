import React from 'react';
import { Button, Progress, Tag } from 'antd';
import { BulbOutlined } from '@ant-design/icons';

import type { ProfileWeakPoint } from '../../services/api';
import { masteryStatusMeta, percent, WEAKNESS_BAND_META } from '../../features/dashboard/profileViewModel';

export const WeakPointCard: React.FC<{
  point: ProfileWeakPoint;
  rank?: number;
  compact?: boolean;
  onAction: (path: string) => void;
  onShowEvidence: (point: ProfileWeakPoint) => void;
}> = ({ point, rank, compact = false, onAction, onShowEvidence }) => {
  const band = WEAKNESS_BAND_META[point.weakness_band] || WEAKNESS_BAND_META.watch;
  const mastery = masteryStatusMeta(point.mastery_status, point.mastery);
  return <article className={`profile-weak-card ${compact ? 'is-compact' : ''}`} data-band={point.weakness_band}>
    <header>
      {typeof rank === 'number' ? <span className="profile-weak-rank">{rank}</span> : null}
      <div>
        <h3>{point.name}</h3>
        <small>{point.area}{point.mastery_status_label ? ` · ${point.mastery_status_label}` : ''}</small>
      </div>
      <Tag bordered={false} className={`profile-band is-${band.tone}`}>{point.weakness_band_label || band.label}</Tag>
    </header>
    <div className="profile-weak-meter">
      <Progress percent={percent(point.mastery)} showInfo={false} strokeColor={mastery.color} trailColor="#e7edef" />
      <span><strong>{percent(point.mastery)}%</strong><small>掌握度 · 薄弱分 {percent(point.weakness_score)}</small></span>
    </div>
    {point.reasons.length ? <ul className="profile-weak-reasons">
      {point.reasons.slice(0, compact ? 1 : 3).map(reason => <li key={reason}>{reason}</li>)}
    </ul> : null}
    <footer className="profile-weak-actions">
      {point.actions.filter(action => action.path).map(action => <Button
        key={action.type}
        size="small"
        onClick={() => onAction(action.path as string)}
      >{action.label}</Button>)}
      <Button type="link" size="small" icon={<BulbOutlined />} onClick={() => onShowEvidence(point)}>为什么？</Button>
    </footer>
  </article>;
};

export const WeakPointList: React.FC<{
  points: ProfileWeakPoint[];
  title?: string;
  emptyCopy?: string;
  onAction: (path: string) => void;
  onShowEvidence: (point: ProfileWeakPoint) => void;
  onStartPractice?: () => void;
}> = ({
  points, title = '薄弱知识点', emptyCopy = '完成练习和复习后，这里会显示需要再看一眼的知识。',
  onAction, onShowEvidence, onStartPractice,
}) => <section className="dashboard-section profile-weak-section" aria-labelledby="profile-weak-title">
  <header className="dashboard-section-heading">
    <div><span className="dashboard-kicker">Need attention</span><h2 id="profile-weak-title">{title}</h2></div>
  </header>
  {points.length
    ? <div className="profile-weak-list">{points.map((point, index) => <WeakPointCard
      key={point.knowledge_point_id}
      point={point}
      rank={index + 1}
      compact
      onAction={onAction}
      onShowEvidence={onShowEvidence}
    />)}</div>
    : <div className="dashboard-empty"><p>{emptyCopy}</p>{onStartPractice ? <Button onClick={onStartPractice}>开始一次练习</Button> : null}</div>}
</section>;

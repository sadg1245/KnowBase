import React from 'react';
import { Button, Progress, Tag } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';

import type { ProfileFocusItem, ProfileMasteryItem, ProfileWeakPoint } from '../../services/api';
import { masteryStatusMeta, percent, trendView } from '../../features/dashboard/profileViewModel';

export const ProfileWaitingCard: React.FC<{ hint: string; onStart: () => void; onImport: () => void }> = ({
  hint, onStart, onImport,
}) => <section className="dashboard-section profile-waiting">
  <span className="dashboard-kicker">Learning profile</span>
  <h2>你的学习画像正在等待形成</h2>
  <p>{hint}</p>
  <div className="profile-waiting-actions">
    <Button type="primary" onClick={onStart}>开始学习</Button>
    <Button onClick={onImport}>导入资料</Button>
  </div>
</section>;

export const ProfileOverviewCard: React.FC<{
  focusName?: string | null;
  focusPoints?: ProfileFocusItem[];
  mastery: ProfileMasteryItem[];
  weakPoints: ProfileWeakPoint[];
  onOpenProfile: () => void;
  onOpenArea?: (item: ProfileMasteryItem) => void;
  onOpenWeakPoint?: (point: ProfileWeakPoint) => void;
}> = ({ focusName, focusPoints = [], mastery, weakPoints, onOpenProfile, onOpenArea, onOpenWeakPoint }) =>
  <section className="dashboard-section profile-overview" aria-labelledby="profile-overview-title">
    <header className="dashboard-section-heading">
      <div><span className="dashboard-kicker">Learning profile</span><h2 id="profile-overview-title">我的学习画像</h2></div>
      <Button type="link" onClick={onOpenProfile}>查看完整画像 <ArrowRightOutlined /></Button>
    </header>
    {focusName ? <p className="profile-focus">
      <span>当前方向</span><strong>{focusName}</strong>
      {focusPoints.length ? <small>当前重点：{focusPoints.slice(0, 3).map(item => item.name).join('、')}</small> : null}
    </p> : null}
    {mastery.length ? <ul className="profile-mastery-list">{mastery.map(item => {
      const meta = masteryStatusMeta(item.status, item.score);
      const trend = trendView(item.trend);
      return <li key={item.workspace_id || item.name}>
        <button type="button" onClick={() => onOpenArea?.(item)}>
          <span className="profile-mastery-name"><strong>{item.name}</strong><small>{item.status_label || meta.label}</small></span>
          <span className="profile-mastery-value">{percent(item.score)}<small>%</small></span>
          {trend.tone !== 'unknown' ? <Tag bordered={false} className={`profile-trend is-${trend.tone}`}>{trend.text}</Tag> : null}
        </button>
        <Progress percent={percent(item.score)} showInfo={false} strokeColor={meta.color} trailColor="#e7edef" />
      </li>;
    })}</ul> : <p className="profile-overview-empty">掌握度会在有了练习与复习记录后出现。</p>}
    {weakPoints.length ? <div className="profile-weak-strip">
      <strong>当前薄弱</strong>
      <div>{weakPoints.map(point => <button key={point.knowledge_point_id} type="button" onClick={() => onOpenWeakPoint?.(point)}>
        {point.name}<small>{percent(point.mastery)}%</small>
      </button>)}</div>
    </div> : <p className="profile-weak-strip is-clear">暂时没有明显薄弱点，保持现在的节奏就好。</p>}
  </section>;

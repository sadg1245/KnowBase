import React from 'react';
import { Progress, Tag } from 'antd';

import type { ProfileMasteryItem } from '../../services/api';
import {
  confidenceView, masteryStatusMeta, percent, sortedMastery, trendView,
} from '../../features/dashboard/profileViewModel';

const trendToneClass = (tone: string) => `profile-trend is-${tone}`;

const MasteryLeaf: React.FC<{ item: ProfileMasteryItem }> = ({ item }) => {
  const meta = masteryStatusMeta(item.status, item.score);
  const trend = trendView(item.trend);
  const confidence = confidenceView(item);
  return <li className="profile-mastery-leaf">
    <div className="profile-mastery-leaf-head">
      <strong>{item.name}</strong>
      <span className="profile-mastery-value">{percent(item.score)}<small>%</small></span>
      <Tag bordered={false} className={`profile-status is-${meta.tone}`}>{item.status_label || meta.label}</Tag>
    </div>
    <Progress percent={percent(item.score)} showInfo={false} strokeColor={meta.color} trailColor="#e7edef" />
    <div className="profile-mastery-meta">
      {trend.tone !== 'unknown' ? <span className={trendToneClass(trend.tone)}>{trend.text}</span> : null}
      {confidence ? <span className="profile-mastery-confidence">{confidence.text}{confidence.note ? ` · ${confidence.note}` : ''}</span> : null}
    </div>
  </li>;
};

export const MasteryOverview: React.FC<{
  areas: ProfileMasteryItem[];
  onOpenArea?: (item: ProfileMasteryItem) => void;
}> = ({ areas, onOpenArea }) => {
  if (!areas.length) return <p className="profile-overview-empty">还没有可用于计算掌握度的知识点。</p>;
  return <div className="profile-mastery-tree">{sortedMastery(areas).map(area => {
    const meta = masteryStatusMeta(area.status, area.score);
    const trend = trendView(area.trend);
    const confidence = confidenceView(area);
    const hidden = Math.max(0, area.knowledge_point_count - area.children.length);
    return <section className="profile-mastery-branch" key={area.workspace_id || area.name}>
      <header>
        <button type="button" onClick={() => onOpenArea?.(area)}>
          <strong>{area.name}</strong>
          <span className="profile-mastery-value">{percent(area.score)}<small>%</small></span>
        </button>
        <Tag bordered={false} className={`profile-status is-${meta.tone}`}>{area.status_label || meta.label}</Tag>
        {trend.tone !== 'unknown' ? <Tag bordered={false} className={trendToneClass(trend.tone)}>{trend.text}</Tag> : null}
        {confidence?.note ? <small className="profile-mastery-confidence">{confidence.note}</small> : null}
      </header>
      <Progress percent={percent(area.score)} showInfo={false} strokeColor={meta.color} trailColor="#e7edef" />
      {area.children.length
        ? <ul className="profile-mastery-children">{area.children.map(child => <MasteryLeaf key={child.knowledge_point_id || child.name} item={child} />)}</ul>
        : null}
      {hidden > 0 ? <p className="profile-mastery-more">还有 {hidden} 个知识点未展开，可进入知识库查看全部。</p> : null}
    </section>;
  })}</div>;
};

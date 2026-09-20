import React from 'react';
import { Button, Progress, Tag } from 'antd';

import type { ProfileGoal } from '../../services/api';
import { goalPlan, goalProgressView } from '../../features/dashboard/profileViewModel';

const Bucket: React.FC<{ label: string; marker: string; items: string[]; tone: string }> = ({
  label, marker, items, tone,
}) => items.length ? <div className={`profile-goal-bucket is-${tone}`}>
  <strong>{label}</strong>
  <ul>{items.map(item => <li key={item}><span>{marker}</span>{item}</li>)}</ul>
</div> : null;

export const GoalProgressCard: React.FC<{
  goals: ProfileGoal[];
  onOpenReport: () => void;
}> = ({ goals, onOpenReport }) => {
  const goal = goalPlan(goals);
  return <section className="dashboard-section profile-goal-section" aria-labelledby="profile-goal-title">
    <header className="dashboard-section-heading">
      <div><span className="dashboard-kicker">Goal</span><h2 id="profile-goal-title">学习目标</h2></div>
      {goal ? <Tag bordered={false} className={`profile-goal-status is-${goalProgressView(goal).tone}`}>{goalProgressView(goal).label}</Tag> : null}
    </header>
    {goal ? <>
      <div className="profile-goal-head">
        <strong>{goal.title}</strong>
        <span className="profile-mastery-value">{goalProgressView(goal).percent}<small>%</small></span>
      </div>
      <Progress percent={goalProgressView(goal).percent} showInfo={false} strokeColor="#167d8d" trailColor="#e7edef" />
      <div className="profile-goal-buckets">
        <Bucket label="已完成" marker="✓" items={goal.completed} tone="done" />
        <Bucket label="学习中" marker="→" items={goal.learning} tone="active" />
        <Bucket label="待学习" marker="○" items={goal.pending} tone="todo" />
      </div>
      <Button type="link" onClick={onOpenReport}>调整学习目标</Button>
    </> : <div className="dashboard-empty"><p>还没有设置学习目标，可以先去报告页定一个。</p><Button onClick={onOpenReport}>设置目标</Button></div>}
  </section>;
};

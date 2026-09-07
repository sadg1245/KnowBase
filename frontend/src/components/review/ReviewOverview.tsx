import React from 'react';
import { Button, Progress, Typography } from 'antd';
import {
  CalendarOutlined, ClockCircleOutlined, FireOutlined, InboxOutlined,
  PlusCircleOutlined, ReadOutlined, RightOutlined, WarningOutlined,
} from '@ant-design/icons';
import type { ReviewSummary } from '../../services/api';
import type { LearningTask } from '../../features/practice/types';

const { Text, Title } = Typography;

interface ReviewOverviewProps {
  summary: ReviewSummary;
  tasks?: LearningTask[];
  onStart: () => void;
  onManage: () => void;
  onTask?: (path: string) => void;
  onCompleteTask?: (taskId: string) => void;
  completingTaskId?: string;
}

const metrics = (summary: ReviewSummary) => [
  { label: '今日待复习', value: summary.due_count, suffix: '张', icon: <CalendarOutlined /> },
  { label: '新卡片', value: summary.new_count, suffix: '张', icon: <PlusCircleOutlined /> },
  { label: '今日完成', value: summary.completed_today, suffix: '张', icon: <ReadOutlined /> },
  { label: '预计时长', value: summary.estimated_minutes, suffix: '分钟', icon: <ClockCircleOutlined /> },
  { label: '连续学习', value: summary.streak_days, suffix: '天', icon: <FireOutlined /> },
  { label: '逾期卡片', value: summary.overdue_count, suffix: '张', icon: <WarningOutlined /> },
];

export const ReviewOverview: React.FC<ReviewOverviewProps> = ({ summary, tasks = [], onStart, onManage, onTask, onCompleteTask, completingTaskId }) => {
  const targetPercent = Math.min(100, Math.round((summary.completed_today / Math.max(1, summary.daily_target)) * 100));
  return <div className="review-overview">
    <div className="review-hero paper-card">
      <div>
        <div className="page-eyebrow">Review · 长期记忆</div>
        <Title className="page-title" level={1}>复习中心</Title>
        <p className="page-lead">每天一点主动回忆，让重要知识在恰当的时间重新出现。</p>
      </div>
      <div className="review-hero-actions">
        <Button size="large" icon={<InboxOutlined />} onClick={onManage}>管理卡片</Button>
        <Button size="large" type="primary" icon={<RightOutlined />} disabled={!summary.due_count} onClick={onStart}>开始复习</Button>
      </div>
      <div className="review-daily-track" aria-label={`今日目标完成 ${targetPercent}%`}>
        <div><Text type="secondary">今日目标</Text><Text strong>{summary.completed_today} / {summary.daily_target}</Text></div>
        <Progress percent={targetPercent} showInfo={false} strokeColor="#167d8d" trailColor="#dbeae9" />
      </div>
    </div>

    <div className="review-metric-grid">
      {metrics(summary).map(metric => <article className="review-metric paper-card" key={metric.label}>
        <span className="review-metric-icon">{metric.icon}</span>
        <Text type="secondary">{metric.label}</Text>
        <div><strong className="metric-number">{metric.value}</strong><small>{metric.suffix}</small></div>
      </article>)}
    </div>

    <section className="review-weak paper-card">
      <div className="review-section-heading">
        <div><div className="page-eyebrow">Focus · 查漏补缺</div><Title level={3}>薄弱知识点</Title></div>
        <Text type="secondary">优先显示关键且掌握度较低的内容</Text>
      </div>
      {summary.weak_points.length ? <div className="review-weak-list">
        {summary.weak_points.map(point => <div className="review-weak-row" key={point.id}>
          <div><Text strong>{point.title}</Text>{point.is_key && <span className="review-key-label">重点</span>}</div>
          <div className="review-weak-progress"><Progress percent={Math.round(point.mastery * 100)} showInfo={false} strokeColor="#d59a42" /><Text>{Math.round(point.mastery * 100)}%</Text></div>
        </div>)}
      </div> : <div className="review-inline-empty">完成几次复习后，这里会显示需要巩固的知识点。</div>}
    </section>

    <section className="review-tasks paper-card">
      <div className="review-section-heading">
        <div><div className="page-eyebrow">NEXT · 可完成的巩固安排</div><Title level={3}>近期学习任务</Title></div>
        <Text type="secondary">路径与截止时间来自你的学习记录</Text>
      </div>
      {tasks.length ? <div className="review-task-list">{tasks.map(task => <article key={task.id}>
        <div><Text strong>{task.title}</Text><small>{task.knowledge_point_title || '综合复习'} · {task.due_at ? `截止 ${new Date(task.due_at).toLocaleString('zh-CN')}` : '未设截止时间'} · 待完成</small></div>
        <div>
          {task.path ? <Button href={task.path} onClick={event => { event.preventDefault(); onTask?.(task.path!); }}>开始任务</Button> : null}
          <Button type="link" loading={completingTaskId === task.id} onClick={() => onCompleteTask?.(task.id)}>标记完成</Button>
        </div>
      </article>)}</div> : <div className="review-inline-empty">今天没有到期的学习任务，可以专注完成卡片复习。</div>}
    </section>
  </div>;
};


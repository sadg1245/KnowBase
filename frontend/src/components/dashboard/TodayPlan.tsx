import React from 'react';
import { Button, Empty, Tag } from 'antd';
import { ArrowRightOutlined, CheckOutlined } from '@ant-design/icons';

import type { DashboardTask } from '../../services/api';
import { dashboardTaskAction, taskCountLabel } from '../../features/dashboard/dashboardViewModel';

export const TodayPlan: React.FC<{
  tasks: DashboardTask[];
  completingIds?: ReadonlySet<string>;
  onNavigate: (path: string) => void;
  onComplete: (taskId: string) => void;
}> = ({ tasks, completingIds, onNavigate, onComplete }) => <section className="dashboard-section dashboard-plan">
  <header className="dashboard-section-heading">
    <div><span className="dashboard-kicker">Today plan</span><h2>今天，沿这条线走</h2></div>
    <span>{tasks.filter(task => task.status === 'completed').length}/{tasks.length} 已完成</span>
  </header>
  {tasks.length ? <div className="dashboard-plan-track">{tasks.map((task, index) => {
    const action = dashboardTaskAction(task);
    return <article key={task.id || `${task.type}-${index}`} className={`dashboard-plan-item ${task.status === 'completed' ? 'is-complete' : ''}`}>
      <div className="dashboard-plan-marker"><span>{task.status === 'completed' ? <CheckOutlined /> : index + 1}</span></div>
      <div className="dashboard-plan-content">
        <div className="dashboard-plan-title"><h3>{task.title}</h3><Tag bordered={false}>{taskCountLabel(task)}</Tag></div>
        <p>{task.description || (typeof task.count === 'number' ? `还有 ${task.count} 项等待你` : '完成后会自动更新今日进度')}</p>
        <small>{typeof task.estimated_minutes === 'number' ? `约 ${task.estimated_minutes} 分钟` : '按实际学习记录更新'}{task.source?.type ? ` · 来源：${task.source.type === 'learning_task' ? '薄弱知识任务' : '学习记录'}` : ''}</small>
      </div>
      <div className="dashboard-plan-actions">
        {task.path ? <Button type="link" href={task.path} onClick={event => { event.preventDefault(); onNavigate(task.path!); }}>前往 <ArrowRightOutlined /></Button> : null}
        {action.kind === 'complete' && task.id ? <Button size="small" loading={completingIds?.has(task.id)} onClick={() => onComplete(task.id!)}>标记完成</Button> : null}
      </div>
    </article>;
  })}</div> : <div className="dashboard-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="今天还没有生成任务"/><Button type="primary" onClick={() => onNavigate('/learn')}>开始第一次学习</Button></div>}
</section>;

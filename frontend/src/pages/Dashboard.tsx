import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App, Button, Progress, Skeleton } from 'antd';
import { SettingOutlined } from '@ant-design/icons';

import { ActivityTimeline } from '../components/dashboard/ActivityTimeline';
import { LearningQueue } from '../components/dashboard/LearningQueue';
import { QuickQuestion } from '../components/dashboard/QuickQuestion';
import { TodayPlan } from '../components/dashboard/TodayPlan';
import { quickQuestionDestination } from '../features/learning/quickQuestion';
import { createTaskCompletionCoordinator, type TaskCompletionCoordinator } from '../features/practice/learningLoop';
import { completeLearningTask, getLearningDashboard } from '../services/api';
import type { LearningDashboard } from '../services/api';

export const TodayTaskList = TodayPlan;

const Dashboard: React.FC = () => {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [data, setData] = useState<LearningDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [completingIds, setCompletingIds] = useState<ReadonlySet<string>>(() => new Set());
  const requestVersion = useRef(0);
  const completionCoordinator = useRef<TaskCompletionCoordinator | null>(null);

  const loadDashboard = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    try {
      const next = await getLearningDashboard();
      if (version === requestVersion.current) setData(next);
    } catch {
      if (version === requestVersion.current) message.error('学习数据暂时没有加载成功，请重试');
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    const coordinator = createTaskCompletionCoordinator(setCompletingIds);
    completionCoordinator.current = coordinator;
    void loadDashboard();
    return () => {
      requestVersion.current += 1;
      coordinator.dispose();
      if (completionCoordinator.current === coordinator) completionCoordinator.current = null;
    };
  }, [loadDashboard]);

  const completeTask = (taskId: string) => completionCoordinator.current?.run(
    taskId,
    () => completeLearningTask(taskId),
    async () => { message.success('学习任务已完成'); await loadDashboard(); },
    async () => { message.error('任务完成状态没有保存，请重试'); },
  );
  const greeting = useMemo(() => {
    const hour = new Date().getHours();
    return hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好';
  }, []);
  const workspaceOptions = useMemo(() => {
    const byId = new Map<string, { id: string; name: string }>();
    data?.recommended_workspaces.forEach(item => byId.set(item.workspace_id, { id: item.workspace_id, name: item.name }));
    data?.recent_workspaces.forEach(item => byId.set(item.id, { id: item.id, name: item.name }));
    return [...byId.values()];
  }, [data?.recent_workspaces, data?.recommended_workspaces]);

  if (loading) return <Skeleton active paragraph={{ rows: 12 }} />;
  if (!data) return <div className="dashboard-load-error"><h2>首页暂时没有加载成功</h2><p>学习记录仍然安全保存，可以立即重试。</p><Button type="primary" onClick={() => void loadDashboard()}>重新加载</Button></div>;
  const minutesGoal = data.goal_progress.daily_minutes;
  const dailyPercent = Math.min(100, Math.round(minutesGoal.ratio * 100));

  return <main className="dashboard-page">
    <section className="dashboard-hero">
      <div className="dashboard-hero-copy">
        <span className="dashboard-kicker">Today · 你的学习现场</span>
        <h1>{greeting}，{data.profile.display_name}</h1>
        <p>今天不必学很多。先完成最靠前的一件事，让理解继续生长。</p>
      </div>
      <div className="dashboard-day-seal" aria-label={`今日目标完成 ${dailyPercent}%`}>
        <Progress type="circle" size={92} percent={dailyPercent} strokeColor="#167d8d" trailColor="#d9e8e7" />
        <small>今日 {data.stats.today_minutes}/{data.profile.daily_goal_minutes} 分钟</small>
      </div>
      <dl className="dashboard-vitals">
        <div><dt>连续学习</dt><dd>{data.stats.streak_days}<small>天</small></dd></div>
        <div><dt>本周学习</dt><dd>{data.stats.week_minutes}<small>分钟</small></dd></div>
        <div><dt>当前薄弱点</dt><dd>{data.weak_points.length}<small>个</small></dd></div>
      </dl>
    </section>

    <QuickQuestion workspaces={workspaceOptions} onAsk={(question, workspaceId) => navigate(
      quickQuestionDestination(question, workspaceId, crypto.randomUUID())
    )} />

    <div className="dashboard-primary-grid">
      <TodayPlan tasks={data.today_tasks} completingIds={completingIds} onNavigate={navigate} onComplete={taskId => void completeTask(taskId)} />
      <LearningQueue queue={data.learning_queue} recommendations={data.recommended_workspaces} onNavigate={navigate} />
    </div>

    <div className="dashboard-review-grid">
      <ActivityTimeline activities={data.recent_activities} />
      <section className="dashboard-section dashboard-weakness">
        <header className="dashboard-section-heading"><div><span className="dashboard-kicker">Focus</span><h2>当前薄弱知识点（导师建议优先级）</h2></div></header>
        {data.weak_points.length ? <div>{data.weak_points.map(point => <button key={point.id} onClick={() => navigate(`/knowledge/${point.workspace_id}`)}>
          <Progress type="circle" size={40} percent={Math.round(point.mastery * 100)} showInfo={false} strokeColor="#c98b37" />
          <span><strong>{point.title}</strong><small>掌握度 {Math.round(point.mastery * 100)}%{typeof point.weakness_score === 'number' ? ` · 薄弱分 ${Math.round(point.weakness_score)}` : ''}</small></span>
        </button>)}</div> : <div className="dashboard-empty"><p>完成测验和复习后，这里会显示需要再看一眼的知识。</p><Button onClick={() => navigate('/practice')}>开始一次练习</Button></div>}
      </section>
    </div>
    <footer className="dashboard-footer-link"><Button type="text" icon={<SettingOutlined />} onClick={() => navigate('/report')}>查看报告并调整学习目标</Button></footer>
  </main>;
};

export default Dashboard;

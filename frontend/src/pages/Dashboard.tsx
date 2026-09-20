import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App, Button, Modal, Progress, Skeleton, Tag } from 'antd';
import { SettingOutlined } from '@ant-design/icons';

import { ActivityTimeline } from '../components/dashboard/ActivityTimeline';
import { GoalProgressCard } from '../components/dashboard/GoalProgressCard';
import { LearningInsightCard } from '../components/dashboard/LearningInsightCard';
import { LearningQueue } from '../components/dashboard/LearningQueue';
import { ProfileEvidenceDrawer } from '../components/dashboard/ProfileEvidenceDrawer';
import { ProfileOverviewCard, ProfileWaitingCard } from '../components/dashboard/ProfileOverviewCard';
import { QuickQuestion } from '../components/dashboard/QuickQuestion';
import { RecentLearningCard } from '../components/dashboard/RecentLearningCard';
import { TodayPlan } from '../components/dashboard/TodayPlan';
import { WeakPointList } from '../components/dashboard/WeakPointCard';
import { dashboardProfileView } from '../features/dashboard/profileViewModel';
import { quickQuestionDestination } from '../features/learning/quickQuestion';
import { createTaskCompletionCoordinator, type TaskCompletionCoordinator } from '../features/practice/learningLoop';
import { completeLearningTask, generateProfileInsight, getLearningDashboard } from '../services/api';
import type { LearningDashboard, ProfileInsight, ProfileWeakPoint } from '../services/api';

export const TodayTaskList = TodayPlan;

const Dashboard: React.FC = () => {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [data, setData] = useState<LearningDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [completingIds, setCompletingIds] = useState<ReadonlySet<string>>(() => new Set());
  const [aiInsight, setAiInsight] = useState<ProfileInsight | null>(null);
  const [generatingInsight, setGeneratingInsight] = useState(false);
  const [insightError, setInsightError] = useState<string | null>(null);
  const [evidencePoint, setEvidencePoint] = useState<ProfileWeakPoint | null>(null);
  const [insightEvidence, setInsightEvidence] = useState<string[] | null>(null);
  const requestVersion = useRef(0);
  const completionCoordinator = useRef<TaskCompletionCoordinator | null>(null);

  const loadDashboard = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    try {
      const next = await getLearningDashboard();
      if (version === requestVersion.current) {
        setData(next);
        setAiInsight(null);
        setInsightError(null);
      }
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

  const profileView = useMemo(() => dashboardProfileView(data?.profile), [data?.profile]);
  const insight = aiInsight?.text ? aiInsight : profileView.insight;

  const askAiForInsight = useCallback(async () => {
    setGeneratingInsight(true);
    setInsightError(null);
    try {
      setAiInsight(await generateProfileInsight());
    } catch {
      setInsightError('AI 摘要暂时没有生成成功，先按上面的规则结论安排学习。');
    } finally {
      setGeneratingInsight(false);
    }
  }, []);

  if (loading) return <Skeleton active paragraph={{ rows: 12 }} />;
  if (!data) return <div className="dashboard-load-error"><h2>首页暂时没有加载成功</h2><p>学习记录仍然安全保存，可以立即重试。</p><Button type="primary" onClick={() => void loadDashboard()}>重新加载</Button></div>;
  const minutesGoal = data.goal_progress.daily_minutes;
  const dailyPercent = Math.min(100, Math.round(minutesGoal.ratio * 100));
  const weakPoints = profileView.isReady ? profileView.weakPoints : [];

  return <main className="dashboard-page">
    <section className="dashboard-hero">
      <div className="dashboard-hero-copy">
        <span className="dashboard-kicker">Today · 你的学习现场</span>
        <h1>{greeting}，{data.profile.display_name}</h1>
        <p>{profileView.focusName ? `今天继续学习 ${profileView.focusName}。` : '今天不必学很多。'}先完成最靠前的一件事，让理解继续生长。</p>
      </div>
      <div className="dashboard-day-seal" aria-label={`今日目标完成 ${dailyPercent}%`}>
        <Progress type="circle" size={92} percent={dailyPercent} strokeColor="#167d8d" trailColor="#d9e8e7" />
        <small>今日 {data.stats.today_minutes}/{data.profile.daily_goal_minutes} 分钟</small>
      </div>
      <dl className="dashboard-vitals">
        <div><dt>连续学习</dt><dd>{data.stats.streak_days}<small>天</small></dd></div>
        <div><dt>本周学习</dt><dd>{data.stats.week_minutes}<small>分钟</small></dd></div>
        <div><dt>当前薄弱点</dt><dd>{weakPoints.length || data.weak_points.length}<small>个</small></dd></div>
      </dl>
    </section>

    <QuickQuestion workspaces={workspaceOptions} onAsk={(question, workspaceId) => navigate(
      quickQuestionDestination(question, workspaceId, crypto.randomUUID())
    )} />

    <div className="dashboard-primary-grid">
      {profileView.isEmpty
        ? <ProfileWaitingCard
          hint={profileView.emptyHint}
          onStart={() => navigate('/learn')}
          onImport={() => navigate('/upload')}
        />
        : <ProfileOverviewCard
          focusName={profileView.focusName}
          focusPoints={data.profile.focus_points}
          mastery={profileView.mastery}
          weakPoints={weakPoints}
          onOpenProfile={() => navigate('/profile')}
          onOpenArea={item => item.workspace_id && navigate(`/knowledge/${item.workspace_id}`)}
          onOpenWeakPoint={point => setEvidencePoint(point)}
        />}
      <TodayPlan tasks={data.today_tasks} completingIds={completingIds} onNavigate={navigate} onComplete={taskId => void completeTask(taskId)} />
    </div>

    {profileView.isReady && insight ? <LearningInsightCard
      insight={insight}
      generating={generatingInsight}
      generateError={insightError}
      onGenerate={() => void askAiForInsight()}
      onShowEvidence={setInsightEvidence}
      onStart={() => navigate('/learn')}
    /> : null}

    {profileView.isReady ? <div className="dashboard-review-grid">
      <WeakPointList
        points={weakPoints}
        onAction={navigate}
        onShowEvidence={setEvidencePoint}
        onStartPractice={() => navigate('/practice')}
      />
      <RecentLearningCard
        items={profileView.recentLearning}
        observations={profileView.observations}
        onOpenReport={() => navigate('/report')}
      />
    </div> : null}

    <div className="dashboard-primary-grid">
      <GoalProgressCard goals={profileView.goals} onOpenReport={() => navigate('/report')} />
      <LearningQueue queue={data.learning_queue} recommendations={data.recommended_workspaces} onNavigate={navigate} />
    </div>

    <ActivityTimeline activities={data.recent_activities} />
    <footer className="dashboard-footer-link"><Button type="text" icon={<SettingOutlined />} onClick={() => navigate('/report')}>查看报告并调整学习目标</Button></footer>

    <ProfileEvidenceDrawer
      open={Boolean(evidencePoint)}
      point={evidencePoint}
      onClose={() => setEvidencePoint(null)}
      onAction={path => { setEvidencePoint(null); navigate(path); }}
    />
    <Modal
      open={Boolean(insightEvidence)}
      title="画像依据"
      footer={null}
      onCancel={() => setInsightEvidence(null)}
    >
      <p>这些数字来自你的练习、复习与学习记录：</p>
      <ul className="profile-insight-evidence">{(insightEvidence || []).map(line => <li key={line}>{line}</li>)}</ul>
      <Tag bordered={false} className="profile-evidence-note">画像不参与资料事实引用。</Tag>
    </Modal>
  </main>;
};

export default Dashboard;

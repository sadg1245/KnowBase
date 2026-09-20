import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App, Button, Skeleton, Tag } from 'antd';
import { ArrowLeftOutlined, BulbOutlined } from '@ant-design/icons';

import { GoalProgressCard } from '../components/dashboard/GoalProgressCard';
import { LearningInsightCard } from '../components/dashboard/LearningInsightCard';
import { MasteryOverview } from '../components/dashboard/MasteryOverview';
import { ProfileEvidenceDrawer } from '../components/dashboard/ProfileEvidenceDrawer';
import { ProfileWaitingCard } from '../components/dashboard/ProfileOverviewCard';
import { WeakPointCard } from '../components/dashboard/WeakPointCard';
import {
  trendView, masterySummary, percent,
} from '../features/dashboard/profileViewModel';
import { generateProfileInsight, getLearnerProfileOverview } from '../services/api';
import type { LearnerProfileOverview, ProfileInsight, ProfileMasteryItem, ProfileWeakPoint } from '../services/api';

const trendRows = (profile: LearnerProfileOverview): Array<{ name: string; from: number; to: number; tone: string; text: string }> => {
  const rows = profile.mastery_overview.flatMap(area => [area, ...area.children]);
  return rows
    .filter(item => typeof item.trend === 'number' && Math.abs(item.trend) >= 0.01)
    .sort((left, right) => (right.trend || 0) - (left.trend || 0))
    .map(item => ({
      name: item.name,
      from: percent(item.score - (item.trend || 0)),
      to: percent(item.score),
      tone: (item.trend || 0) > 0 ? 'up' : 'down',
      text: trendView(item.trend).text,
    }));
};

const LearningProfilePage: React.FC = () => {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<LearnerProfileOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [aiInsight, setAiInsight] = useState<ProfileInsight | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [evidencePoint, setEvidencePoint] = useState<ProfileWeakPoint | null>(null);
  const requestVersion = useRef(0);

  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    setFailed(false);
    try {
      const next = await getLearnerProfileOverview();
      if (version !== requestVersion.current) return;
      setProfile(next);
      setAiInsight(null);
      setGenerateError(null);
    } catch {
      if (version === requestVersion.current) {
        setFailed(true);
        message.error('学习画像暂时没有加载成功');
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [message]);

  useEffect(() => { void load(); return () => { requestVersion.current += 1; }; }, [load]);

  const insights = useMemo(() => (profile ? trendRows(profile) : []), [profile]);
  const summary = useMemo(() => masterySummary(profile?.mastery_overview || []), [profile?.mastery_overview]);
  const insight = aiInsight?.text ? aiInsight : profile?.insight || null;

  const askAi = useCallback(async () => {
    setGenerating(true);
    setGenerateError(null);
    try {
      setAiInsight(await generateProfileInsight());
    } catch {
      setGenerateError('AI 摘要暂时没有生成成功，下面仍然是你真实的画像数据。');
    } finally {
      setGenerating(false);
    }
  }, []);

  if (loading) return <Skeleton active paragraph={{ rows: 14 }} />;
  if (failed || !profile) return <div className="empty-guide">
    <h2>学习画像暂时没有加载成功</h2>
    <p>学习记录仍然安全保存，可以稍后重试。</p>
    <Button type="primary" onClick={() => void load()}>重新加载</Button>
  </div>;

  return <main className="learning-profile-page">
    <header className="profile-page-heading">
      <div>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>回到今天</Button>
        <span className="dashboard-kicker">Learning profile · 读时聚合</span>
        <h1>我的学习画像</h1>
        <p>
          {profile.current_focus.length
            ? `${profile.current_focus[0].name} · ${profile.mastery_overview[0]?.status_label || '学习中'}`
            : '等待学习记录'}
          {profile.focus_points.length
            ? `　当前重点：${profile.focus_points.slice(0, 5).map(item => item.name).join('、')}`
            : ''}
        </p>
      </div>
      <Tag bordered={false}>更新于 {new Date(profile.computed_at).toLocaleString('zh-CN')}</Tag>
    </header>

    {profile.is_empty ? <ProfileWaitingCard
      hint={profile.empty_hint || '开始一次学习、练习或复习后，系统会逐步了解你的学习状态。'}
      onStart={() => navigate('/learn')}
      onImport={() => navigate('/upload')}
    /> : <>
      <section className="profile-summary-grid" aria-label="画像总览">
        <div><span>已学习知识点</span><strong>{summary.total}</strong></div>
        <div><span>掌握良好</span><strong>{summary.mastered}</strong></div>
        <div><span>学习中</span><strong>{summary.learning}</strong></div>
        <div><span>薄弱知识</span><strong>{summary.weak}</strong></div>
      </section>

      {insight ? <LearningInsightCard
        insight={insight}
        generating={generating}
        generateError={generateError}
        onGenerate={() => void askAi()}
        onShowEvidence={() => setEvidencePoint(profile.weak_points[0] || null)}
        onStart={() => navigate('/learn')}
      /> : null}

      <div className="profile-page-grid">
        <section className="dashboard-section" aria-labelledby="profile-mastery-title">
          <header className="dashboard-section-heading">
            <div><span className="dashboard-kicker">Mastery</span><h2 id="profile-mastery-title">知识掌握</h2></div>
            <span>阈值：30% 之下未掌握 · 70% 以上已掌握 · 85% 以上熟练</span>
          </header>
          <MasteryOverview
            areas={profile.mastery_overview}
            onOpenArea={(item: ProfileMasteryItem) => item.workspace_id && navigate(`/knowledge/${item.workspace_id}`)}
          />
        </section>

        <section className="dashboard-section" aria-labelledby="profile-weak-title">
          <header className="dashboard-section-heading">
            <div><span className="dashboard-kicker">Need attention</span><h2 id="profile-weak-title">薄弱知识点</h2></div>
            <span>按薄弱分排序，每条都可展开依据</span>
          </header>
          {profile.weak_points.length
            ? <div className="profile-weak-list">{profile.weak_points.map((point, index) => <WeakPointCard
              key={point.knowledge_point_id}
              point={point}
              rank={index + 1}
              onAction={navigate}
              onShowEvidence={setEvidencePoint}
            />)}</div>
            : <div className="dashboard-empty"><p>目前没有达到薄弱阈值的知识点。</p><Button onClick={() => navigate('/practice')}>做一次练习</Button></div>}
        </section>
      </div>

      <div className="profile-page-grid">
        <section className="dashboard-section" aria-labelledby="profile-errors-title">
          <header className="dashboard-section-heading">
            <div><span className="dashboard-kicker">Common errors</span><h2 id="profile-errors-title">常见错误</h2></div>
            <span>来自错题记录的错误原因聚合</span>
          </header>
          {profile.common_errors.length ? <ul className="profile-error-list">{profile.common_errors.map(item => <li key={`${item.area}-${item.pattern}`}>
            <div><strong>{item.area}</strong><p>{item.pattern}</p></div>
            <Tag bordered={false}>{item.count} 次</Tag>
          </li>)}</ul> : <div className="dashboard-empty dashboard-empty-compact"><p>还没有记录错误原因的错题。做错的题目会带着原因出现在这里。</p></div>}
        </section>

        <section className="dashboard-section" aria-labelledby="profile-trend-title">
          <header className="dashboard-section-heading">
            <div><span className="dashboard-kicker">Trend</span><h2 id="profile-trend-title">最近进步</h2></div>
            <span>对比 {profile.trend_window_days} 天前</span>
          </header>
          {insights.length ? <ul className="profile-trend-list">{insights.map(row => <li key={row.name}>
            <strong>{row.name}</strong>
            <span>{row.from}% → {row.to}%</span>
            <span className={`profile-trend is-${row.tone}`}>{row.text}</span>
          </li>)}</ul> : <div className="dashboard-empty dashboard-empty-compact"><p>还没有可对比的掌握度变化。</p></div>}
        </section>
      </div>

      <div className="profile-page-grid">
        <GoalProgressCard goals={profile.goals} onOpenReport={() => navigate('/report')} />
        <section className="dashboard-section" aria-labelledby="profile-preference-title">
          <header className="dashboard-section-heading">
            <div><span className="dashboard-kicker">Preferences</span><h2 id="profile-preference-title">学习偏好</h2></div>
            <Button type="link" onClick={() => navigate('/settings')}>去设置</Button>
          </header>
          <div className="profile-preference">
            <div>
              <h4><BulbOutlined /> 你的设置</h4>
              <ul>
                <li>每日学习目标：{profile.daily_goal_minutes} 分钟</li>
                <li>每日复习目标：{profile.daily_review_target} 张卡片</li>
                <li>每周学习天数：{profile.weekly_goal_days} 天</li>
                <li>默认讲解方式：{profile.preferred_mode === 'deep' ? '深入讲解' : '通俗讲解'}</li>
                <li>时区：{profile.timezone_name}</li>
              </ul>
            </div>
            <div>
              <h4>系统观察</h4>
              {profile.observations.notes.length
                ? <ul>{profile.observations.notes.map(note => <li key={note}>{note}</li>)}</ul>
                : <p className="profile-preference-empty">积累几次学习会话后，这里会出现系统观察。</p>}
            </div>
          </div>
        </section>
      </div>
    </>}

    <ProfileEvidenceDrawer
      open={Boolean(evidencePoint)}
      point={evidencePoint}
      onClose={() => setEvidencePoint(null)}
      onAction={path => { setEvidencePoint(null); navigate(path); }}
    />
  </main>;
};

export default LearningProfilePage;

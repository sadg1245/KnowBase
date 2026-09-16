import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Segmented, Skeleton, Tag } from 'antd';
import { BulbOutlined, LeftOutlined, RightOutlined, SettingOutlined } from '@ant-design/icons';

import { EvidenceDrawer } from '../components/report/EvidenceDrawer';
import { GoalEditor, toGlobalGoalPayload, type GlobalGoalForm, type WorkspaceGoalForm } from '../components/report/GoalEditor';
import { ReportTrend } from '../components/report/ReportTrend';
import { WeaknessChanges } from '../components/report/WeaknessChanges';
import { moveAnchorDate, periodRangeLabel, reportMetricCards, suggestionCopy } from '../features/report/reportViewModel';
import {
  deleteWorkspaceGoal, generateReportSuggestion, getLearningGoals, getNaturalLearningReport,
  getReportEvidence, getWorkspaces, updateGlobalGoals, updateWorkspaceGoal,
} from '../services/api';
import type {
  LearningGoals, LearningReport, PeriodType, ReportEvidenceItem, Workspace,
} from '../services/api';

const today = () => new Date().toLocaleDateString('sv-SE');
const futureDate = () => {
  const date = new Date();
  date.setFullYear(date.getFullYear() + 1);
  return date.toLocaleDateString('sv-SE');
};

const LearningReportPage: React.FC = () => {
  const { message } = App.useApp();
  const [period, setPeriod] = useState<PeriodType>('week');
  const [anchorDate, setAnchorDate] = useState(today);
  const [report, setReport] = useState<LearningReport | null>(null);
  const [goals, setGoals] = useState<LearningGoals | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [suggesting, setSuggesting] = useState(false);
  const [goalOpen, setGoalOpen] = useState(false);
  const [goalSaving, setGoalSaving] = useState(false);
  const [goalError, setGoalError] = useState<string>();
  const [evidenceMetric, setEvidenceMetric] = useState<{ metric: string; label: string } | null>(null);
  const [evidenceItems, setEvidenceItems] = useState<ReportEvidenceItem[]>([]);
  const [evidenceCursor, setEvidenceCursor] = useState<string | null>();
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const requestVersion = useRef(0);
  const evidenceVersion = useRef(0);

  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    try {
      const [nextReport, nextGoals, nextWorkspaces] = await Promise.all([
        getNaturalLearningReport(period, anchorDate), getLearningGoals(), getWorkspaces(),
      ]);
      if (version !== requestVersion.current) return;
      setReport(nextReport);
      setGoals(nextGoals);
      setWorkspaces(nextWorkspaces);
    } catch {
      if (version === requestVersion.current) message.error('学习报告暂时没有加载成功');
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [anchorDate, message, period]);

  useEffect(() => { void load(); return () => { requestVersion.current += 1; }; }, [load]);

  const loadEvidence = useCallback(async (cursor?: string | null, append = false) => {
    if (!evidenceMetric) return;
    const version = append ? evidenceVersion.current : ++evidenceVersion.current;
    setEvidenceLoading(true);
    try {
      const page = await getReportEvidence(period, anchorDate, evidenceMetric.metric, cursor || undefined);
      if (version !== evidenceVersion.current) return;
      setEvidenceItems(current => append ? [...current, ...page.items] : page.items);
      setEvidenceCursor(page.next_cursor);
    } catch {
      if (version === evidenceVersion.current) message.error('指标依据暂时没有加载成功');
    } finally {
      if (version === evidenceVersion.current) setEvidenceLoading(false);
    }
  }, [anchorDate, evidenceMetric, message, period]);

  useEffect(() => {
    setEvidenceItems([]);
    setEvidenceCursor(undefined);
    if (evidenceMetric) void loadEvidence();
  }, [evidenceMetric, loadEvidence]);

  const globalInitial = useMemo<GlobalGoalForm>(() => ({
    minutes: goals?.global.daily_minutes?.target || 25,
    reviews: goals?.global.daily_reviews?.target || 10,
    weeklyDays: goals?.global.weekly_days?.target || 5,
    targetDate: goals?.global.overall_mastery?.target_date || futureDate(),
    timezoneName: goals?.timezone_name || 'Asia/Shanghai',
  }), [goals]);
  const workspaceInitial = useMemo<WorkspaceGoalForm[]>(() => {
    const byWorkspace = new Map((goals?.workspaces || []).map(item => [item.workspace_id, item]));
    return workspaces.map(item => {
      const goal = byWorkspace.get(item.id);
      return { id: item.id, name: item.name, targetMastery: goal?.target, targetDate: goal?.target_date || undefined };
    });
  }, [goals?.workspaces, workspaces]);

  const saveGoals = async (global: GlobalGoalForm, workspaceRows: WorkspaceGoalForm[]) => {
    setGoalSaving(true);
    setGoalError(undefined);
    try {
      await updateGlobalGoals(toGlobalGoalPayload(global));
      const originals = new Map(workspaceInitial.map(item => [item.id, item]));
      const changes = workspaceRows.flatMap(item => {
        const original = originals.get(item.id);
        const changed = original?.targetMastery !== item.targetMastery || original?.targetDate !== item.targetDate;
        if (!changed) return [];
        if (item.targetMastery == null && !item.targetDate) return original?.targetMastery != null ? [deleteWorkspaceGoal(item.id)] : [];
        if (item.targetMastery == null || !item.targetDate) throw new Error(`请完整填写「${item.name}」的掌握度和日期`);
        return [updateWorkspaceGoal(item.id, { target_mastery: item.targetMastery, target_date: item.targetDate })];
      });
      await Promise.all(changes);
      await load();
      setGoalOpen(false);
      message.success('学习目标已保存');
    } catch (reason: any) {
      setGoalError(reason?.response?.data?.detail || reason?.message || '部分目标没有保存，请检查后重试');
    } finally {
      setGoalSaving(false);
    }
  };

  const requestSuggestion = async () => {
    setSuggesting(true);
    try {
      const suggestion = await generateReportSuggestion(period, anchorDate);
      setReport(current => current ? { ...current, suggestion } : current);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '学习建议生成失败，报告数据不受影响');
      await load();
    } finally { setSuggesting(false); }
  };

  if (loading && !report) return <Skeleton active paragraph={{ rows: 12 }} />;
  if (!report) return <div className="dashboard-load-error"><h2>报告暂时无法显示</h2><Button type="primary" onClick={() => void load()}>重新加载</Button></div>;
  const cards = reportMetricCards(report);

  return <main className="report-page">
    <header className="report-heading">
      <div><span className="page-eyebrow">Reflection · 看见积累</span><h1>学习报告</h1><p>每一个数字都能回到实际学习记录，不从结果倒推过程。</p></div>
      <Button icon={<SettingOutlined />} onClick={() => setGoalOpen(true)}>调整学习目标</Button>
    </header>
    <div className="report-period-bar">
      <Segmented value={period} onChange={value => setPeriod(value as PeriodType)} options={[
        { label: '日', value: 'day' }, { label: '周', value: 'week' }, { label: '月', value: 'month' },
      ]} />
      <div><Button aria-label="上一周期" icon={<LeftOutlined />} onClick={() => setAnchorDate(value => moveAnchorDate(value, period, -1))} />
        <span>{periodRangeLabel(report.period.local_start, report.period.local_end)}<small>{report.period.timezone_name}</small></span>
        <Button aria-label="下一周期" icon={<RightOutlined />} disabled={anchorDate >= today()} onClick={() => setAnchorDate(value => moveAnchorDate(value, period, 1))} /></div>
    </div>

    <section className="report-metric-grid">{cards.map(card => <button key={card.metric} onClick={() => setEvidenceMetric({ metric: card.metric, label: card.label })}>
      <span>{card.label}</span><strong>{card.value}</strong><small className={`is-${card.comparison.tone}`}>{card.comparison.text}</small><i>查看依据 →</i>
    </button>)}</section>

    <div className="report-main-grid">
      <ReportTrend trend={report.trend} />
      <div className="report-side-stack">
        <WeaknessChanges changes={report.weakness_changes} onOpen={() => setEvidenceMetric({ metric: 'weakness_change', label: '薄弱知识变化' })} />
        <section className="report-suggestion">
          <div><span className="dashboard-kicker">AI study note</span><h2>下一步学习建议</h2></div>
          {report.suggestion?.status === 'ready' ? <p>{report.suggestion.suggestion}</p> : <p>{suggestionCopy(report.suggestion)}</p>}
          {report.suggestion?.model ? <Tag bordered={false}>{report.suggestion.model}</Tag> : null}
          {report.suggestion?.status !== 'ready' ? <Button type="primary" icon={<BulbOutlined />} loading={suggesting} onClick={() => void requestSuggestion()}>{report.suggestion?.status === 'failed' ? '重新生成建议' : '生成学习建议'}</Button> : <Button onClick={() => void requestSuggestion()} loading={suggesting}>按当前数据重新生成</Button>}
        </section>
      </div>
    </div>

    <section className="report-goal-strip">
      <div><span>每日学习</span><strong>{goals?.global.daily_minutes.actual || 0}/{goals?.global.daily_minutes.target || 0} 分钟</strong></div>
      <div><span>每日复习</span><strong>{goals?.global.daily_reviews.actual || 0}/{goals?.global.daily_reviews.target || 0} 张</strong></div>
      <div><span>本周学习</span><strong>{goals?.global.weekly_days.actual || 0}/{goals?.global.weekly_days.target || 0} 天</strong></div>
      <Button type="link" onClick={() => setGoalOpen(true)}>编辑目标</Button>
    </section>

    <EvidenceDrawer open={Boolean(evidenceMetric)} title={evidenceMetric?.label || ''} items={evidenceItems} loading={evidenceLoading}
      hasMore={Boolean(evidenceCursor)} onLoadMore={() => void loadEvidence(evidenceCursor, true)} onClose={() => setEvidenceMetric(null)} />
    <GoalEditor open={goalOpen} initial={globalInitial} workspaces={workspaceInitial} saving={goalSaving} error={goalError}
      onClose={() => { if (!goalSaving) setGoalOpen(false); }} onSave={(global, workspaceRows) => void saveGoals(global, workspaceRows)} />
  </main>;
};

export default LearningReportPage;

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  attemptAccuracyLabel, attemptMarks, confidenceView, dashboardProfileView, goalPlan,
  goalProgressView, insightEvidenceLines, lastStudiedLabel, masteryStatusMeta,
  masteryStatusOf, masterySummary, percent, primaryWeakAction, reviewSummary,
  topMastery, topWeakPoints, trendView, weakPointActionPath,
} from '../src/features/dashboard/profileViewModel';
import type {
  DashboardProfile, ProfileMasteryItem, ProfileWeakPoint,
} from '../src/services/api';

const masteryItem = (overrides: Partial<ProfileMasteryItem> = {}): ProfileMasteryItem => ({
  name: 'RAG', score: 0.76, status: 'mastered', status_label: '已掌握',
  workspace_id: 'ws-1', knowledge_point_count: 4, trend: 0.13, confidence: 0.9,
  confidence_note: null, last_evidence_at: '2026-09-17T00:00:00+00:00', children: [],
  ...overrides,
});

const weakPoint = (overrides: Partial<ProfileWeakPoint> = {}): ProfileWeakPoint => ({
  knowledge_point_id: 'kp-1', name: 'LangGraph State', workspace_id: 'ws-1', area: 'AI Agent 开发',
  mastery: 0.38, mastery_status: 'weak', mastery_status_label: '薄弱',
  weakness_score: 0.81, weakness_band: 'priority', weakness_band_label: '优先处理',
  reasons: ['最近 5 题答对 2 题', '仍有 2 道错题未掌握'],
  actions: [
    { type: 'review', label: '复习', path: '/review' },
    { type: 'practice', label: '专项练习', path: '/practice?knowledge_point_id=kp-1' },
    { type: 'explain', label: '让 AI 讲解', path: '/learn?prompt=state' },
  ],
  evidence: {
    recent_attempts: [
      { correct: true, submitted_at: '2026-09-17T03:00:00+00:00', duration_seconds: 90 },
      { correct: false, submitted_at: '2026-09-17T02:00:00+00:00', duration_seconds: 120 },
      { correct: null, submitted_at: null, duration_seconds: 0 },
    ],
    attempt_accuracy: 0.4,
    recent_reviews: [
      { rating: 2, label: '模糊', reviewed_at: '2026-09-16T02:00:00+00:00' },
      { rating: 1, label: '忘记', reviewed_at: '2026-09-15T02:00:00+00:00' },
    ],
    mistake_count: 2,
    repeat_error_count: 3,
    mistake_patterns: [{ pattern: 'State 与普通局部变量混淆', count: 3, last_wrong_at: null }],
    last_studied_at: '2026-09-17T03:00:00+00:00',
    stale_days: 2,
    state_note: '掌握明显不足，建议优先处理',
    components: { accuracy: 60, repeat_error: 50, review_feedback: 100, response_time: 0, recency: 20 },
  },
  ...overrides,
});

test('mastery_status_of_the_view_model_matches_the_backend_bands', () => {
  assert.equal(masteryStatusOf(0.29), 'not_mastered');
  assert.equal(masteryStatusOf(0.3), 'weak');
  assert.equal(masteryStatusOf(0.5), 'learning');
  assert.equal(masteryStatusOf(0.7), 'mastered');
  assert.equal(masteryStatusOf(0.85), 'proficient');
  assert.equal(masteryStatusOf(undefined), 'not_mastered');
  assert.equal(masteryStatusMeta('weak').label, '薄弱');
  assert.equal(masteryStatusMeta(undefined, 0.9).label, '熟练');
  assert.equal(percent(0.585), 59);
  assert.equal(percent(undefined), 0);
  assert.equal(percent(1.4), 100);
});

test('trend and confidence read as directional copy instead of raw numbers', () => {
  assert.deepEqual(trendView(0.13), { text: '↑ 13 个百分点', tone: 'up' });
  assert.deepEqual(trendView(-0.02), { text: '↓ 2 个百分点', tone: 'down' });
  assert.deepEqual(trendView(0), { text: '→ 持平', tone: 'flat' });
  assert.deepEqual(trendView(null), { text: '暂无趋势', tone: 'unknown' });
  assert.deepEqual(confidenceView({ confidence: 0.55, confidence_note: '最近 40 天没有有效复习或练习' }), {
    text: '当前置信度 55%', note: '最近 40 天没有有效复习或练习',
  });
  assert.equal(confidenceView({ confidence: null, confidence_note: null }), null);
});

test('top lists sort by score and weakness without mutating the payload', () => {
  const items = [
    masteryItem({ name: 'LangGraph', score: 0.41, status: 'weak' }),
    masteryItem({ name: 'RAG', score: 0.76 }),
    masteryItem({ name: 'FastAPI', score: 0.72 }),
  ];
  assert.deepEqual(topMastery(items, 2).map(item => item.name), ['RAG', 'FastAPI']);
  assert.deepEqual(items.map(item => item.name), ['LangGraph', 'RAG', 'FastAPI']);

  const weak = [
    weakPoint({ knowledge_point_id: 'a', name: 'A', weakness_score: 0.4 }),
    weakPoint({ knowledge_point_id: 'b', name: 'B', weakness_score: 0.9 }),
  ];
  assert.deepEqual(topWeakPoints(weak, 1).map(point => point.name), ['B']);
});

test('weak point actions resolve to the most actionable path', () => {
  const point = weakPoint();
  assert.equal(weakPointActionPath(point, 'review'), '/review');
  assert.deepEqual(primaryWeakAction(point), { label: '专项练习', path: '/practice?knowledge_point_id=kp-1' });

  const reviewOnly = weakPoint({ actions: [{ type: 'review', label: '复习', path: null }] });
  assert.equal(primaryWeakAction(reviewOnly), null);
});

test('evidence copy turns attempts, reviews, and recency into readable lines', () => {
  const point = weakPoint();
  assert.deepEqual(attemptMarks(point.evidence), ['✓', '×', '·']);
  assert.equal(attemptAccuracyLabel(point.evidence), '正确率 40%');
  assert.equal(reviewSummary(point.evidence), '模糊 / 忘记');
  assert.equal(lastStudiedLabel(point.evidence), '最后有效学习：2 天前');
  assert.equal(lastStudiedLabel({ ...point.evidence, recent_reviews: [], attempt_accuracy: null, last_studied_at: null, stale_days: null }), '还没有有效学习记录');
  assert.equal(lastStudiedLabel({ ...point.evidence, stale_days: 0 }), '今天有过学习');
  assert.equal(reviewSummary({ ...point.evidence, recent_reviews: [] }), '还没有复习记录');
});

test('insight evidence lines stay on deterministic numbers', () => {
  const lines = insightEvidenceLines({
    text: '随便一句话', generated_by: 'rules', based_on: ['mastery_trend'],
    evidence: {
      trend_window_days: 14,
      mastery: [{ name: 'RAG', score: 0.76, trend: 0.13 }],
      weak_points: [{ name: 'LangGraph State', mastery: 0.38, reasons: ['最近 5 题答对 2 题'] }],
    },
  });
  assert.deepEqual(lines, [
    '最近 14 天 RAG 掌握度 76%（↑ 13 个百分点）',
    '薄弱点 LangGraph State 掌握度 38%：最近 5 题答对 2 题',
  ]);
  assert.deepEqual(insightEvidenceLines(null), []);
});

test('goal helpers pick the goal with a topic plan and describe its progress', () => {
  const goals = [
    {
      id: 'g1', title: '每日学习 30 分钟', scope_type: 'global' as const, metric: 'daily_minutes',
      target_value: 30, actual: 42, progress: 1, status: 'completed', target_date: null,
      workspace_id: null, completed: [], learning: [], pending: [],
    },
    {
      id: 'g2', title: '掌握「AI Agent 开发」', scope_type: 'workspace' as const, metric: 'workspace_mastery',
      target_value: 80, actual: 56.67, progress: 0.7084, status: 'in_progress', target_date: '2026-12-31',
      workspace_id: 'ws-1', completed: ['Prompt Engineering'], learning: ['RAG'], pending: ['LangGraph'],
    },
  ];
  assert.equal(goalPlan(goals)?.id, 'g2');
  assert.deepEqual(goalProgressView(goals[1]), { percent: 71, label: '推进中', tone: 'steady' });
  assert.deepEqual(goalProgressView(goals[0]), { percent: 100, label: '已完成', tone: 'good' });
  assert.equal(goalPlan([]), null);
});

test('mastery summary counts knowledge points, not areas', () => {
  const areas = [
    masteryItem({ children: [
      masteryItem({ name: 'RAG', score: 0.9, status: 'proficient', children: [] }),
      masteryItem({ name: 'Reranker', score: 0.58, status: 'learning', children: [] }),
      masteryItem({ name: 'State', score: 0.2, status: 'not_mastered', children: [] }),
    ] }),
  ];
  assert.deepEqual(masterySummary(areas), { total: 3, mastered: 1, learning: 1, weak: 1 });
});

test('dashboard profile view trims the payload into the home page shape', () => {
  const profile = {
    is_empty: false, empty_hint: null, current_focus: 'AI Agent 开发',
    focus_points: [{ name: 'RAG' }, { name: 'LangGraph' }],
    mastery: [
      masteryItem({ name: 'A', score: 0.1 }), masteryItem({ name: 'B', score: 0.9 }),
      masteryItem({ name: 'C', score: 0.5 }), masteryItem({ name: 'D', score: 0.4 }),
      masteryItem({ name: 'E', score: 0.3 }),
    ],
    weak_points: [weakPoint({ knowledge_point_id: 'a', name: 'A', weakness_score: 0.9 }), weakPoint({ knowledge_point_id: 'b', name: 'B', weakness_score: 0.5 })],
    insight: { text: '继续补 State。', generated_by: 'rules', based_on: [], evidence: {} },
    recent_learning: [
      { date: '2026-09-18', label: '今天', minutes: 32, activity_count: 2, last_studied_at: null, areas: [] },
      { date: '2026-09-17', label: '昨天', minutes: 45, activity_count: 3, last_studied_at: null, areas: [] },
      { date: '2026-09-16', label: '9 月 16 日', minutes: 10, activity_count: 1, last_studied_at: null, areas: [] },
      { date: '2026-09-15', label: '9 月 15 日', minutes: 5, activity_count: 1, last_studied_at: null, areas: [] },
    ],
    observations: { notes: ['平均学习会话约 43 分钟'] },
    goals: [],
  } as unknown as DashboardProfile;

  const view = dashboardProfileView(profile);
  assert.equal(view.isReady, true);
  assert.equal(view.focusName, 'AI Agent 开发');
  assert.deepEqual(view.mastery.map(item => item.name), ['B', 'C', 'D', 'E']);
  assert.equal(view.weakPoints.length, 2);
  assert.equal(view.recentLearning.length, 3);
  assert.deepEqual(view.observations, ['平均学习会话约 43 分钟']);
  assert.equal(view.insight?.text, '继续补 State。');

  const empty = dashboardProfileView({
    is_empty: true, empty_hint: null, current_focus: null, focus_points: [], mastery: [],
    weak_points: [], insight: { text: '', generated_by: 'rules', based_on: [], evidence: {} },
    recent_learning: [], observations: { notes: [] }, goals: [],
  } as unknown as DashboardProfile);
  assert.equal(empty.isReady, false);
  assert.equal(empty.isEmpty, true);
  assert.match(empty.emptyHint, /开始一次学习/);
  assert.equal(empty.insight, null);
  assert.equal(dashboardProfileView(null).isReady, false);
});

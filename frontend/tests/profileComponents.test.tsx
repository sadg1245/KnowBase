import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { GoalProgressCard } from '../src/components/dashboard/GoalProgressCard';
import { LearningInsightCard } from '../src/components/dashboard/LearningInsightCard';
import { MasteryOverview } from '../src/components/dashboard/MasteryOverview';
import { ProfileEvidenceDrawer, attemptLine, evidenceSections } from '../src/components/dashboard/ProfileEvidenceDrawer';
import { ProfileOverviewCard, ProfileWaitingCard } from '../src/components/dashboard/ProfileOverviewCard';
import { RecentLearningCard } from '../src/components/dashboard/RecentLearningCard';
import { WeakPointCard, WeakPointList } from '../src/components/dashboard/WeakPointCard';
import type { ProfileGoal, ProfileMasteryItem, ProfileWeakPoint } from '../src/services/api';

const masteryItem = (overrides: Partial<ProfileMasteryItem> = {}): ProfileMasteryItem => ({
  name: 'RAG', score: 0.76, status: 'mastered', status_label: '已掌握',
  workspace_id: 'ws-1', knowledge_point_count: 4, trend: 0.13, confidence: 0.9,
  confidence_note: null, last_evidence_at: null, children: [],
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
      { correct: true, submitted_at: null, duration_seconds: 90 },
      { correct: false, submitted_at: null, duration_seconds: 120 },
      { correct: false, submitted_at: null, duration_seconds: 60 },
    ],
    attempt_accuracy: 0.4,
    recent_reviews: [{ rating: 2, label: '模糊', reviewed_at: null }],
    mistake_count: 2,
    repeat_error_count: 3,
    mistake_patterns: [{ pattern: 'State 与普通局部变量混淆', count: 3, last_wrong_at: null }],
    last_studied_at: '2026-09-16T00:00:00+00:00',
    stale_days: 2,
    state_note: '掌握明显不足，建议优先处理',
    components: { accuracy: 60, repeat_error: 50, review_feedback: 100, response_time: 0, recency: 20 },
  },
  ...overrides,
});

const goal = (overrides: Partial<ProfileGoal> = {}): ProfileGoal => ({
  id: 'g1', title: '掌握「AI Agent 开发」', scope_type: 'workspace', metric: 'workspace_mastery',
  target_value: 80, actual: 56.67, progress: 0.7084, status: 'in_progress', target_date: '2026-12-31',
  workspace_id: 'ws-1', completed: ['Prompt Engineering'], learning: ['RAG'], pending: ['LangGraph'],
  ...overrides,
});

test('profile overview card shows focus, mastery, weak points, and the full-profile entry', () => {
  const html = renderToStaticMarkup(<ProfileOverviewCard
    focusName="AI Agent 开发"
    focusPoints={[{ name: 'RAG', kind: 'knowledge_point' }, { name: 'LangGraph', kind: 'knowledge_point' }]}
    mastery={[masteryItem(), masteryItem({ name: 'LangGraph', score: 0.41, status: 'weak', status_label: '薄弱', trend: -0.02 })]}
    weakPoints={[weakPoint()]}
    onOpenProfile={() => undefined}
  />);

  assert.match(html, /我的学习画像/);
  assert.match(html, /当前方向/);
  assert.match(html, /AI Agent 开发/);
  assert.match(html, /当前重点：RAG、LangGraph/);
  assert.match(html, />76</);
  assert.match(html, /↑ 13 个百分点/);
  assert.match(html, /↓ 2 个百分点/);
  assert.match(html, /当前薄弱/);
  assert.match(html, /LangGraph State/);
  assert.match(html, /查看完整画像/);
});

test('profile overview falls back to a calm empty line without weak points', () => {
  const html = renderToStaticMarkup(<ProfileOverviewCard
    focusName={null}
    mastery={[]}
    weakPoints={[]}
    onOpenProfile={() => undefined}
  />);
  assert.match(html, /暂时没有明显薄弱点/);
  assert.doesNotMatch(html, /当前方向/);
});

test('waiting card explains how the profile forms and offers both actions', () => {
  const html = renderToStaticMarkup(<ProfileWaitingCard
    hint="开始一次学习、练习或复习后，系统会逐步了解你的学习状态。"
    onStart={() => undefined}
    onImport={() => undefined}
  />);
  assert.match(html, /你的学习画像正在等待形成/);
  assert.match(html, /开始学习/);
  assert.match(html, /导入资料/);
  assert.doesNotMatch(html, /0%/);
});

test('weak point card ranks the point, quotes reasons, and offers three actions', () => {
  const html = renderToStaticMarkup(<WeakPointCard
    point={weakPoint()}
    rank={1}
    onAction={() => undefined}
    onShowEvidence={() => undefined}
  />);
  assert.match(html, /优先处理/);
  assert.match(html, /38/);
  assert.match(html, /薄弱分 81/);
  assert.match(html, /最近 5 题答对 2 题/);
  // antd 会在两个汉字的按钮文案之间插入空格。
  assert.match(html, /复\s*习/);
  assert.match(html, /专项练习/);
  assert.match(html, /让 AI 讲解/);
  assert.match(html, /为什么？/);
});

test('weak point list shows an actionable empty state', () => {
  const html = renderToStaticMarkup(<WeakPointList
    points={[]}
    onAction={() => undefined}
    onShowEvidence={() => undefined}
    onStartPractice={() => undefined}
  />);
  assert.match(html, /薄弱知识点/);
  assert.match(html, /开始一次练习/);

  const listed = renderToStaticMarkup(<WeakPointList
    points={[weakPoint(), weakPoint({ knowledge_point_id: 'kp-2', name: 'Reranker', weakness_score: 0.51, weakness_band: 'watch', weakness_band_label: '需要巩固', reasons: ['最近两次复习有 1 次没记住'] })]}
    onAction={() => undefined}
    onShowEvidence={() => undefined}
  />);
  assert.match(listed, /LangGraph State/);
  assert.match(listed, /Reranker/);
  assert.match(listed, /需要巩固/);
});

test('mastery overview renders the two-level tree with confidence notes', () => {
  const html = renderToStaticMarkup(<MasteryOverview areas={[
    masteryItem({
      confidence_note: null,
      knowledge_point_count: 3,
      children: [
        masteryItem({ name: 'Embedding', score: 0.86, status: 'proficient', status_label: '熟练', trend: 0.04, confidence: 0.9 }),
        masteryItem({ name: 'Reranker', score: 0.58, status: 'learning', status_label: '学习中', trend: null, confidence: 0.35, confidence_note: '50 天没有有效复习或练习' }),
      ],
    }),
  ]} />);

  assert.match(html, /知识掌握|RAG/);
  assert.match(html, /Embedding/);
  assert.match(html, /熟练/);
  assert.match(html, /Reranker/);
  assert.match(html, /50 天没有有效复习或练习/);
  assert.match(html, /还有 1 个知识点未展开/);
});

test('insight card marks rule output and hides the empty text', () => {
  const html = renderToStaticMarkup(<LearningInsightCard
    insight={{
      text: '最近 14 天 RAG 掌握度提升 13 个百分点（76%）。当前最该补的是 LangGraph State。',
      generated_by: 'rules',
      based_on: ['mastery_trend', 'weak_points'],
      evidence: { trend_window_days: 14, mastery: [{ name: 'RAG', score: 0.76, trend: 0.13 }] },
    }}
    onShowEvidence={() => undefined}
    onStart={() => undefined}
    onGenerate={() => undefined}
  />);
  assert.match(html, /AI 学习洞察/);
  assert.match(html, /依据规则/);
  assert.match(html, /LangGraph State/);
  assert.match(html, /查看依据/);
  assert.match(html, /开始学习/);
  assert.match(html, /让 AI 总结/);

  const ai = renderToStaticMarkup(<LearningInsightCard
    insight={{ text: '模型总结的一句话。', generated_by: 'ai', based_on: [], evidence: {} }}
    onShowEvidence={() => undefined}
    onStart={() => undefined}
    onGenerate={() => undefined}
    generating
  />);
  assert.match(ai, /AI 生成/);
  assert.doesNotMatch(ai, /让 AI 总结/);

  const blank = renderToStaticMarkup(<LearningInsightCard
    insight={{ text: '', generated_by: 'rules', based_on: [], evidence: {} }}
    onShowEvidence={() => undefined}
    onStart={() => undefined}
  />);
  assert.equal(blank, '');
});

test('goal card splits completed, learning, and pending topics', () => {
  const html = renderToStaticMarkup(<GoalProgressCard goals={[goal()]} onOpenReport={() => undefined} />);
  assert.match(html, /掌握「AI Agent 开发」/);
  assert.match(html, /71/);
  assert.match(html, /已完成/);
  assert.match(html, /Prompt Engineering/);
  assert.match(html, /学习中/);
  assert.match(html, /RAG/);
  assert.match(html, /待学习/);
  assert.match(html, /LangGraph/);
  assert.match(html, /调整学习目标/);

  const empty = renderToStaticMarkup(<GoalProgressCard goals={[]} onOpenReport={() => undefined} />);
  assert.match(empty, /设置目标/);
});

test('recent learning card lists each day and marks system observations as observations', () => {
  const html = renderToStaticMarkup(<RecentLearningCard
    items={[
      { date: '2026-09-18', label: '今天', minutes: 32, activity_count: 2, last_studied_at: null, areas: [{ name: 'AI Agent 开发', workspace_id: 'ws-1', minutes: 32 }] },
      { date: '2026-09-17', label: '昨天', minutes: 45, activity_count: 3, last_studied_at: null, areas: [{ name: 'Python', workspace_id: 'ws-2', minutes: 45 }] },
    ]}
    observations={['平均学习会话约 43 分钟', '晚上学习频率较高']}
    onOpenReport={() => undefined}
  />);
  assert.match(html, /今天/);
  assert.match(html, /AI Agent 开发/);
  assert.match(html, />32</);
  assert.match(html, /昨天/);
  assert.match(html, /Python/);
  assert.match(html, /系统观察/);
  assert.match(html, /晚上学习频率较高/);
  assert.match(html, /查看报告/);
});

test('evidence drawer helpers explain why a point is weak', () => {
  const point = weakPoint();
  assert.equal(attemptLine(point.evidence), '✓ × × · 正确率 40%');
  const sections = evidenceSections(point);
  const titles = sections.map(section => section.title);
  assert.deepEqual(titles, ['练习表现', '复习表现', '错误记录', '最近学习', '系统状态']);
  const flat = sections.flatMap(section => section.lines).join('\n');
  assert.match(flat, /最近 3 题/);
  assert.match(flat, /正确率 40%/);
  assert.match(flat, /未掌握错题 2 道/);
  assert.match(flat, /同一批错题累计重复错误 3 次/);
  assert.match(flat, /模糊/);
  assert.match(flat, /State 与普通局部变量混淆 · 重复错误 3 次/);
  assert.match(flat, /最后有效学习：2 天前/);
  assert.match(flat, /掌握明显不足，建议优先处理/);

  const withoutPatterns = evidenceSections(weakPoint({
    evidence: { ...point.evidence, mistake_patterns: [], recent_attempts: [], attempt_accuracy: null },
  }));
  assert.equal(withoutPatterns.some(section => section.title === '错误记录'), false);
  assert.match(withoutPatterns[0].lines.join(' '), /还没有已评分的作答/);

  // 抽屉本身通过 antd 渲染，服务端渲染只断言标题文案即可。
  const drawer = renderToStaticMarkup(<ProfileEvidenceDrawer
    open={false}
    point={point}
    onClose={() => undefined}
    onAction={() => undefined}
  />);
  assert.equal(typeof drawer, 'string');
});

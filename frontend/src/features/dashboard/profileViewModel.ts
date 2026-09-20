import type {
  DashboardProfile, MasteryStatus, ProfileGoal, ProfileInsight,
  ProfileMasteryItem, ProfileWeakEvidence, ProfileWeakPoint, WeaknessBand,
} from '../../services/api';

export type MasteryTone = 'risk' | 'watch' | 'steady' | 'good' | 'strong';

export const MASTERY_STATUS_META: Record<MasteryStatus, { label: string; tone: MasteryTone; color: string }> = {
  not_mastered: { label: '未掌握', tone: 'risk', color: '#c9564b' },
  weak: { label: '薄弱', tone: 'watch', color: '#c98b37' },
  learning: { label: '学习中', tone: 'steady', color: '#167d8d' },
  mastered: { label: '已掌握', tone: 'good', color: '#3f8f6b' },
  proficient: { label: '熟练', tone: 'strong', color: '#2f6f57' },
};

export const WEAKNESS_BAND_META: Record<WeaknessBand, { label: string; tone: MasteryTone; color: string }> = {
  stable: { label: '暂时稳定', tone: 'good', color: '#3f8f6b' },
  watch: { label: '需要巩固', tone: 'watch', color: '#c98b37' },
  weak: { label: '薄弱', tone: 'watch', color: '#c98b37' },
  priority: { label: '优先处理', tone: 'risk', color: '#c9564b' },
};

/** 与后端 `mastery_band` 一致的阈值，用于后端未给出状态时的本地兜底。 */
export const masteryStatusOf = (score?: number | null): MasteryStatus => {
  const value = typeof score === 'number' ? score : 0;
  if (value < 0.3) return 'not_mastered';
  if (value < 0.5) return 'weak';
  if (value < 0.7) return 'learning';
  if (value < 0.85) return 'mastered';
  return 'proficient';
};

export const masteryStatusMeta = (status?: MasteryStatus | null, score?: number | null) =>
  MASTERY_STATUS_META[status || masteryStatusOf(score)];

export const percent = (value?: number | null): number =>
  Math.round(Math.max(0, Math.min(1, typeof value === 'number' ? value : 0)) * 100);

export type TrendView = { text: string; tone: 'up' | 'down' | 'flat' | 'unknown' };

export const trendView = (trend?: number | null): TrendView => {
  if (typeof trend !== 'number') return { text: '暂无趋势', tone: 'unknown' };
  const points = Math.round(trend * 100);
  if (points > 0) return { text: `↑ ${points} 个百分点`, tone: 'up' };
  if (points < 0) return { text: `↓ ${Math.abs(points)} 个百分点`, tone: 'down' };
  return { text: '→ 持平', tone: 'flat' };
};

export const confidenceView = (
  item: Pick<ProfileMasteryItem, 'confidence' | 'confidence_note'>,
): { text: string; note?: string } | null => {
  if (typeof item.confidence !== 'number') return null;
  return { text: `当前置信度 ${percent(item.confidence)}%`, note: item.confidence_note || undefined };
};

export const sortedMastery = (items: ProfileMasteryItem[] = []): ProfileMasteryItem[] =>
  [...items].sort((left, right) => right.score - left.score || left.name.localeCompare(right.name, 'zh-CN'));

export const topMastery = (items: ProfileMasteryItem[] = [], limit = 4): ProfileMasteryItem[] =>
  sortedMastery(items).slice(0, Math.max(0, limit));

export const topWeakPoints = (items: ProfileWeakPoint[] = [], limit = 3): ProfileWeakPoint[] =>
  [...items]
    .sort((left, right) => right.weakness_score - left.weakness_score || left.name.localeCompare(right.name, 'zh-CN'))
    .slice(0, Math.max(0, limit));

export const weakPointActionPath = (
  point: ProfileWeakPoint,
  type: ProfileWeakPoint['actions'][number]['type'],
): string | null => point.actions.find(action => action.type === type)?.path || null;

/** 首页与画像页的默认动作：优先专项练习，其次复习，最后让 AI 讲解。 */
export const primaryWeakAction = (point: ProfileWeakPoint): { label: string; path: string } | null => {
  for (const type of ['practice', 'review', 'explain'] as const) {
    const action = point.actions.find(item => item.type === type);
    if (action?.path) return { label: action.label, path: action.path };
  }
  const fallback = point.actions.find(action => action.path);
  return fallback?.path ? { label: fallback.label, path: fallback.path } : null;
};

export const attemptMarks = (evidence: ProfileWeakEvidence): string[] =>
  evidence.recent_attempts.map(attempt => (
    attempt.correct === false ? '×' : attempt.correct === true ? '✓' : '·'
  ));

export const attemptAccuracyLabel = (evidence: ProfileWeakEvidence): string =>
  typeof evidence.attempt_accuracy === 'number'
    ? `正确率 ${percent(evidence.attempt_accuracy)}%`
    : '还没有已评分的作答';

export const reviewSummary = (evidence: ProfileWeakEvidence): string =>
  evidence.recent_reviews.length
    ? evidence.recent_reviews.map(review => review.label).join(' / ')
    : '还没有复习记录';

export const lastStudiedLabel = (evidence: ProfileWeakEvidence): string => {
  if (!evidence.last_studied_at) return '还没有有效学习记录';
  if (typeof evidence.stale_days === 'number') {
    if (evidence.stale_days <= 0) return '今天有过学习';
    if (evidence.stale_days === 1) return '最后有效学习：昨天';
    return `最后有效学习：${evidence.stale_days} 天前`;
  }
  return `最后有效学习：${new Date(evidence.last_studied_at).toLocaleDateString('zh-CN')}`;
};

export const goalProgressView = (
  goal: ProfileGoal,
): { percent: number; label: string; tone: 'steady' | 'good' | 'watch' } => ({
  percent: percent(goal.progress),
  label: goal.status === 'completed' ? '已完成' : goal.status === 'in_progress' ? '推进中' : '未开始',
  tone: goal.status === 'completed' ? 'good' : goal.status === 'not_started' ? 'watch' : 'steady',
});

/** 目标卡片优先展示带知识点拆解的目标（已完成 / 学习中 / 待学习）。 */
export const goalPlan = (goals: ProfileGoal[] = []): ProfileGoal | null =>
  goals.find(goal => goal.completed.length || goal.learning.length || goal.pending.length)
  || goals[0]
  || null;

export const masterySummary = (areas: ProfileMasteryItem[] = []) => {
  const points = areas.flatMap(area => (area.children.length ? area.children : [area]));
  return {
    total: points.length,
    mastered: points.filter(point => point.status === 'mastered' || point.status === 'proficient').length,
    learning: points.filter(point => point.status === 'learning').length,
    weak: points.filter(point => point.status === 'weak' || point.status === 'not_mastered').length,
  };
};

/** [查看依据] 只展示确定性指标，不展示模型自由发挥的句子。 */
export const insightEvidenceLines = (insight?: ProfileInsight | null): string[] => {
  const evidence = insight && insight.evidence && typeof insight.evidence === 'object' ? insight.evidence : {};
  const window = typeof evidence.trend_window_days === 'number' ? evidence.trend_window_days : 14;
  const lines: string[] = [];
  const mastery = Array.isArray(evidence.mastery) ? evidence.mastery : [];
  for (const item of mastery.slice(0, 4)) {
    if (!item || typeof item.name !== 'string') continue;
    const trend = typeof item.trend === 'number' ? trendView(item.trend) : null;
    const trendText = trend && trend.tone !== 'unknown' ? `（${trend.text}）` : '';
    lines.push(`最近 ${window} 天 ${item.name} 掌握度 ${percent(item.score)}%${trendText}`);
  }
  const weakPoints = Array.isArray(evidence.weak_points) ? evidence.weak_points : [];
  for (const item of weakPoints.slice(0, 3)) {
    if (!item || typeof item.name !== 'string') continue;
    const reasons = Array.isArray(item.reasons) && item.reasons.length ? `：${item.reasons.join('；')}` : '';
    lines.push(`薄弱点 ${item.name} 掌握度 ${percent(item.mastery)}%${reasons}`);
  }
  return lines;
};

export type DashboardProfileView = {
  isReady: boolean;
  isEmpty: boolean;
  emptyHint: string;
  focusName: string | null;
  focusPoints: string[];
  mastery: ProfileMasteryItem[];
  weakPoints: ProfileWeakPoint[];
  insight: ProfileInsight | null;
  recentLearning: DashboardProfile['recent_learning'];
  observations: string[];
  goals: ProfileGoal[];
};

export const dashboardProfileView = (profile?: DashboardProfile | null): DashboardProfileView => ({
  isReady: Boolean(profile) && !profile?.is_empty,
  isEmpty: Boolean(profile?.is_empty),
  emptyHint: profile?.empty_hint || '开始一次学习、练习或复习后，系统会逐步了解你的学习状态。',
  focusName: profile?.current_focus || null,
  focusPoints: (profile?.focus_points || []).slice(0, 4).map(item => item.name),
  mastery: topMastery(profile?.mastery || [], 4),
  weakPoints: topWeakPoints(profile?.weak_points || [], 3),
  insight: profile?.insight?.text ? profile.insight : null,
  recentLearning: (profile?.recent_learning || []).slice(0, 3),
  observations: profile?.observations?.notes || [],
  goals: profile?.goals || [],
});

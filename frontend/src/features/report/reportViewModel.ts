import type { LearningReport, PeriodType, ReportSuggestion } from '../../services/api';

export type ComparisonView = { text: string; tone: 'positive' | 'negative' | 'neutral' };

export const formatComparison = (value: number | null): ComparisonView => {
  if (value === null) return { text: '暂无可比基线', tone: 'neutral' };
  if (value > 0) return { text: `较上期 +${value}%`, tone: 'positive' };
  if (value < 0) return { text: `较上期 ${value}%`, tone: 'negative' };
  return { text: '与上期持平', tone: 'neutral' };
};

export const formatDuration = (seconds: number): string => {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} 小时 ${remainder} 分钟` : `${hours} 小时`;
};

export type ReportMetricCard = {
  metric: string; label: string; value: string; comparison: ComparisonView;
};

export const reportMetricCards = (report: LearningReport): ReportMetricCard[] => [
  { metric: 'learning_time', label: '学习时长', value: formatDuration(report.total_active_seconds), comparison: formatComparison(report.comparisons.learning_time.percent_change) },
  { metric: 'activity_count', label: '学习次数', value: String(report.activity_count), comparison: formatComparison(report.comparisons.activity_count.percent_change) },
  { metric: 'new_knowledge_points', label: '新增知识点', value: String(report.new_knowledge_points), comparison: formatComparison(report.comparisons.new_knowledge_points.percent_change) },
  { metric: 'review_count', label: '完成复习', value: String(report.review_count), comparison: formatComparison(report.comparisons.review_count.percent_change) },
  { metric: 'quiz_accuracy', label: '练习正确率', value: `${report.quiz_accuracy}%`, comparison: formatComparison(report.comparisons.quiz_accuracy.percent_change) },
  { metric: 'mastery_change', label: '掌握程度变化', value: `${report.mastery_delta > 0 ? '+' : ''}${report.mastery_delta}%`, comparison: formatComparison(report.comparisons.mastery_change.percent_change) },
];

const parseCalendarDate = (value: string) => {
  const [year, month, day] = value.split('-').map(Number);
  return { year, month, day };
};
const calendarString = (date: Date) => date.toISOString().slice(0, 10);

export const moveAnchorDate = (value: string, period: PeriodType, direction: -1 | 1): string => {
  const { year, month, day } = parseCalendarDate(value);
  if (period === 'month') {
    const targetMonth = month - 1 + direction;
    const targetYear = year + Math.floor(targetMonth / 12);
    const normalizedMonth = ((targetMonth % 12) + 12) % 12;
    const lastDay = new Date(Date.UTC(targetYear, normalizedMonth + 1, 0)).getUTCDate();
    return calendarString(new Date(Date.UTC(targetYear, normalizedMonth, Math.min(day, lastDay))));
  }
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + direction * (period === 'week' ? 7 : 1));
  return calendarString(date);
};

export const suggestionCopy = (suggestion?: ReportSuggestion | null): string => {
  if (!suggestion) return '生成学习建议';
  if (suggestion.status === 'pending') return '正在生成学习建议';
  if (suggestion.status === 'failed') return '建议生成失败，可重新生成';
  return suggestion.suggestion || '建议已生成';
};

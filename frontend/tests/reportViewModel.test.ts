import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatComparison, formatDuration, moveAnchorDate, periodRangeLabel, reportMetricCards, suggestionCopy,
} from '../src/features/report/reportViewModel';

test('zero previous period is shown as no comparable baseline', () => {
  assert.deepEqual(formatComparison(null), { text: '暂无可比基线', tone: 'neutral' });
});

test('comparisons and durations preserve direction and sign', () => {
  assert.deepEqual(formatComparison(12.5), { text: '较上期 +12.5%', tone: 'positive' });
  assert.deepEqual(formatComparison(-8), { text: '较上期 -8%', tone: 'negative' });
  assert.equal(formatDuration(3660), '1 小时 1 分钟');
});

test('report metric cards use stable order and forward evidence metrics', () => {
  const report = {
    total_active_seconds: 900, activity_count: 4, new_knowledge_points: 2,
    review_count: 3, quiz_accuracy: 75, pending_grading_count: 1,
    mastery_delta: -5, weakness_changes: { improved: 1, worsened: 2, unchanged: 0 },
    comparisons: {
      learning_time: { percent_change: null }, activity_count: { percent_change: 1 },
      new_knowledge_points: { percent_change: 2 }, review_count: { percent_change: 3 },
      quiz_accuracy: { percent_change: -4 }, mastery_change: { percent_change: -5 },
    },
  } as any;
  const cards = reportMetricCards(report);
  assert.deepEqual(cards.map(item => item.metric), [
    'learning_time', 'activity_count', 'new_knowledge_points', 'review_count', 'quiz_accuracy', 'mastery_change',
  ]);
  assert.equal(cards.at(-1)?.value, '-5%');
});

test('period navigation keeps calendar dates and suggestion states are explicit', () => {
  assert.equal(moveAnchorDate('2026-03-31', 'month', -1), '2026-02-28');
  assert.equal(moveAnchorDate('2026-09-15', 'week', 1), '2026-09-22');
  assert.match(suggestionCopy(undefined), /生成学习建议/);
  assert.match(suggestionCopy({ status: 'failed', error_message: 'x' } as any), /重新生成/);
});

test('report range renders the exclusive server end as an inclusive calendar date', () => {
  assert.equal(periodRangeLabel('2026-09-14', '2026-09-21'), '2026-09-14 — 2026-09-20');
  assert.equal(periodRangeLabel('2026-09-16', '2026-09-17'), '2026-09-16');
});

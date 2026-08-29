import React from 'react';
import { Button, Typography } from 'antd';
import { CheckCircleFilled, InboxOutlined, LineChartOutlined } from '@ant-design/icons';
import type { ReviewResultSummary } from '../../features/review/types';

const { Text, Title } = Typography;

interface ReviewResultsProps {
  results: ReviewResultSummary;
  onOverview: () => void;
  onCards: () => void;
}

const durationLabel = (seconds: number) => seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;

export const ReviewResults: React.FC<ReviewResultsProps> = ({ results, onOverview, onCards }) => <div className="review-results paper-card">
  <CheckCircleFilled className="review-results-check" />
  <div className="page-eyebrow">Session complete</div>
  <Title level={1}>今天的记忆又稳了一点</Title>
  <Text type="secondary">已完成 {results.completed} 张卡片，系统已经安排好下一次见面。</Text>
  <div className="review-result-metrics">
    <div><span>总耗时</span><strong className="metric-number">{durationLabel(results.totalSeconds)}</strong></div>
    <div><span>平均每张</span><strong className="metric-number">{durationLabel(results.averageSeconds)}</strong></div>
    <div><span>掌握度变化</span><strong className={`metric-number ${results.masteryDelta >= 0 ? 'is-positive' : 'is-negative'}`}>{results.masteryDelta >= 0 ? '+' : ''}{Math.round(results.masteryDelta * 100)}%</strong></div>
  </div>
  <div className="review-result-distribution" aria-label="评分分布">
    {(['忘记了', '有点模糊', '记住了', '非常熟练'] as const).map((label, index) => <div key={label}><span>{index + 1}</span><Text>{label}</Text><strong>{results.ratingCounts[(index + 1) as 1 | 2 | 3 | 4]}</strong></div>)}
  </div>
  <div className="review-result-actions">
    <Button size="large" icon={<InboxOutlined />} onClick={onCards}>查看卡片库</Button>
    <Button size="large" type="primary" icon={<LineChartOutlined />} onClick={onOverview}>返回复习概览</Button>
  </div>
</div>;


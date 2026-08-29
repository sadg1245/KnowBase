import React, { useCallback, useEffect, useRef } from 'react';
import { Button, Progress, Typography } from 'antd';
import { ArrowLeftOutlined, CheckOutlined, CloseOutlined, EyeOutlined, MehOutlined, SmileOutlined } from '@ant-design/icons';
import { classifyReviewGesture, type Point } from '../../features/review/gestures';
import type { ReviewRating, ReviewSessionState } from '../../features/review/types';

const { Text, Title } = Typography;

interface ReviewSessionPanelProps {
  state: ReviewSessionState;
  submitting: boolean;
  onFlip: () => void;
  onRate: (rating: ReviewRating) => Promise<void> | void;
  onExit: () => void;
}

const ratingOptions: Array<{ rating: ReviewRating; label: string; hint: string; icon: React.ReactNode; className: string }> = [
  { rating: 1, label: '忘记了', hint: '重新学习', icon: <CloseOutlined />, className: 'is-forgot' },
  { rating: 2, label: '有点模糊', hint: '短期再见', icon: <MehOutlined />, className: 'is-fuzzy' },
  { rating: 3, label: '记住了', hint: '延长间隔', icon: <CheckOutlined />, className: 'is-remembered' },
  { rating: 4, label: '非常熟练', hint: '大幅延长', icon: <SmileOutlined />, className: 'is-fluent' },
];

export const ReviewSessionPanel: React.FC<ReviewSessionPanelProps> = ({ state, submitting, onFlip, onRate, onExit }) => {
  const touchStart = useRef<Point | null>(null);
  const current = state.cards[state.index];
  const rate = useCallback((rating: ReviewRating) => {
    if (!state.flipped || submitting) return;
    void onRate(rating);
  }, [onRate, state.flipped, submitting]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return;
      if ((event.key === 'Enter' || event.key === ' ') && !submitting) {
        event.preventDefault();
        onFlip();
      } else if (state.flipped && ['1', '2', '3', '4'].includes(event.key)) {
        event.preventDefault();
        rate(Number(event.key) as ReviewRating);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onFlip, rate, state.flipped, submitting]);

  if (!current) return null;
  const onTouchEnd = (point: Point) => {
    if (!touchStart.current || submitting) return;
    const gesture = classifyReviewGesture(touchStart.current, point, state.flipped);
    touchStart.current = null;
    if (gesture === 'flip') onFlip();
    if (gesture === 'forgot') rate(1);
    if (gesture === 'remembered') rate(3);
  };

  return <div className="review-session">
    <div className="review-session-header">
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={onExit}>退出复习</Button>
      <div className="review-progress-wrap"><Progress percent={Math.round((state.index / state.cards.length) * 100)} showInfo={false} strokeColor="#167d8d" /><Text className="review-progress-count">{state.index + 1} / {state.cards.length}</Text></div>
    </div>
    <div
      className={`review-flashcard paper-card ${state.flipped ? 'is-flipped' : ''}`}
      role="button"
      tabIndex={0}
      aria-label={state.flipped ? '隐藏答案' : '显示答案'}
      aria-pressed={state.flipped}
      onClick={() => { if (!submitting) onFlip(); }}
      onTouchStart={event => { const touch = event.changedTouches[0]; touchStart.current = touch ? { x: touch.clientX, y: touch.clientY } : null; }}
      onTouchEnd={event => { const touch = event.changedTouches[0]; if (touch) onTouchEnd({ x: touch.clientX, y: touch.clientY }); }}
    >
      <Text className="review-card-side">{state.flipped ? '答案' : '问题'}</Text>
      <Title level={2}>{state.flipped ? current.back : current.front}</Title>
      {state.flipped && current.source_label && <div className="review-card-source">来源：{current.source_label}</div>}
      <div className="review-flip-hint"><EyeOutlined /> {state.flipped ? '点击或按空格隐藏答案' : '先回忆，再点击或按空格查看答案'}</div>
    </div>
    <div className={`review-rating-panel ${state.flipped ? 'is-visible' : ''}`} aria-hidden={!state.flipped}>
      <Text type="secondary">按 1–4 评分 · 手机左滑“忘记”，右滑“记住”</Text>
      <div className="review-rating-grid">
        {ratingOptions.map(option => <Button
          key={option.rating}
          className={option.className}
          disabled={!state.flipped}
          loading={submitting}
          onClick={event => { event.stopPropagation(); rate(option.rating); }}
          icon={option.icon}
        ><span><strong>{option.rating} · {option.label}</strong><small>{option.hint}</small></span></Button>)}
      </div>
    </div>
  </div>;
};


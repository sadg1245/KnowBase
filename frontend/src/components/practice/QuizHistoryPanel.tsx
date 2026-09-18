import React from 'react';
import { Alert, Button, Empty, Pagination, Progress, Skeleton, Tabs, Tag } from 'antd';
import { PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons';

import type {
  AssessmentAnswerMode,
  AssessmentQuestionType,
  QuizSetHistoryItem,
  QuizSetHistoryRun,
  QuizSetHistoryScope,
} from '../../features/practice/types';


export const ANSWER_MODE_LABELS: Record<AssessmentAnswerMode, string> = {
  sequential: '逐题答题',
  full_paper: '整卷答题',
};

export const ANSWER_MODE_KEYS: AssessmentAnswerMode[] = ['sequential', 'full_paper'];

const DIFFICULTY_LABELS: Record<string, string> = { easy: '简单', medium: '适中', hard: '困难' };

const QUESTION_TYPE_LABELS: Record<AssessmentQuestionType, string> = {
  single_choice: '单项选择',
  multiple_choice: '多项选择',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  concept_explanation: '解释概念',
};

const RUN_STATUS_LABELS: Record<QuizSetHistoryRun['status'], string> = {
  not_started: '尚未开始',
  in_progress: '进行中',
  submitted: '已完成',
};

const SET_STATUS_LABELS: Record<QuizSetHistoryItem['status'], string> = {
  generating: '生成中',
  ready: '可作答',
  failed: '生成失败',
};

const formatScore = (value: number): string => String(Math.round(value * 10) / 10);

const formatMoment = (value: string): string => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

export const quizHistoryTitle = (item: QuizSetHistoryItem): string => item.title?.trim() || '自定义测验';

export const questionTypeLabel = (questionType: AssessmentQuestionType): string =>
  QUESTION_TYPE_LABELS[questionType] ?? questionType;

/** 资料范围：优先展示文件名，其次退回到数量，避免把内部 ID 暴露到界面上。 */
export const quizHistoryScopeLabel = (item: QuizSetHistoryItem): string => {
  const documents = item.documents.length
    ? item.documents.map(document => document.filename).join('、')
    : item.document_ids.length
      ? `${item.document_ids.length} 份已解析资料`
      : '全部已解析资料';
  const sections = item.section_filters.length ? item.section_filters.join('、') : '全部章节';
  const points = item.knowledge_point_ids.length ? `${item.knowledge_point_ids.length} 个知识点` : '全部知识点';
  return `${documents} · ${sections} · ${points}`;
};

export const quizHistoryRunLabel = (run: QuizSetHistoryRun | null): string => {
  if (!run) return '还没有作答记录';
  const round = `第 ${run.round_number} 轮`;
  if (run.status === 'submitted') {
    return `${round} · 已完成 · 得分 ${formatScore(run.score)}/${formatScore(run.max_score)} · 正确 ${run.correct_count}/${run.total_questions}`;
  }
  if (run.status === 'in_progress') {
    return `${round} · 进行中 · 已答 ${run.answered_count}/${run.total_questions}`;
  }
  return `${round} · ${RUN_STATUS_LABELS[run.status]} · 共 ${run.total_questions} 题`;
};

export type QuizHistoryAction = { label: string; tone: 'start' | 'resume' | 'retry' } | null;

export const quizHistoryAction = (item: QuizSetHistoryItem): QuizHistoryAction => {
  if (item.status !== 'ready') return null;
  if (!item.run || item.run.status === 'not_started') return { label: '开始作答', tone: 'start' };
  if (item.run.status === 'in_progress') return { label: '继续作答', tone: 'resume' };
  return { label: '再练一次', tone: 'retry' };
};

export const quizHistoryProgress = (run: QuizSetHistoryRun | null): number => {
  if (!run) return 0;
  if (run.status === 'submitted') return 100;
  if (run.total_questions <= 0) return 0;
  return Math.min(100, Math.round((run.answered_count / run.total_questions) * 100));
};

interface QuizHistoryPanelProps {
  mode: AssessmentAnswerMode;
  counts: Record<AssessmentAnswerMode, number>;
  items: QuizSetHistoryItem[];
  total: number;
  filters: QuizSetHistoryScope;
  loading?: boolean;
  busyId?: string;
  onModeChange: (mode: AssessmentAnswerMode) => void;
  onFiltersChange: (filters: QuizSetHistoryScope) => void;
  onOpen: (item: QuizSetHistoryItem) => void | Promise<void>;
  onRefresh: () => void;
}

export const QuizHistoryPanel: React.FC<QuizHistoryPanelProps> = ({
  mode,
  counts,
  items,
  total,
  filters,
  loading = false,
  busyId,
  onModeChange,
  onFiltersChange,
  onOpen,
  onRefresh,
}) => {
  const limit = filters.limit ?? 10;
  const offset = filters.offset ?? 0;

  return <section className="quiz-history-panel" aria-labelledby="quiz-history-title">
    <div className="practice-loop-heading">
      <div>
        <div className="page-eyebrow">GENERATION LOG · 可追溯的出题记录</div>
        <h2 id="quiz-history-title">历史出题</h2>
        <p className="quiz-history-lead">按作答方式分开保存每次生成的题单，随时继续或重做。</p>
      </div>
      <Button icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>刷新记录</Button>
    </div>
    <Tabs
      className="quiz-history-tabs"
      activeKey={mode}
      onChange={key => onModeChange(key as AssessmentAnswerMode)}
      items={ANSWER_MODE_KEYS.map(key => ({
        key,
        label: `${ANSWER_MODE_LABELS[key]}（${counts[key] ?? 0}）`,
      }))}
    />
    {loading && items.length === 0 ? <div className="paper-card practice-loop-loading"><Skeleton active paragraph={{ rows: 4 }} /></div>
      : items.length === 0 ? <div className="paper-card empty-guide">
        <Empty description={`还没有「${ANSWER_MODE_LABELS[mode]}」的出题记录`} />
      </div>
      : <div className="quiz-history-list">{items.map(item => {
        const action = quizHistoryAction(item);
        const busy = busyId === item.id;
        return <article className={`quiz-history-card paper-card is-${item.status}`} key={item.id}>
          <div className="quiz-history-main">
            <div className="quiz-history-meta">
              <Tag color={item.status === 'failed' ? 'error' : item.status === 'ready' ? 'cyan' : 'default'}>
                {SET_STATUS_LABELS[item.status]}
              </Tag>
              <Tag>{ANSWER_MODE_LABELS[item.answer_mode]}</Tag>
              {item.strict_sources ? <Tag>严格依据资料</Tag> : null}
              <span>{formatMoment(item.created_at)}</span>
            </div>
            <h3>{quizHistoryTitle(item)}</h3>
            <p className="quiz-history-scope">{quizHistoryScopeLabel(item)}</p>
            <div className="quiz-history-tags">
              <Tag>题量 {item.question_count}</Tag>
              <Tag>难度 {DIFFICULTY_LABELS[item.difficulty] ?? item.difficulty}</Tag>
              {item.question_types.map(type => <Tag key={type}>{questionTypeLabel(type)}</Tag>)}
            </div>
            {item.status === 'failed'
              ? <Alert className="quiz-history-error" type="error" showIcon message="这次生成失败了"
                  description={item.generation_error || '可以调整资料范围或题型后重新生成。'} />
              : <>
                <div className="quiz-history-run">
                  <span>{quizHistoryRunLabel(item.run)}</span>
                  {item.round_count > 1 ? <small>共 {item.round_count} 轮作答</small> : null}
                </div>
                {item.run ? <Progress percent={quizHistoryProgress(item.run)} showInfo={false} strokeColor="#167d8d" trailColor="#e7edef" /> : null}
              </>}
          </div>
          <div className="quiz-history-actions">
            {action
              ? <Button type="primary" icon={<PlayCircleOutlined />} loading={busy} onClick={() => void onOpen(item)}>
                {action.label}
              </Button>
              : <Button disabled>{item.status === 'failed' ? '生成失败' : '生成中'}</Button>}
            <small>最近更新 {formatMoment(item.updated_at)}</small>
          </div>
        </article>;
      })}</div>}
    {total > limit ? <Pagination
      className="practice-loop-pagination"
      current={Math.floor(offset / limit) + 1}
      pageSize={limit}
      total={total}
      showSizeChanger
      pageSizeOptions={[5, 10, 20]}
      onChange={(page, pageSize) => onFiltersChange({ ...filters, limit: pageSize, offset: (page - 1) * pageSize })}
    /> : null}
  </section>;
};

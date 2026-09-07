import React from 'react';
import { Button, Progress, Tag } from 'antd';
import { FileSearchOutlined, RedoOutlined, ReloadOutlined } from '@ant-design/icons';

import type {
  AssessmentQuestion,
  AssessmentSourceSnapshot,
  JsonValue,
  QuizAttempt,
  QuizRunView,
} from '../../features/practice/types';
import { createPracticeSession, practiceResults } from '../../features/practice/practiceSession';


const displayValue = (value: JsonValue | string[] | undefined | null): string => {
  if (value === undefined || value === null) return '—';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('、');
  if (typeof value === 'object' && 'message' in value && typeof value.message === 'string') return value.message;
  return JSON.stringify(value, null, 2);
};

export const assessmentSourceHref = (workspaceId: string, source: AssessmentSourceSnapshot): string | null => {
  if (!source.document_id) return null;
  const params = new URLSearchParams();
  if (source.chunk_id) params.set('chunk', source.chunk_id);
  if (typeof source.page === 'number') params.set('page', String(source.page));
  const query = params.toString();
  return `/knowledge/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(source.document_id)}${query ? `?${query}` : ''}`;
};

const attemptState = (attempt?: QuizAttempt): { label: string; className: string } => {
  if (!attempt) return { label: '未作答', className: 'is-unanswered' };
  if (attempt.evaluation_status === 'grading_failed') return { label: '评分暂未完成', className: 'is-grading-failed' };
  if (attempt.evaluation_status === 'pending_ai') return { label: 'AI 评分中', className: 'is-pending' };
  if (attempt.is_correct) return { label: '回答正确', className: 'is-correct' };
  return { label: '需要复习', className: 'is-incorrect' };
};

interface ResultQuestionProps {
  question: AssessmentQuestion;
  attempt?: QuizAttempt;
  workspaceId: string;
  retryingAttemptId?: string;
  onRetryGrading: (attemptId: string) => void | Promise<void>;
  onSource?: (href: string, source: AssessmentSourceSnapshot) => void;
}

const ResultQuestion: React.FC<ResultQuestionProps> = ({
  question,
  attempt,
  workspaceId,
  retryingAttemptId,
  onRetryGrading,
  onSource,
}) => {
  const state = attemptState(attempt);
  return <article className={`practice-result-question ${state.className}`}>
    <div className="practice-margin-state" aria-label={state.label}><span />{state.label}</div>
    <div className="practice-result-body">
      <div className="practice-question-meta">第 {question.position} 题 · {state.label}</div>
      <h3>{question.prompt}</h3>
      <dl className="practice-answer-review">
        <div><dt>你的答案</dt><dd>{displayValue(attempt?.user_answer)}</dd></div>
        {attempt?.evaluation_status === 'grading_failed' ? <div className="practice-grading-note">
          <dt>评分状态</dt>
          <dd>
            评分暂未完成，答案已经保存，不会记为错题。
            {attempt.error_reason ? <small>{attempt.error_reason}</small> : null}
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={retryingAttemptId === attempt.id}
              onClick={() => void onRetryGrading(attempt.id)}
            >重试评分</Button>
          </dd>
        </div> : null}
        <div><dt>参考答案</dt><dd>{displayValue(question.answer_payload ?? question.answer)}</dd></div>
        <div><dt>解析</dt><dd>{question.explanation || '暂无解析'}</dd></div>
        <div><dt>AI 评价</dt><dd>{displayValue(attempt?.feedback)}</dd></div>
      </dl>
      {question.source_snapshot.length ? <footer className="practice-source-notes">
        <strong><FileSearchOutlined /> 资料引用</strong>
        {question.source_snapshot.map((source, index) => {
          const href = assessmentSourceHref(workspaceId, source);
          const excerpt = typeof source.excerpt === 'string' ? source.excerpt : null;
          return <div className="practice-source-note" key={`${source.document_id ?? 'source'}-${source.chunk_id ?? index}`}>
            <sup>{index + 1}</sup>
            <div>
              {href ? <a href={href} onClick={() => onSource?.(href, source)}>
                {source.source_file || `资料 ${index + 1}`}{source.page ? ` · 第 ${source.page} 页` : ''}
              </a> : <span>{source.source_file || `资料 ${index + 1}`}</span>}
              {excerpt ? <blockquote>{excerpt}</blockquote> : null}
            </div>
          </div>;
        })}
      </footer> : null}
    </div>
  </article>;
};

interface QuizResultsProps {
  run: QuizRunView;
  retrying?: boolean;
  retryingAttemptId?: string;
  onRetry: () => void | Promise<void>;
  onRetryGrading: (attemptId: string) => void | Promise<void>;
  onSource?: (href: string, source: AssessmentSourceSnapshot) => void;
}

export const QuizResults: React.FC<QuizResultsProps> = ({
  run,
  retrying = false,
  retryingAttemptId,
  onRetry,
  onRetryGrading,
  onSource,
}) => {
  if (run.status !== 'submitted') return null;
  const session = createPracticeSession(run, run.quiz_set.questions, Date.now());
  const summary = practiceResults(session);
  const attempts = session.attemptsByQuestionId;
  const elapsedMinutes = Math.floor(run.elapsed_seconds / 60);
  const elapsedRemainder = run.elapsed_seconds % 60;

  return <section className="practice-results" aria-labelledby="practice-results-title">
    <header className="practice-results-summary paper-card">
      <div>
        <div className="page-eyebrow">ANSWER SHEET · 已批阅</div>
        <h2 id="practice-results-title">这份答卷留下了哪些线索</h2>
        <p>{summary.gradingFailedQuestionIds.length || summary.pendingQuestionIds.length
          ? '部分主观题仍在等待评分，当前结果不会把它们算作错误。'
          : '沿着批注回看推理过程，再决定下一轮重点。'}</p>
      </div>
      <div className="practice-score-seal">
        <Progress type="circle" percent={summary.accuracyPercent} strokeColor="#167d8d" size={112} />
        <span>{summary.score}/{summary.maxScore || '—'} 分</span>
      </div>
      <div className="practice-result-metrics">
        <div><span>已评分</span><strong>{summary.gradedCount}/{session.questions.length}</strong></div>
        <div><span>正确题数</span><strong>{summary.correctCount}</strong></div>
        <div><span>用时</span><strong>{elapsedMinutes}:{String(elapsedRemainder).padStart(2, '0')}</strong></div>
      </div>
      <Button type="primary" icon={<RedoOutlined />} loading={retrying} onClick={() => void onRetry()}>重新作答</Button>
    </header>

    <div className="practice-result-list">
      {session.questions.map(question => <ResultQuestion
        key={question.id}
        question={question}
        attempt={attempts[question.id]}
        workspaceId={run.quiz_set.workspace_id}
        retryingAttemptId={retryingAttemptId}
        onRetryGrading={onRetryGrading}
        onSource={onSource}
      />)}
    </div>
    {summary.pendingQuestionIds.length ? <Tag color="processing">{summary.pendingQuestionIds.length} 题 AI 评分中</Tag> : null}
  </section>;
};

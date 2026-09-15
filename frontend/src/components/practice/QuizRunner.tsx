import React, { useEffect, useRef, useState } from 'react';
import { Button, Progress, Tag } from 'antd';
import { ArrowLeftOutlined, ArrowRightOutlined, CheckOutlined, ClockCircleOutlined } from '@ant-design/icons';

import type { PracticeAnswer, PracticeSessionState, QuizAttempt, QuizRunView } from '../../features/practice/types';
import { remainingSeconds, unansweredQuestionIds } from '../../features/practice/practiceSession';
import { QuestionInput, answerIsPresent } from './QuestionInput';
import { QuizResults, ResultQuestion } from './QuizResults';


const QUESTION_TYPE_LABELS: Record<PracticeSessionState['questions'][number]['question_type'], string> = {
  single_choice: '单项选择题',
  multiple_choice: '多项选择题',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  concept_explanation: '解释概念题',
};

export const paperSubmissionWarning = (unansweredIds: string[]): string | null => (
  unansweredIds.length ? `还有 ${unansweredIds.length} 道题未作答，仍要交卷吗？` : null
);

export const shouldAutoSubmitPaper = (run: QuizRunView, secondsRemaining: number | null): boolean => (
  run.status === 'in_progress' && run.answer_mode === 'full_paper' && secondsRemaining === 0
);

export const activeQuestionIndexForRun = (
  activeIndex: number,
  activeRunId: string,
  nextRunId: string,
): number => activeRunId === nextRunId ? activeIndex : 0;

const formatTimer = (seconds: number | null): string => {
  if (seconds === null) return '不限时';
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
};

const markerState = (attempt?: QuizAttempt, hasDraft = false): string => {
  if (attempt?.evaluation_status === 'grading_failed') return 'is-grading-failed';
  if (attempt?.evaluation_status === 'pending_ai') return 'is-pending';
  if (attempt?.evaluation_status === 'graded') return 'is-submitted';
  return hasDraft ? 'is-answered' : 'is-empty';
};

interface QuizRunnerProps {
  session: PracticeSessionState;
  submitting?: boolean;
  retrying?: boolean;
  retryingAttemptId?: string;
  onAnswer: (questionId: string, answer: PracticeAnswer) => void;
  onSubmitQuestion: (questionId: string, answer: PracticeAnswer) => void | Promise<void>;
  onSubmitPaper: () => void | Promise<void>;
  onRetry: () => void | Promise<void>;
  onRetryGrading: (attemptId: string) => void | Promise<void>;
}

export const QuizRunner: React.FC<QuizRunnerProps> = ({
  session,
  submitting = false,
  retrying = false,
  retryingAttemptId,
  onAnswer,
  onSubmitQuestion,
  onSubmitPaper,
  onRetry,
  onRetryGrading,
}) => {
  const [activeIndex, setActiveIndex] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const timeoutSubmittedRunId = useRef<string>();
  const runStatus = session.run.status;
  const runId = session.run.id;
  const answerMode = session.run.answer_mode;
  const startedAt = session.run.started_at;
  const durationLimit = session.run.quiz_set.duration_limit_seconds;
  const timeRemaining = remainingSeconds(session.run, now);
  const timeoutReached = runStatus === 'in_progress' && answerMode === 'full_paper' && timeRemaining === 0;
  const activeRunId = useRef(runId);

  useEffect(() => {
    if (activeRunId.current === runId) return;
    activeRunId.current = runId;
    setActiveIndex(0);
  }, [runId]);

  useEffect(() => {
    if (runStatus !== 'in_progress' || durationLimit === null || startedAt === null) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [runStatus, durationLimit, startedAt]);

  useEffect(() => {
    if (!timeoutReached || timeoutSubmittedRunId.current === runId) return;
    timeoutSubmittedRunId.current = runId;
    void onSubmitPaper();
  }, [timeoutReached, runId, onSubmitPaper]);

  if (runStatus === 'submitted') {
    return <QuizResults
      run={session.run}
      retrying={retrying}
      retryingAttemptId={retryingAttemptId}
      onRetry={onRetry}
      onRetryGrading={onRetryGrading}
    />;
  }

  const questions = session.questions;
  if (questions.length === 0) return <div className="paper-card empty-guide">这份测验还没有题目。</div>;
  const runAwareIndex = activeQuestionIndexForRun(activeIndex, activeRunId.current, runId);
  const safeIndex = Math.min(runAwareIndex, questions.length - 1);
  const current = questions[safeIndex];
  const answer = session.answers[current.id];
  const attempt = session.attemptsByQuestionId[current.id];
  const isRevealed = session.revealedQuestionIds.has(current.id);
  const unanswered = unansweredQuestionIds(session);
  const remaining = timeRemaining;
  const answeredCount = questions.length - unanswered.length;

  const submitPaper = () => {
    const warning = paperSubmissionWarning(unanswered);
    if (warning && !window.confirm(warning)) return;
    void onSubmitPaper();
  };

  return <section className="practice-runner" aria-label="测验答题区">
    <header className="practice-runner-header">
      <div>
        <div className="page-eyebrow">ROUND {session.run.round_number} · {session.run.answer_mode === 'sequential' ? '逐题作答' : '整卷作答'}</div>
        <h2>{session.run.quiz_set.title}</h2>
      </div>
      <div className={`practice-timer ${remaining === 0 ? 'is-expired' : ''}`} aria-label="剩余时间">
        <ClockCircleOutlined /><span>{formatTimer(remaining)}</span>
      </div>
    </header>
    <Progress percent={Math.round((answeredCount / questions.length) * 100)} showInfo={false} strokeColor="#167d8d" />

    <div className="practice-paper-layout">
      <nav className="practice-question-index" aria-label="题目导航">
        <span className="practice-index-label">题目索引</span>
        <div>
          {questions.map((question, index) => <button
            key={question.id}
            type="button"
            className={`${markerState(session.attemptsByQuestionId[question.id], answerIsPresent(session.answers[question.id]))} ${index === safeIndex ? 'is-active' : ''}`}
            aria-label={`第 ${index + 1} 题`}
            aria-current={index === safeIndex ? 'step' : undefined}
            onClick={() => setActiveIndex(index)}
          >{index + 1}</button>)}
        </div>
      </nav>

      <article className="practice-question-paper paper-card">
        <div className={`practice-paper-marker ${markerState(attempt, answerIsPresent(answer))}`} aria-hidden="true" />
        <div className="practice-question-meta">
          <span>第 {safeIndex + 1} 题 / 共 {questions.length} 题</span>
          <Tag>{QUESTION_TYPE_LABELS[current.question_type]}</Tag>
          <Tag>{current.difficulty === 'easy' ? '基础' : current.difficulty === 'hard' ? '挑战' : '适中'}</Tag>
        </div>
        <h3>{current.prompt}</h3>
        <QuestionInput
          question={current}
          value={answer}
          disabled={Boolean(attempt) || submitting}
          onChange={value => onAnswer(current.id, value)}
        />

        {isRevealed ? <div className="practice-inline-feedback"><ResultQuestion
          question={current} attempt={attempt} workspaceId={session.run.quiz_set.workspace_id}
          retryingAttemptId={retryingAttemptId} onRetryGrading={onRetryGrading}
        /></div> : null}

        <footer className="practice-paper-actions">
          <Button
            icon={<ArrowLeftOutlined />}
            disabled={safeIndex === 0}
            onClick={() => setActiveIndex(index => Math.max(0, index - 1))}
          >上一题</Button>
          <div>
            {session.run.answer_mode === 'sequential' && !attempt ? <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={submitting}
              disabled={unanswered.includes(current.id)}
              onClick={() => void onSubmitQuestion(current.id, answer!)}
            >提交本题</Button> : null}
            {safeIndex < questions.length - 1 ? <Button
              type={attempt ? 'primary' : 'default'}
              icon={<ArrowRightOutlined />}
              iconPosition="end"
              onClick={() => setActiveIndex(index => Math.min(questions.length - 1, index + 1))}
            >下一题</Button> : null}
            {session.run.answer_mode === 'full_paper' ? <Button
              type="primary"
              loading={submitting}
              disabled={submitting}
              onClick={submitPaper}
            >交卷</Button> : null}
          </div>
        </footer>
      </article>
    </div>
  </section>;
};

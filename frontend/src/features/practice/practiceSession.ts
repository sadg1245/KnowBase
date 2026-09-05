import type {
  AssessmentQuestion,
  PracticeAnswer,
  PracticeResultSummary,
  PracticeSessionDraft,
  PracticeSessionState,
  QuizAttempt,
  QuizRunView,
} from './types';

export const PRACTICE_SESSION_STORAGE_KEY = 'knowbase.practice-session.v1';

const hasAnswer = (answer: PracticeAnswer | undefined): answer is PracticeAnswer => (
  typeof answer === 'string'
    ? answer.trim().length > 0
    : Array.isArray(answer) && answer.length > 0 && answer.every(value => typeof value === 'string' && value.trim().length > 0)
);

const copyAnswer = (answer: PracticeAnswer): PracticeAnswer => Array.isArray(answer) ? [...answer] : answer;

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

const isDraftAnswer = (value: unknown): value is PracticeAnswer => (
  typeof value === 'string' || (Array.isArray(value) && value.every(item => typeof item === 'string'))
);

const latestAttempts = (run: QuizRunView, questions: AssessmentQuestion[]): Record<string, QuizAttempt> => {
  const questionIds = new Set(questions.map(question => question.id));
  const attempts = new Map<string, QuizAttempt>();
  for (const attempt of [...run.attempts, ...questions.map(question => question.attempt).filter((attempt): attempt is QuizAttempt => Boolean(attempt))]) {
    if (attempt.quiz_run_id !== run.id || !questionIds.has(attempt.question_id)) continue;
    const previous = attempts.get(attempt.question_id);
    if (!previous || previous.attempt_number <= attempt.attempt_number) attempts.set(attempt.question_id, attempt);
  }
  return Object.fromEntries(attempts);
};

export const createPracticeSession = (
  run: QuizRunView,
  questions: AssessmentQuestion[],
  createdAt: number,
  draft: PracticeSessionDraft | null = null,
): PracticeSessionState => {
  const scopedQuestions = run.question_ids === null
    ? [...questions]
    : questions.filter(question => run.question_ids?.includes(question.id));
  const attemptsByQuestionId = latestAttempts(run, scopedQuestions);
  const answers: Record<string, PracticeAnswer> = {};
  const draftAnswers = draft?.version === 1 && draft.runId === run.id ? draft.answers : {};

  for (const question of scopedQuestions) {
    const serverAttempt = attemptsByQuestionId[question.id];
    if (serverAttempt) {
      answers[question.id] = copyAnswer(serverAttempt.user_answer);
    } else if (hasAnswer(draftAnswers[question.id])) {
      answers[question.id] = copyAnswer(draftAnswers[question.id]);
    }
  }

  const revealedQuestionIds = new Set<string>();
  if (run.status === 'submitted') {
    scopedQuestions.forEach(question => revealedQuestionIds.add(question.id));
  } else if (run.answer_mode === 'sequential') {
    Object.keys(attemptsByQuestionId).forEach(questionId => revealedQuestionIds.add(questionId));
  }

  return {
    run,
    questions: scopedQuestions,
    answers,
    attemptsByQuestionId,
    revealedQuestionIds,
    createdAt,
  };
};

export const setAnswer = (
  state: PracticeSessionState,
  questionId: string,
  answer: PracticeAnswer,
): PracticeSessionState => {
  if (!state.questions.some(question => question.id === questionId) || state.attemptsByQuestionId[questionId]) return state;
  const answers = { ...state.answers };
  if (hasAnswer(answer)) answers[questionId] = copyAnswer(answer);
  else delete answers[questionId];
  return { ...state, answers };
};

export const recordAttempt = (state: PracticeSessionState, attempt: QuizAttempt): PracticeSessionState => {
  if (attempt.quiz_run_id !== state.run.id || !state.questions.some(question => question.id === attempt.question_id)) return state;
  const previous = state.attemptsByQuestionId[attempt.question_id];
  if (previous && previous.attempt_number > attempt.attempt_number) return state;
  const attemptsByQuestionId = { ...state.attemptsByQuestionId, [attempt.question_id]: attempt };
  const answers = { ...state.answers, [attempt.question_id]: copyAnswer(attempt.user_answer) };
  const revealedQuestionIds = new Set(state.revealedQuestionIds);
  if (state.run.status === 'submitted' || state.run.answer_mode === 'sequential') revealedQuestionIds.add(attempt.question_id);
  return { ...state, attemptsByQuestionId, answers, revealedQuestionIds };
};

export const remainingSeconds = (run: QuizRunView, now: number): number | null => {
  const limit = run.quiz_set.duration_limit_seconds;
  if (limit === null) return null;
  const startedAt = run.started_at === null ? Number.NaN : Date.parse(run.started_at);
  if (!Number.isFinite(startedAt)) return limit;
  return Math.max(0, limit - Math.floor(Math.max(0, now - startedAt) / 1_000));
};

export const unansweredQuestionIds = (state: PracticeSessionState): string[] => (
  state.questions.filter(question => !hasAnswer(state.answers[question.id])).map(question => question.id)
);

export const practiceResults = (state: PracticeSessionState): PracticeResultSummary => {
  const gradedAttempts = Object.values(state.attemptsByQuestionId).filter(attempt => attempt.evaluation_status === 'graded');
  const score = gradedAttempts.reduce((total, attempt) => total + (attempt.score ?? 0), 0);
  const maxScore = gradedAttempts.reduce((total, attempt) => total + attempt.max_score, 0);
  const correctCount = gradedAttempts.filter(attempt => attempt.is_correct === true).length;
  return {
    gradedCount: gradedAttempts.length,
    correctCount,
    score,
    maxScore,
    accuracyPercent: maxScore ? Math.round((score / maxScore) * 100) : 0,
    pendingQuestionIds: Object.values(state.attemptsByQuestionId)
      .filter(attempt => attempt.evaluation_status === 'pending_ai')
      .map(attempt => attempt.question_id),
    gradingFailedQuestionIds: Object.values(state.attemptsByQuestionId)
      .filter(attempt => attempt.evaluation_status === 'grading_failed')
      .map(attempt => attempt.question_id),
  };
};

const resolvedStorage = (storage?: Storage | null): Storage | null => {
  if (storage !== undefined) return storage;
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage;
  } catch {
    return null;
  }
};

export const loadPracticeSessionDraft = (runId: string, storage?: Storage | null): PracticeSessionDraft | null => {
  try {
    const raw = resolvedStorage(storage)?.getItem(PRACTICE_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.version !== 1 || parsed.runId !== runId || !isRecord(parsed.answers)) return null;
    const answers = Object.entries(parsed.answers).reduce<Record<string, PracticeAnswer>>((validAnswers, [questionId, answer]) => {
      if (isDraftAnswer(answer) && hasAnswer(answer)) validAnswers[questionId] = copyAnswer(answer);
      return validAnswers;
    }, {});
    return { version: 1, runId, answers };
  } catch {
    return null;
  }
};

export const clearPracticeSessionDraft = (storage?: Storage | null): void => {
  try {
    resolvedStorage(storage)?.removeItem(PRACTICE_SESSION_STORAGE_KEY);
  } catch {
    // Session storage can be disabled by the browser or privacy settings.
  }
};

export const savePracticeSessionDraft = (state: PracticeSessionState, storage?: Storage | null): void => {
  if (state.run.status === 'submitted') {
    clearPracticeSessionDraft(storage);
    return;
  }
  const answers = Object.fromEntries(state.questions
    .filter(question => !state.attemptsByQuestionId[question.id] && hasAnswer(state.answers[question.id]))
    .map(question => [question.id, copyAnswer(state.answers[question.id])])) as Record<string, PracticeAnswer>;
  if (Object.keys(answers).length === 0) {
    clearPracticeSessionDraft(storage);
    return;
  }
  try {
    resolvedStorage(storage)?.setItem(PRACTICE_SESSION_STORAGE_KEY, JSON.stringify({ version: 1, runId: state.run.id, answers } satisfies PracticeSessionDraft));
  } catch {
    // Draft persistence is best effort; the server remains authoritative.
  }
};

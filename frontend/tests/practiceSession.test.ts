import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createPracticeSession,
  loadPracticeSessionDraft,
  practiceResults,
  recordAttempt,
  remainingSeconds,
  savePracticeSessionDraft,
  setAnswer,
  unansweredQuestionIds,
} from '../src/features/practice/practiceSession';

const questions = [
  { id: 'q1', prompt: 'First question', question_type: 'single_choice', position: 1 },
  { id: 'q2', prompt: 'Second question', question_type: 'short_answer', position: 2 },
] as any[];

const run = {
  id: 'run-1',
  quiz_set_id: 'set-1',
  round_number: 1,
  answer_mode: 'full_paper',
  question_ids: null,
  status: 'in_progress',
  started_at: '1970-01-01T00:00:01.000Z',
  submitted_at: null,
  elapsed_seconds: 0,
  score: 0,
  max_score: 0,
  correct_count: 0,
  graded_count: 0,
  created_at: '1970-01-01T00:00:00.000Z',
  updated_at: '1970-01-01T00:00:00.000Z',
  attempts: [],
  quiz_set: { duration_limit_seconds: 60 },
} as any;

test('full paper keeps answers hidden and reports unanswered questions', () => {
  const state = setAnswer(createPracticeSession(run, questions, 1_000), 'q1', 'A');

  assert.deepEqual(unansweredQuestionIds(state), ['q2']);
  assert.equal(state.revealedQuestionIds.size, 0);
});

test('timer resumes from server started_at and clamps at the limit', () => {
  assert.equal(remainingSeconds(run, Date.parse(run.started_at) + 61_000), 0);
  assert.equal(remainingSeconds({ ...run, quiz_set: { duration_limit_seconds: null } }, 99_000), null);
});

test('only graded attempts contribute to result accuracy', () => {
  const state = createPracticeSession({
    ...run,
    answer_mode: 'sequential',
    attempts: [
      {
        id: 'attempt-1', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: 'q1',
        attempt_number: 1, user_answer: 'A', is_correct: true, score: 1, max_score: 1,
        evaluation_status: 'graded', feedback: { message: 'Correct' }, error_reason: null,
        duration_seconds: 2, submitted_at: '1970-01-01T00:00:03.000Z',
      },
      {
        id: 'attempt-2', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: 'q2',
        attempt_number: 1, user_answer: 'Draft', is_correct: null, score: null, max_score: 1,
        evaluation_status: 'grading_failed', feedback: { message: 'Retry' }, error_reason: 'provider unavailable',
        duration_seconds: 2, submitted_at: '1970-01-01T00:00:04.000Z',
      },
    ],
  }, questions, 1_000);

  assert.equal(state.revealedQuestionIds.has('q1'), true);
  assert.equal(state.revealedQuestionIds.has('q2'), true);
  assert.deepEqual(practiceResults(state), {
    gradedCount: 1,
    correctCount: 1,
    score: 1,
    maxScore: 1,
    accuracyPercent: 100,
    pendingQuestionIds: [],
    gradingFailedQuestionIds: ['q2'],
  });
});

test('storage ignores malformed and stale drafts while preserving unsubmitted answers only', () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  } as Storage;

  values.set('knowbase.practice-session.v1', '{not json');
  assert.equal(loadPracticeSessionDraft('run-1', storage), null);

  values.set('knowbase.practice-session.v1', JSON.stringify({ version: 1, runId: 'another-run', answers: { q1: 'stale' } }));
  assert.equal(loadPracticeSessionDraft('run-1', storage), null);

  const state = createPracticeSession({
    ...run,
    attempts: [{
      id: 'attempt-1', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: 'q1',
      attempt_number: 1, user_answer: 'Server answer', is_correct: true, score: 1, max_score: 1,
      evaluation_status: 'graded', feedback: null, error_reason: null, duration_seconds: 1,
      submitted_at: '1970-01-01T00:00:02.000Z',
    }],
  }, questions, 1_000, { version: 1, runId: 'run-1', answers: { q1: 'stale', q2: ['B', 'C'] } });
  savePracticeSessionDraft(state, storage);

  assert.deepEqual(loadPracticeSessionDraft('run-1', storage), {
    version: 1,
    runId: 'run-1',
    answers: { q2: ['B', 'C'] },
  });
  assert.equal(state.answers.q1, 'Server answer');
});

test('storage failures leave the active session usable', () => {
  const unavailableStorage = {
    getItem: () => { throw new Error('storage disabled'); },
    setItem: () => { throw new Error('storage disabled'); },
    removeItem: () => { throw new Error('storage disabled'); },
  } as unknown as Storage;
  const state = setAnswer(createPracticeSession(run, questions, 1_000), 'q2', 'draft');

  assert.equal(loadPracticeSessionDraft('run-1', unavailableStorage), null);
  assert.doesNotThrow(() => savePracticeSessionDraft(state, unavailableStorage));
  assert.equal(state.answers.q2, 'draft');
});

test('scoped submitted run reveals only its fixed paper questions', () => {
  const state = createPracticeSession({
    ...run,
    question_ids: ['q2'],
    status: 'submitted',
  }, questions, 1_000);

  assert.deepEqual(state.questions.map(question => question.id), ['q2']);
  assert.deepEqual([...state.revealedQuestionIds], ['q2']);
});

test('pending AI attempts do not count as incorrect results', () => {
  const state = createPracticeSession({
    ...run,
    answer_mode: 'sequential',
    attempts: [{
      id: 'attempt-pending', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: 'q1',
      attempt_number: 1, user_answer: 'Waiting', is_correct: null, score: null, max_score: 1,
      evaluation_status: 'pending_ai', feedback: null, error_reason: null, duration_seconds: 1,
      submitted_at: '1970-01-01T00:00:02.000Z',
    }],
  }, questions, 1_000);

  assert.deepEqual(practiceResults(state), {
    gradedCount: 0,
    correctCount: 0,
    score: 0,
    maxScore: 0,
    accuracyPercent: 0,
    pendingQuestionIds: ['q1'],
    gradingFailedQuestionIds: [],
  });
});

test('recording a full-paper attempt is immutable and does not reveal its answer early', () => {
  const initial = createPracticeSession(run, questions, 1_000);
  const next = recordAttempt(initial, {
    id: 'attempt-1', quiz_set_id: 'set-1', quiz_run_id: 'run-1', question_id: 'q1',
    attempt_number: 1, user_answer: 'A', is_correct: true, score: 1, max_score: 1,
    evaluation_status: 'graded', feedback: null, error_reason: null, duration_seconds: 1,
    submitted_at: '1970-01-01T00:00:02.000Z',
  });

  assert.notEqual(next, initial);
  assert.equal(initial.attemptsByQuestionId.q1, undefined);
  assert.equal(next.answers.q1, 'A');
  assert.equal(next.revealedQuestionIds.size, 0);
});

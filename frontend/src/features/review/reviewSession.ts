import type { Flashcard } from '../../services/api';
import type { RecordReviewInput, ReviewResultSummary, ReviewSessionState } from './types';

export const createReviewSession = (cards: Flashcard[], startedAt: number): ReviewSessionState => ({
  cards: [...cards],
  index: 0,
  flipped: false,
  cardStartedAt: startedAt,
  results: [],
});

export const flipCard = (state: ReviewSessionState): ReviewSessionState => ({
  ...state,
  flipped: !state.flipped,
});

export const reviewDurationSeconds = (state: ReviewSessionState, finishedAt: number): number =>
  Math.max(0, Math.min(3600, Math.round((finishedAt - state.cardStartedAt) / 1000)));

export const recordReview = (state: ReviewSessionState, input: RecordReviewInput): ReviewSessionState => ({
  ...state,
  index: state.index + 1,
  flipped: false,
  cardStartedAt: input.finishedAt,
  results: [...state.results, {
    cardId: input.response.card.id,
    rating: input.rating,
    durationSeconds: input.response.change.duration_seconds,
    previousMastery: input.response.change.previous_mastery,
    nextMastery: input.response.change.next_mastery,
  }],
});

export const reviewResults = (state: ReviewSessionState): ReviewResultSummary => {
  const ratingCounts: ReviewResultSummary['ratingCounts'] = { 1: 0, 2: 0, 3: 0, 4: 0 };
  let totalSeconds = 0;
  let masteryDelta = 0;
  for (const result of state.results) {
    ratingCounts[result.rating] += 1;
    totalSeconds += result.durationSeconds;
    masteryDelta += result.nextMastery - result.previousMastery;
  }
  const completed = state.results.length;
  return {
    completed,
    ratingCounts,
    totalSeconds,
    averageSeconds: completed ? Math.round(totalSeconds / completed) : 0,
    masteryDelta: completed ? Number((masteryDelta / completed).toFixed(2)) : 0,
  };
};

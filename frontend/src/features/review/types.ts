import type { Flashcard, ReviewResponse } from '../../services/api';

export type ReviewRating = 1 | 2 | 3 | 4;

export interface ReviewEntry {
  cardId: string;
  rating: ReviewRating;
  durationSeconds: number;
  previousMastery: number;
  nextMastery: number;
}

export interface ReviewSessionState {
  cards: Flashcard[];
  index: number;
  flipped: boolean;
  cardStartedAt: number;
  results: ReviewEntry[];
}

export interface RecordReviewInput {
  rating: ReviewRating;
  finishedAt: number;
  response: ReviewResponse;
}

export interface ReviewResultSummary {
  completed: number;
  ratingCounts: Record<ReviewRating, number>;
  totalSeconds: number;
  averageSeconds: number;
  masteryDelta: number;
}

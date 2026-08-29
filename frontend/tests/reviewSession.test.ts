import assert from 'node:assert/strict';
import test from 'node:test';

import type { Flashcard, ReviewResponse } from '../src/services/api';
import {
  createReviewSession,
  flipCard,
  recordReview,
  reviewDurationSeconds,
  reviewResults,
} from '../src/features/review/reviewSession';

const card: Flashcard = {
  id: 'card-1', workspace_id: 'workspace', knowledge_point_id: 'point',
  front: 'Question', back: 'Answer', source_label: 'Book · p3', source_type: 'knowledge_point',
  source_snapshot: { page: 3 }, tags: ['memory'], difficulty: 3, mastery: 0.4,
  mastery_status: 'learning', due_at: '2026-08-29T00:00:00Z', interval_days: 2,
  ease: 2.5, review_count: 1, algorithm_version: 'simple_v1', scheduler_data: {},
  last_reviewed_at: null, total_review_seconds: 9, created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

const response: ReviewResponse = {
  card: { ...card, mastery: 0.52, interval_days: 5, review_count: 2 },
  change: {
    previous_mastery: 0.4,
    next_mastery: 0.52,
    previous_status: 'learning',
    next_status: 'learning',
    previous_interval: 2,
    next_interval: 5,
    duration_seconds: 18,
  },
};

test('creates a focused review session and flips without resetting timing', () => {
  const state = createReviewSession([card], 1_000);
  assert.equal(state.index, 0);
  assert.equal(state.flipped, false);
  assert.equal(state.cardStartedAt, 1_000);
  const flipped = flipCard(state);
  assert.equal(flipped.flipped, true);
  assert.equal(flipped.cardStartedAt, 1_000);
});

test('records rating duration and mastery delta before advancing', () => {
  const state = flipCard(createReviewSession([card], 1_000));
  assert.equal(reviewDurationSeconds(state, 19_400), 18);
  const next = recordReview(state, { rating: 3, finishedAt: 19_400, response });
  assert.equal(next.index, 1);
  assert.equal(next.flipped, false);
  assert.equal(next.results[0].durationSeconds, 18);
  assert.equal(next.results[0].previousMastery, 0.4);
  assert.equal(next.results[0].nextMastery, 0.52);
  assert.equal(reviewResults(next).masteryDelta, 0.12);
});

test('summarizes rating distribution total and average duration', () => {
  const first = recordReview(flipCard(createReviewSession([card, { ...card, id: 'card-2' }], 0)), {
    rating: 1,
    finishedAt: 4_200,
    response: { ...response, change: { ...response.change, duration_seconds: 4 } },
  });
  const second = recordReview(flipCard(first), {
    rating: 4,
    finishedAt: 14_100,
    response: { ...response, card: { ...response.card, id: 'card-2' }, change: { ...response.change, duration_seconds: 10 } },
  });
  const summary = reviewResults(second);
  assert.deepEqual(summary.ratingCounts, { 1: 1, 2: 0, 3: 0, 4: 1 });
  assert.equal(summary.totalSeconds, 14);
  assert.equal(summary.averageSeconds, 7);
  assert.equal(summary.completed, 2);
});

test('duration is rounded and clamped to the API range', () => {
  const state = createReviewSession([card], 5_000);
  assert.equal(reviewDurationSeconds(state, 4_000), 0);
  assert.equal(reviewDurationSeconds(state, 3_700_000), 3600);
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { classifyReviewGesture } from '../src/features/review/gestures';

test('upward swipe flips a question card', () => {
  assert.equal(classifyReviewGesture({ x: 10, y: 100 }, { x: 20, y: 35 }, false), 'flip');
});

test('horizontal swipes rate a revealed card', () => {
  assert.equal(classifyReviewGesture({ x: 100, y: 20 }, { x: 30, y: 24 }, true), 'forgot');
  assert.equal(classifyReviewGesture({ x: 20, y: 20 }, { x: 90, y: 25 }, true), 'remembered');
});

test('short or scroll-like gestures do not trigger review actions', () => {
  assert.equal(classifyReviewGesture({ x: 20, y: 20 }, { x: 45, y: 70 }, true), null);
  assert.equal(classifyReviewGesture({ x: 20, y: 80 }, { x: 30, y: 20 }, true), null);
  assert.equal(classifyReviewGesture({ x: 20, y: 20 }, { x: 60, y: 24 }, true), null);
});

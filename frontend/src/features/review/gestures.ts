export interface Point { x: number; y: number }
export type ReviewGesture = 'flip' | 'forgot' | 'remembered' | null;

const GESTURE_THRESHOLD = 56;

export const classifyReviewGesture = (start: Point, end: Point, flipped: boolean): ReviewGesture => {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (!flipped && dy <= -GESTURE_THRESHOLD && Math.abs(dy) > Math.abs(dx)) return 'flip';
  if (flipped && Math.abs(dx) >= GESTURE_THRESHOLD && Math.abs(dx) > Math.abs(dy)) {
    return dx < 0 ? 'forgot' : 'remembered';
  }
  return null;
};

interface ScrollTarget {
  scrollIntoView(options?: ScrollIntoViewOptions): unknown;
}

/**
 * Keep React effects from returning the browser's scroll result.
 * Newer Chromium builds may return a Promise from scrollIntoView().
 */
export function scrollMessagesIntoView(target: ScrollTarget | null): void {
  if (target) {
    target.scrollIntoView({ behavior: 'smooth' });
  }
}

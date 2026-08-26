import type { DocumentSection } from '../services/api';

export function resolveSelectedChunk(
  items: DocumentSection[],
  requestedChunk?: string | null,
  requestedPage?: number | null,
): DocumentSection | undefined {
  if (requestedChunk) {
    const exact = items.find(item => item.chunk_id === requestedChunk);
    if (exact) return exact;
  }
  if (requestedPage && requestedPage > 0) {
    const page = items.find(item => item.page_num === requestedPage);
    if (page) return page;
  }
  return items[0];
}

export const pdfPageFragment = (page?: number | null): string =>
  page && page > 0 ? `#page=${page}` : '';

export function buildOutline(items: DocumentSection[]): DocumentSection[] {
  const seen = new Set<string>();
  return items.filter(item => {
    const key = JSON.stringify([item.section_path, item.heading ?? null, item.page_num ?? null]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}


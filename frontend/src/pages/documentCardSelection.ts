export interface RawDocumentSelection {
  text: string;
  startChunkId?: string;
  endChunkId?: string;
  page?: number | null;
  heading?: string | null;
}

export interface DocumentCardSelection {
  excerpt: string;
  chunkId: string;
  page?: number | null;
  heading?: string | null;
}

export const normalizeDocumentCardSelection = (input: RawDocumentSelection): DocumentCardSelection | null => {
  const excerpt = input.text.replace(/\s+/g, ' ').trim();
  if (!excerpt || !input.startChunkId || input.startChunkId !== input.endChunkId) return null;
  return {
    excerpt,
    chunkId: input.startChunkId,
    page: input.page,
    heading: input.heading,
  };
};


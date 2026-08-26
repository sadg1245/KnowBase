import type { SourceItem } from '../../services/api';

export function linkifySourceCitations(markdown: string, sourceCount: number): string {
  const protectedPattern = /(```[\s\S]*?```|`[^`\n]*`)/g;
  return markdown.split(protectedPattern).map((part, index) => {
    if (index % 2 === 1) return part;
    return part.replace(/\[资料(\d+)\]/g, (match, rawIndex) => {
      const sourceIndex = Number(rawIndex);
      return sourceIndex >= 1 && sourceIndex <= sourceCount
        ? `[资料${sourceIndex}](knowbase-source://${sourceIndex})`
        : match;
    });
  }).join('');
}

export function sourceDetailTarget(workspaceId: string, source: SourceItem): string | null {
  if (!workspaceId || !source.document_id || !source.chunk_id) return null;
  const query = new URLSearchParams({ chunk: source.chunk_id });
  if (source.page_number > 0) query.set('page', String(source.page_number));
  return `/knowledge/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(source.document_id)}?${query.toString()}`;
}


const FENCE_PATTERN = /^(\s*)(`{3,}|~{3,})/;
const BACKTICK_PATTERN = /(`+)/g;


const normalizeProse = (value: string): string => value
  .replace(/\\\[([^\n]*?)\\\]/g, (_match, expression: string) => `$$\n${expression.trim()}\n$$`)
  .replace(/\\\(/g, '$')
  .replace(/\\\)/g, '$')
  .replace(/\\\[/g, () => '$$')
  .replace(/\\\]/g, () => '$$');


const normalizeOutsideInlineCode = (line: string): string => {
  let cursor = 0;
  let codeFenceLength = 0;
  let output = '';

  for (const match of line.matchAll(BACKTICK_PATTERN)) {
    const marker = match[0];
    const index = match.index ?? 0;
    const segment = line.slice(cursor, index);
    output += codeFenceLength ? segment : normalizeProse(segment);
    output += marker;

    if (!codeFenceLength) codeFenceLength = marker.length;
    else if (marker.length === codeFenceLength) codeFenceLength = 0;
    cursor = index + marker.length;
  }

  const remainder = line.slice(cursor);
  return output + (codeFenceLength ? remainder : normalizeProse(remainder));
};


export const normalizeMathDelimiters = (markdown: string): string => {
  let openFence: { marker: string; length: number } | null = null;

  return markdown.split('\n').map((line) => {
    const fence = line.match(FENCE_PATTERN);
    if (fence) {
      const run = fence[2];
      if (!openFence) openFence = { marker: run[0], length: run.length };
      else if (run[0] === openFence.marker && run.length >= openFence.length) openFence = null;
      return line;
    }
    return openFence ? line : normalizeOutsideInlineCode(line);
  }).join('\n');
};

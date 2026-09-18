export interface AnswerSection {
  key: 'sources' | 'model' | 'unverified' | 'mixed';
  title?: string;
  body: string;
}

const HEADING = /^#{0,6}[ \t]*(来自私人资料|AI 补充（模型记忆）|尚未被资料证实)[ \t]*[:：]?[ \t]*$/;

const KEY_BY_TITLE: Record<string, AnswerSection['key']> = {
  '来自私人资料': 'sources',
  'AI 补充（模型记忆）': 'model',
  '尚未被资料证实': 'unverified',
};

export const splitAnswerSections = (content: string): AnswerSection[] => {
  const lines = (content ?? '').split(/\r?\n/);
  const sections: AnswerSection[] = [];
  let current: AnswerSection | undefined;
  for (const line of lines) {
    const match = line.match(HEADING);
    if (match) {
      if (current) sections.push(current);
      current = { key: KEY_BY_TITLE[match[1]], title: match[1], body: '' };
      continue;
    }
    if (current) current.body = current.body ? `${current.body}\n${line}` : line;
  }
  if (current) {
    sections.push({ ...current, body: current.body.trim() });
    return sections.filter(section => section.body.length > 0);
  }
  const body = (content ?? '').trim();
  return body ? [{ key: 'mixed', title: undefined, body }] : [];
};

export const layerNotice = (key: string): string | undefined =>
  key === 'model' ? '这部分不是你的资料，来自模型知识' : undefined;

export const answerPolicyLabel = (status?: string): string => ({
  supported: '资料命中',
  limited: '资料不足，已用模型补充',
  insufficient: '资料不足，已用模型补充',
  model_only: '仅模型补充',
  error: '检索异常',
}[status || ''] || '尚未检索');

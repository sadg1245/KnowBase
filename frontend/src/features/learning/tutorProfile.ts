import type { LearningMemory, MemoryKind, TutorProfile } from '../../services/api';

export const MEMORY_KIND_LABELS: Record<MemoryKind, string> = {
  session_summary: '会话小结',
  mistake_pattern: '错题模式',
  preference: '学习偏好',
  insight: '报告洞察',
  manual: '手动记录',
};

export const memoryKindLabel = (kind: string): string =>
  MEMORY_KIND_LABELS[kind as MemoryKind] ?? '学习记忆';

export const memorySourceLabel = (memory: LearningMemory): string => {
  const refs = memory.source_refs ?? {};
  if (refs.session_id) return '来源：学习会话';
  if (refs.knowledge_point_id || refs.mistake_id) return '来源：练习与知识点';
  if (refs.period_type) return '来源：学习报告';
  return '来源：手动记录';
};

export const filterMemories = (items: LearningMemory[], kind?: MemoryKind): LearningMemory[] =>
  items.filter(item => item.is_active && (!kind || item.kind === kind));

export const profileSummary = (profile: TutorProfile): string => {
  const parts = [`${profile.weak_points.length} 个薄弱知识点`];
  if (profile.next_actions.length) parts.push(`下一步：${profile.next_actions.join('、')}`);
  if (profile.recent_topics.length) parts.push(`最近学习：${profile.recent_topics.join('、')}`);
  return parts.join(' · ');
};

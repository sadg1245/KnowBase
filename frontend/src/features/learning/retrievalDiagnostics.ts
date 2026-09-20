import type { RetrievalRunDetail, RetrievalRunHit } from '../../services/api';

export type EvidenceDiagnostics = {
  status?: string;
  degradationReason?: string;
  queryIntent?: string;
  rerankDegraded?: string | null;
  indexStale?: boolean;
  indexStaleReasons?: string[];
  contextNotes?: string[];
};

export type DiagnosticLine = { label: string; value: string; tone: 'ok' | 'warn' | 'info' };

/** 回答级诊断：把证据事件里的可选键翻译成可读行，缺省不显示噪声。 */
export const evidenceDiagnosticLines = (evidence?: EvidenceDiagnostics | null): DiagnosticLine[] => {
  if (!evidence) return [];
  const lines: DiagnosticLine[] = [];
  if (evidence.status) {
    lines.push({
      label: '证据状态',
      value: evidence.status,
      tone: evidence.status === 'supported' ? 'ok' : evidence.status === 'insufficient' ? 'warn' : 'info',
    });
  }
  if (evidence.queryIntent) lines.push({ label: '查询意图', value: evidence.queryIntent, tone: 'info' });
  if (evidence.degradationReason) lines.push({ label: '检索降级', value: evidence.degradationReason, tone: 'warn' });
  if (evidence.rerankDegraded) lines.push({ label: '重排降级', value: evidence.rerankDegraded, tone: 'warn' });
  if (evidence.indexStale) {
    const reasons = (evidence.indexStaleReasons || []).join('、') || '索引指纹与当前配置不一致';
    lines.push({ label: '索引需要重建', value: reasons, tone: 'warn' });
  }
  for (const note of (evidence.contextNotes || []).slice(0, 3)) {
    lines.push({ label: '上下文处理', value: note, tone: 'info' });
  }
  return lines;
};

export type HitRow = {
  chunkId: string;
  source: string;
  rank: string;
  scores: string;
  kinds: string;
  bonus: string;
};

/** 逐条候选的分项打分：向量/关键词名次、融合、重排与画像 Bonus。 */
export const hitRows = (detail?: RetrievalRunDetail | null): HitRow[] =>
  (detail?.hits || []).map((hit: RetrievalRunHit) => ({
    chunkId: hit.chunk_id,
    source: `${hit.source_file}${hit.page_num ? ` · 第 ${hit.page_num} 页` : ''}${hit.heading ? ` · ${hit.heading}` : ''}`,
    rank: `V${hit.vector_rank ?? '-'} / K${hit.keyword_rank ?? '-'} → #${hit.final_rank ?? '-'}`,
    scores: `融合 ${hit.fusion_score.toFixed(3)} · 重排 ${hit.rerank_score.toFixed(3)}`,
    kinds: (hit.vector_kinds || []).join('+') || 'content',
    bonus: hit.profile_bonus > 0 ? `+${hit.profile_bonus.toFixed(3)}` : '0',
  }));

export const runSummary = (detail?: RetrievalRunDetail | null): string | null => {
  if (!detail?.run) return null;
  const parts = [
    `范围 ${detail.run.scope_mode || 'strict'}`,
    `证据 ${detail.run.evidence_status}`,
    detail.run.expanded_scope ? `已扩展 ${detail.run.expansion_rounds} 轮` : '未扩展',
  ];
  if (!detail.run.vector_succeeded) parts.push('向量不可用');
  if (!detail.run.keyword_succeeded) parts.push('关键词不可用');
  return parts.join(' · ');
};

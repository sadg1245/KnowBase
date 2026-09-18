export type EvidenceStatus = 'supported' | 'limited' | 'insufficient' | 'error';

export interface EvidenceInfo {
  status: EvidenceStatus;
  vector_succeeded: boolean;
  keyword_succeeded: boolean;
  degradation_reason?: string;
  top_score: number;
  answer_policy?: string;
  model_fallback?: boolean;
  profile_injected?: boolean;
  memory_hits?: string[];
  memory_degraded_reason?: string | null;
}

export interface AssistantDraft {
  session?: { id: string; title: string; title_changed?: boolean };
  evidence?: EvidenceInfo;
  content: string;
  sources: unknown[];
  suggestions: string[];
  answerLayers: string[];
  messageId?: string;
  status: 'streaming' | 'complete' | 'partial' | 'failed';
}

export const createAssistantDraft = (): AssistantDraft => ({
  content: '',
  sources: [],
  suggestions: [],
  answerLayers: [],
  status: 'streaming',
});

export const applyChatEvent = (state: AssistantDraft, event: Record<string, any>): AssistantDraft => {
  if (event.session) return { ...state, session: event.session };
  if (event.evidence) return { ...state, evidence: event.evidence };
  if (typeof event.replace === 'string') return { ...state, content: event.replace };
  if (typeof event.token === 'string') return { ...state, content: state.content + event.token };
  if (Array.isArray(event.sources)) return { ...state, sources: event.sources };
  if (Array.isArray(event.suggestions)) return { ...state, suggestions: event.suggestions.slice(0, 3) };
  if (event.done) {
    return {
      ...state,
      messageId: event.message_id,
      answerLayers: Array.isArray(event.answer_layers) ? event.answer_layers : state.answerLayers,
      status: event.generation_status === 'partial' ? 'partial' : 'complete',
    };
  }
  if (event.error) return { ...state, status: state.content ? 'partial' : 'failed' };
  return state;
};

export const learningLayoutForWidth = (width: number): 'three-column' | 'two-column' | 'single-column' => {
  if (width >= 1280) return 'three-column';
  if (width >= 900) return 'two-column';
  return 'single-column';
};

export const evidenceStatusLabel = (status?: string): string => ({
  supported: '资料命中',
  limited: '资料不足，已用模型补充',
  insufficient: '资料不足，已用模型补充',
  model_only: '仅模型补充',
  error: '检索异常',
}[status || ''] || '尚未检索');

export const messagesAfterSessionDelete = <T>(
  activeSessionId: string | undefined,
  deletedSessionId: string,
  messages: T[],
): T[] => activeSessionId === deletedSessionId ? [] : messages;

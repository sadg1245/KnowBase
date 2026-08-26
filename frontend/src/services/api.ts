import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
});

const authToken = () => localStorage.getItem('knowbase_session');
api.interceptors.request.use((config) => {
  const token = authToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
api.interceptors.response.use((response) => response, (error) => {
  if (error?.response?.status === 401) window.dispatchEvent(new Event('knowbase:locked'));
  return Promise.reject(error);
});

// ============ 类型定义 ============

export interface Workspace {
  id: string;
  name: string;
  description: string;
  document_count: number;
  created_at: string;
  learning_goal?: string;
  domain?: string;
  accent_color?: string;
  archived?: boolean;
}

export interface Document {
  id: string;
  workspace_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  chunk_count: number;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  error_message?: string | null;
  summary?: string | null;
  outline?: string | null;
  learning_status: 'not_started' | 'queued' | 'generating' | 'ready' | 'failed';
  learning_error_message?: string | null;
  tags: string[];
  chapter_summaries: unknown[];
  core_concepts: unknown[];
  important_terms: unknown[];
  common_mistakes: unknown[];
  prerequisites: unknown[];
  learning_order: unknown[];
  review_points: unknown[];
  processed_at?: string | null;
  learning_generated_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentSection {
  chunk_id: string;
  chunk_index: number;
  page_num?: number | null;
  heading?: string | null;
  heading_level?: number | null;
  section_path: string[];
  content: string;
  document_id?: string;
  previous_chunk_id?: string | null;
  next_chunk_id?: string | null;
}

export interface DocumentSectionsResponse {
  document_id: string;
  outline: Array<Omit<DocumentSection, 'content' | 'chunk_index'>>;
  items: DocumentSection[];
}

export interface SearchResult {
  answer: string;
  sources: SourceItem[];
  timing: {
    retrieval_ms: number;
    generation_ms: number;
    total_ms: number;
  };
}

export interface SourceItem {
  filename: string;
  page_number: number;
  content: string;
  score: number;
  document_id?: string | null;
  heading?: string | null;
  chunk_id?: string | null;
}

export interface BackendSourceItem {
  content: string;
  source_file: string;
  page_num?: number | null;
  score: number;
  document_id?: string | null;
  heading?: string | null;
  chunk_id?: string | null;
}

export type ChatEvent =
  | { token: string }
  | { session: { id: string; title: string; title_changed?: boolean } }
  | { evidence: { status: 'supported' | 'limited' | 'insufficient' | 'error'; vector_succeeded: boolean; keyword_succeeded: boolean; degradation_reason?: string; top_score: number } }
  | { sources: BackendSourceItem[] }
  | { suggestions: string[] }
  | { done: true; message_id?: string; session_id?: string; conversation_id?: string; confidence?: number; full_text?: string; generation_status?: 'complete' | 'partial' }
  | { error: string; retryable?: boolean; message_id?: string };

const normalizeSource = (source: BackendSourceItem): SourceItem => ({
  filename: source.source_file,
  page_number: source.page_num ?? 0,
  content: source.content,
  score: source.score,
  document_id: source.document_id,
  heading: source.heading,
  chunk_id: source.chunk_id,
});

export interface LLMSettings {
  provider: string;
  model: string;
  api_key?: string;
  api_key_masked?: string;
  base_url?: string;
}

export interface SystemInfo {
  version: string;
  total_workspaces: number;
  total_documents: number;
  total_chunks: number;
  backend_uptime: number;
}

export interface EmbeddingSettings {
  model: string;
  dimension?: number | null;
}

// ============ 工作区接口 ============

export const getWorkspaces = async (): Promise<Workspace[]> => {
  const res = await api.get('/workspaces');
  return res.data;
};

export const createWorkspace = async (name: string, description: string): Promise<Workspace> => {
  const res = await api.post('/workspaces', { name, description });
  return res.data;
};

export const deleteWorkspace = async (id: string): Promise<void> => {
  await api.delete(`/workspaces/${id}`);
};

// ============ 文档接口 ============

export const getDocuments = async (workspaceId: string): Promise<Document[]> => {
  const res = await api.get(`/workspaces/${workspaceId}/documents`);
  return res.data;
};

export const uploadDocument = async (
  workspaceId: string,
  file: File,
  onProgress?: (percent: number) => void
): Promise<Document> => {
  const formData = new FormData();
  formData.append('files', file);
  const res = await api.post(`/workspaces/${workspaceId}/documents`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (e.total && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    },
  });
  const item = Array.isArray(res.data) ? res.data[0] : res.data;
  return item.document ?? item;
};

export const deleteDocument = async (docId: string): Promise<void> => {
  await api.delete(`/documents/${docId}`);
};

export const getDocumentStatus = async (docId: string): Promise<Document> => {
  const res = await api.get(`/documents/${docId}/status`);
  return res.data;
};

export const getDocument = async (id: string): Promise<Document> => (await api.get(`/documents/${id}`)).data;
export const updateDocument = async (id: string, values: { filename?: string; tags?: string[] }): Promise<Document> =>
  (await api.patch(`/documents/${id}`, values)).data;
export const getDocumentSections = async (id: string): Promise<DocumentSectionsResponse> =>
  (await api.get(`/documents/${id}/sections`)).data;
export const getDocumentSection = async (documentId: string, chunkId: string): Promise<DocumentSection> =>
  (await api.get(`/documents/${documentId}/sections/${encodeURIComponent(chunkId)}`)).data;
export const reprocessDocument = async (id: string): Promise<Document> =>
  (await api.post(`/documents/${id}/reprocess`)).data;
export const regenerateDocumentLearning = async (id: string): Promise<Document> =>
  (await api.post(`/documents/${id}/regenerate-learning`)).data;

// ============ 检索接口 ============

export const searchKnowledge = async (
  query: string,
  workspaceId?: string
): Promise<SearchResult> => {
  const res = await api.post('/search', { query, workspace_id: workspaceId });
  return {
    answer: '',
    sources: (res.data.results || []).map(normalizeSource),
    timing: { retrieval_ms: 0, generation_ms: 0, total_ms: 0 },
  };
};

export const streamChat = async (
  question: string,
  workspaceId: string | undefined,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
  mode = 'explain',
  strictSources = true,
  sessionId?: string,
  documentIds: string[] = [],
): Promise<void> => {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(authToken() ? { Authorization: `Bearer ${authToken()}` } : {}) },
    body: JSON.stringify({ question, workspace_id: workspaceId, document_ids: documentIds, mode, strict_sources: strictSources, session_id: sessionId }),
    signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Chat request failed: ${response.status}`);
  }
  if (!response.body) {
    throw new Error('Chat response has no stream body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {
      const dataLine = block.split('\n').find((line) => line.startsWith('data:'));
      if (dataLine) onEvent(JSON.parse(dataLine.slice(5).trim()));
    }
    if (done) break;
  }
};

export const normalizeChatSources = (sources: BackendSourceItem[]): SourceItem[] =>
  sources.map(normalizeSource);

export type LearningMode = 'direct' | 'simple' | 'deep' | 'socratic' | 'feynman' | 'quiz';
export type EvidenceStatus = 'supported' | 'limited' | 'insufficient' | 'error';

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  sources: BackendSourceItem[];
  mode?: LearningMode;
  evidence_status?: EvidenceStatus;
  follow_up_questions: string[];
  generation_status: 'complete' | 'partial' | 'failed';
  created_at: string;
}

export interface ChatSession {
  id: string;
  user_id: string;
  workspace_id?: string | null;
  title: string;
  document_ids: string[];
  mode: LearningMode;
  strict_sources: boolean;
  is_favorite: boolean;
  summary?: string | null;
  created_at: string;
  updated_at: string;
  last_message_at: string;
  messages?: ChatMessage[];
}

export const getChatSessions = async (workspaceId?: string, favorite?: boolean): Promise<ChatSession[]> =>
  (await api.get('/chat/sessions', { params: { workspace_id: workspaceId, favorite } })).data;

export const createChatSession = async (values: {
  workspace_id?: string;
  document_ids?: string[];
  mode?: LearningMode;
  strict_sources?: boolean;
  title?: string;
}): Promise<ChatSession> => (await api.post('/chat/sessions', values)).data;

export const getChatSession = async (id: string): Promise<ChatSession> =>
  (await api.get(`/chat/sessions/${id}`)).data;

export const updateChatSession = async (id: string, values: Partial<Pick<ChatSession, 'title' | 'workspace_id' | 'document_ids' | 'mode' | 'strict_sources' | 'is_favorite'>>): Promise<ChatSession> =>
  (await api.patch(`/chat/sessions/${id}`, values)).data;

export const deleteChatSession = async (id: string): Promise<void> => {
  await api.delete(`/chat/sessions/${id}`);
};

export const createSessionSummaryNote = async (id: string): Promise<{ id: string; title: string; content: string }> =>
  (await api.post(`/chat/sessions/${id}/summary-note`, {})).data;

export const createMessageCard = async (messageId: string) =>
  (await api.post(`/chat/messages/${messageId}/card`)).data;

export const createMessageNote = async (messageId: string) =>
  (await api.post(`/chat/messages/${messageId}/note`, {})).data;

export const createMessageMistake = async (messageId: string) =>
  (await api.post(`/chat/messages/${messageId}/mistake`)).data;

export const updateMessageFeedback = async (messageId: string, helpful: boolean, category?: string) =>
  (await api.put(`/chat/messages/${messageId}/feedback`, { helpful, category })).data;

// ============ 个人学习接口 ============

export interface KnowledgePoint {
  id: string; workspace_id: string; document_id?: string | null; title: string;
  summary: string; explanation: string; source_page?: number | null;
  source_heading?: string | null; importance: number; difficulty: number;
  mastery: number; tags: string[]; is_key: boolean;
  mastery_status: 'not_started' | 'learning' | 'mastered'; created_at: string;
}

export interface Flashcard {
  id: string; workspace_id: string; knowledge_point_id?: string | null;
  front: string; back: string; source_label?: string | null; due_at: string;
  interval_days: number; ease: number; review_count: number;
}

export interface QuizQuestion {
  id: string; workspace_id: string; knowledge_point_id?: string | null;
  question_type: 'choice' | 'true_false' | 'short'; prompt: string;
  options?: string[] | null; answer?: string; explanation: string;
  source_label?: string | null; attempts: number; correct_attempts: number;
  last_answer?: string | null; last_correct?: boolean | null;
}

export interface LearningDashboard {
  profile: { display_name: string; daily_goal_minutes: number; daily_review_target: number };
  stats: { workspace_count: number; document_count: number; knowledge_point_count: number; due_cards: number; wrong_questions: number; today_minutes: number; week_minutes: number; streak_days: number };
  today_tasks: { type: string; title: string; count: number; path: string }[];
  weak_points: KnowledgePoint[];
  recent_activities: { id: string; type: string; title: string; duration_seconds: number; created_at: string }[];
  recent_workspaces: Workspace[];
}

export interface KnowledgeBaseDetail extends Workspace {
  progress: number; card_count: number; quiz_count: number;
  documents: (Document & { outline_items?: DocumentSectionsResponse['outline'] })[];
  knowledge_points: KnowledgePoint[];
  recent_activities: Array<{ id: string; type: string; title: string; duration_seconds: number; payload?: Record<string, unknown> | null; created_at: string }>;
  recommendations: Array<{
    type: 'retry_document' | 'retry_learning' | 'generate_learning' | 'review_point' | 'continue_chat';
    title: string; document_id?: string; knowledge_point_id?: string;
  }>;
}

export const getLearningDashboard = async (): Promise<LearningDashboard> => (await api.get('/learning/dashboard')).data;
export interface LearningProfile { id: string; display_name: string; daily_goal_minutes: number; daily_review_target: number; preferred_mode: string; reminder_time?: string }
export const getLearningProfile = async (): Promise<LearningProfile> => (await api.get('/learning/profile')).data;
export const updateLearningProfile = async (values: Partial<LearningProfile>): Promise<LearningProfile> => (await api.put('/learning/profile', values)).data;
export const getKnowledgeBaseDetail = async (id: string): Promise<KnowledgeBaseDetail> => (await api.get(`/learning/workspaces/${id}`)).data;
export const updateKnowledgeBase = async (id: string, values: Partial<Workspace>): Promise<KnowledgeBaseDetail> => (await api.put(`/learning/workspaces/${id}`, values)).data;
export const analyzeKnowledgeBase = async (id: string, documentId?: string, regenerate = false): Promise<{ created_points: number; detail: KnowledgeBaseDetail }> => (await api.post(`/learning/workspaces/${id}/analyze`, { document_id: documentId, regenerate })).data;
export const updateKnowledgePoint = async (id: string, values: Partial<KnowledgePoint>): Promise<KnowledgePoint> => (await api.put(`/learning/knowledge-points/${id}`, values)).data;
export const deleteKnowledgePoint = async (id: string): Promise<void> => { await api.delete(`/learning/knowledge-points/${id}`); };
export const knowledgePointToCard = async (id: string): Promise<Flashcard> => (await api.post(`/learning/knowledge-points/${id}/card`)).data;
export const mergeKnowledgePoints = async (targetId: string, sourceIds: string[]): Promise<KnowledgePoint> =>
  (await api.post('/learning/knowledge-points/merge', { target_id: targetId, source_ids: sourceIds })).data;
export const knowledgePointToQuiz = async (id: string): Promise<QuizQuestion> =>
  (await api.post(`/learning/knowledge-points/${id}/quiz`)).data;
export const getCards = async (dueOnly = false, workspaceId?: string): Promise<Flashcard[]> => (await api.get('/learning/cards', { params: { due_only: dueOnly, workspace_id: workspaceId } })).data;
export const createCard = async (values: Pick<Flashcard, 'workspace_id' | 'front' | 'back'> & Partial<Flashcard>): Promise<Flashcard> => (await api.post('/learning/cards', values)).data;
export const reviewCard = async (id: string, rating: 1 | 2 | 3 | 4): Promise<Flashcard> => (await api.post(`/learning/cards/${id}/review`, { rating })).data;
export const deleteCard = async (id: string): Promise<void> => { await api.delete(`/learning/cards/${id}`); };
export const generateQuiz = async (workspaceId: string, count = 5, documentIds: string[] = []): Promise<QuizQuestion[]> => (await api.post('/learning/quizzes/generate', { workspace_id: workspaceId, document_ids: documentIds, count, question_type: 'mixed' })).data;
export const getQuizzes = async (wrongOnly = false, workspaceId?: string, documentIds: string[] = []): Promise<QuizQuestion[]> => (await api.get('/learning/quizzes', {
  params: { wrong_only: wrongOnly, workspace_id: workspaceId, document_ids: documentIds },
  paramsSerializer: { indexes: null },
})).data;
export const submitQuiz = async (id: string, answer: string): Promise<{ correct: boolean; reference_answer: string; explanation: string; source_label?: string; question: QuizQuestion }> => (await api.post(`/learning/quizzes/${id}/submit`, { answer })).data;
export const getLearningReport = async (days = 7) => (await api.get('/learning/report', { params: { days } })).data;
export const exportLearningData = async () => (await api.get('/learning/export')).data;
export const createActivity = async (values: { workspace_id?: string; activity_type: string; title: string; duration_seconds?: number; payload?: object }) => (await api.post('/learning/activities', values)).data;
export const documentContentUrl = (id: string) => `/api/documents/${id}/content`;
export const getDocumentObjectUrl = async (id: string): Promise<string> => {
  const response = await api.get(`/documents/${id}/content`, { responseType: 'blob' });
  return URL.createObjectURL(response.data);
};

export interface AuthStatus { enabled: boolean; configured: boolean }
export const getAuthStatus = async (): Promise<AuthStatus> => (await api.get('/auth/status')).data;
export const unlockVault = async (password: string, setup = false, displayName?: string): Promise<void> => {
  const response = await api.post(setup ? '/auth/setup' : '/auth/login', { password, display_name: displayName });
  localStorage.setItem('knowbase_session', response.data.token);
};

// ============ 大模型设置接口 ============

export const getLLMSettings = async (): Promise<LLMSettings> => {
  const res = await api.get('/settings/llm');
  return { ...res.data, api_key: '' };
};

export const updateLLMSettings = async (settings: LLMSettings): Promise<void> => {
  await api.put('/settings/llm', settings);
};

export const testLLM = async (provider: string, model: string): Promise<{ success: boolean; message: string }> => {
  const res = await api.post('/settings/llm/test', { provider, model });
  return res.data;
};

export const getEmbeddingSettings = async (): Promise<EmbeddingSettings> => {
  const res = await api.get('/settings/embedding');
  return res.data;
};

export const updateEmbeddingSettings = async (model: string): Promise<EmbeddingSettings> => {
  const res = await api.put('/settings/embedding', { model });
  return res.data;
};

// ============ 系统接口 ============

export const getSystemInfo = async (): Promise<SystemInfo> => {
  const res = await api.get('/settings/system');
  return {
    version: res.data.version,
    total_workspaces: res.data.workspace_count,
    total_documents: res.data.document_count,
    total_chunks: res.data.total_chunks,
    backend_uptime: res.data.backend_uptime,
  };
};

export default api;

import axios from 'axios';
import type {
  AssessmentListScope,
  AssessmentPage,
  AttemptResult,
  LearningTask,
  LearningTaskFilters,
  MistakeFilters,
  MistakeRecord,
  MistakeRedoRequest,
  MistakeRedoResult,
  PaperSubmitRequest,
  QuestionSubmitRequest,
  QuizRunCreateRequest,
  QuizRunView,
  QuizSetHistoryPage,
  QuizSetHistoryScope,
  QuizSetGenerateRequest,
  QuizSetView,
  WeakKnowledgeRecalculation,
  WeakKnowledgeRecalculationScope,
  WeakKnowledgeState,
} from '../features/practice/types';

export type {
  AssessmentListScope,
  AssessmentPage,
  AssessmentQuestion,
  AssessmentQuestionType,
  AttemptEvaluationStatus,
  AttemptFeedbackPayload,
  AttemptResult,
  LearningTask,
  LearningTaskFilters,
  MistakeFilters,
  MistakeMasteryStatus,
  MistakeRecord,
  MistakeRedoRequest,
  MistakeRedoResult,
  PaperSubmitRequest,
  PracticeAnswer,
  QuestionSubmitRequest,
  QuizAttempt,
  QuizRunCreateRequest,
  QuizRunSummary,
  QuizRunView,
  QuizSetHistoryItem,
  QuizSetHistoryPage,
  QuizSetHistoryRun,
  QuizSetHistoryScope,
  QuizSetGenerateRequest,
  QuizSetView,
  WeakKnowledgeRecalculation,
  WeakKnowledgeRecalculationScope,
  WeakKnowledgeState,
} from '../features/practice/types';

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
  slug?: string;
  document_count: number;
  knowledge_point_count?: number;
  learning_progress?: number;
  last_studied_at?: string | null;
  created_at: string;
  updated_at?: string;
  learning_goal?: string;
  learning_status?: LearningStatus;
  domain?: string;
  domain_id?: string | null;
  cover_kind?: 'upload' | 'url' | 'none';
  cover_url?: string | null;
  accent_color?: string;
  archived?: boolean;
}

export type LearningStatus = 'not_started' | 'learning' | 'paused' | 'completed';

export const LEARNING_STATUS_LABELS: Record<LearningStatus, string> = {
  not_started: '未开始',
  learning: '学习中',
  paused: '已暂停',
  completed: '已完成',
};

export interface WorkspaceDraft {
  name: string;
  description?: string;
  learning_goal?: string;
  learning_status?: LearningStatus;
  domain_id?: string | null;
  domain?: string;
  cover_url?: string | null;
  clear_cover?: boolean;
  accent_color?: string;
  archived?: boolean;
}

export interface LearningDomain {
  id: string;
  name: string;
  description: string;
  color: string;
  workspace_count: number;
  created_at: string;
  updated_at: string;
}

export interface CurrentUser {
  id: string;
  username: string;
  display_name: string;
  avatar_kind: 'upload' | 'url' | 'none';
  avatar_url?: string | null;
  created_at?: string | null;
}

export interface LearningPreferences {
  daily_goal_minutes: number;
  daily_review_target: number;
  weekly_goal_days: number;
  timezone_name: string;
  preferred_mode: string;
  reminder_time?: string | null;
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
  /** 后端是否已经具备可用的模型凭证（Ollama 无需 Key 也算已配置） */
  configured?: boolean;
}

export interface SystemInfo {
  version: string;
  total_workspaces: number;
  total_documents: number;
  total_chunks: number;
  backend_uptime: number;
}

export interface EmbeddingSettings {
  provider?: string;
  model: string;
  dimension?: number | null;
}

// ============ 工作区接口 ============

export const getWorkspaces = async (): Promise<Workspace[]> => {
  const res = await api.get('/workspaces');
  return res.data;
};

export interface WorkspaceListQuery {
  includeArchived?: boolean;
  archivedOnly?: boolean;
}

export const getWorkspaceList = async (query: WorkspaceListQuery = {}): Promise<Workspace[]> => {
  const params: Record<string, boolean> = {};
  if (query.includeArchived) params.include_archived = true;
  if (query.archivedOnly) params.archived_only = true;
  const res = await api.get('/workspaces', { params });
  return res.data;
};

export const createWorkspace = async (
  name: string,
  description: string,
  extra: Omit<WorkspaceDraft, 'name' | 'description'> = {},
): Promise<Workspace> => {
  const res = await api.post('/workspaces', { name, description, ...extra });
  return res.data;
};

export const updateWorkspace = async (id: string, values: WorkspaceDraft | Partial<WorkspaceDraft>): Promise<Workspace> => {
  const res = await api.put(`/workspaces/${id}`, values);
  return res.data;
};

export const uploadWorkspaceCover = async (id: string, file: File): Promise<Workspace> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post(`/workspaces/${id}/cover`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};

export const clearWorkspaceCover = async (id: string): Promise<Workspace> => {
  const res = await api.delete(`/workspaces/${id}/cover`);
  return res.data;
};

export const getLearningDomains = async (): Promise<LearningDomain[]> => {
  const res = await api.get('/learning-domains');
  return res.data;
};

export const createLearningDomain = async (values: { name: string; description?: string; color?: string }): Promise<LearningDomain> => {
  const res = await api.post('/learning-domains', values);
  return res.data;
};

export const updateLearningDomain = async (id: string, values: { name?: string; description?: string; color?: string }): Promise<LearningDomain> => {
  const res = await api.patch(`/learning-domains/${id}`, values);
  return res.data;
};

export const deleteLearningDomain = async (id: string): Promise<void> => {
  await api.delete(`/learning-domains/${id}`);
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
export const regenerateDocumentLearning = async (id: string, overwriteTags = false): Promise<Document> =>
  (await api.post(`/documents/${id}/regenerate-learning`, null, {
    params: overwriteTags ? { overwrite_tags: true } : {},
  })).data;

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
  weakness_score?: number | null;
}

export interface Flashcard {
  id: string; workspace_id: string; knowledge_point_id?: string | null;
  front: string; back: string; source_label?: string | null;
  source_type: 'manual' | 'knowledge_point' | 'answer' | 'selection';
  source_snapshot?: Record<string, unknown> | Record<string, unknown>[] | null;
  tags: string[]; difficulty: number; mastery: number;
  mastery_status: 'not_started' | 'learning' | 'mastered'; due_at: string;
  interval_days: number; ease: number; review_count: number;
  algorithm_version: string; scheduler_data: Record<string, unknown>;
  last_reviewed_at?: string | null; total_review_seconds: number;
  created_at: string; updated_at: string;
}

export interface CardDraft {
  workspace_id: string; front: string; back: string; source_label?: string | null;
  tags?: string[]; difficulty?: number; due_at?: string;
}

export interface ReviewSummary {
  due_count: number; new_count: number; completed_today: number;
  estimated_minutes: number; streak_days: number; overdue_count: number;
  daily_target: number;
  weak_points: Array<Pick<KnowledgePoint, 'id' | 'workspace_id' | 'title' | 'mastery' | 'mastery_status' | 'importance' | 'is_key'>>;
}

export interface ReviewChange {
  previous_mastery: number; next_mastery: number;
  previous_status: Flashcard['mastery_status']; next_status: Flashcard['mastery_status'];
  previous_interval: number; next_interval: number; duration_seconds: number;
}

export interface ReviewResponse { card: Flashcard; change: ReviewChange }

export interface SelectionCardDraft extends CardDraft {
  document_id: string; source_excerpt: string; source_page?: number | null; source_heading?: string | null;
}

export interface QuizQuestion {
  id: string; workspace_id: string; knowledge_point_id?: string | null;
  question_type: 'choice' | 'true_false' | 'short'; prompt: string;
  options?: string[] | null; answer?: string; explanation: string;
  source_label?: string | null; attempts: number; correct_attempts: number;
  last_answer?: string | null; last_correct?: boolean | null;
}

export type DashboardTask = {
  type: string;
  title: string;
  path: string | null;
  count?: number;
  id?: string;
  knowledge_point_id?: string | null;
  workspace_id?: string;
  due_at?: string | null;
  priority?: number;
  status?: 'pending' | 'completed' | 'dismissed';
  description?: string;
  estimated_minutes?: number;
  source?: { type: string; [key: string]: unknown };
  derived?: boolean;
};

export type GoalProgress = {
  id: string; scope_type: 'global' | 'workspace'; workspace_id?: string | null;
  metric: string; actual: number; target: number; ratio: number;
  status: 'not_started' | 'in_progress' | 'completed'; target_date?: string | null;
  is_active: boolean; version: number;
};
export type DashboardLearningQueue = {
  due_reviews: { count: number; path: string };
  mistakes: { count: number; path: string };
};
export type WorkspaceRecommendation = {
  workspace_id: string; name: string; description: string; domain?: string;
  accent_color: string; score: number; reason: string; path: string;
  components: { goal_urgency: number; weakness: number; unfinished_work: number; recent_activity: number; new_material: number };
  last_activity_at?: string | null;
};
export type DashboardActivity = {
  id: string; workspace_id?: string | null; type: string; title: string;
  duration_seconds: number; created_at: string; occurred_at?: string;
  source_type?: string | null; source_id?: string | null;
};

export interface LearningDashboard {
  profile: { display_name: string; daily_goal_minutes: number; daily_review_target: number; weekly_goal_days: number; timezone_name: string };
  stats: { workspace_count: number; document_count: number; knowledge_point_count: number; due_cards: number; wrong_questions: number; today_minutes: number; week_minutes: number; streak_days: number };
  today_tasks: DashboardTask[];
  weak_points: KnowledgePoint[];
  recent_activities: DashboardActivity[];
  recent_workspaces: Workspace[];
  goal_progress: Record<string, GoalProgress>;
  learning_queue: DashboardLearningQueue;
  recommended_workspaces: WorkspaceRecommendation[];
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
export type StudySession = {
  id: string; workspace_id?: string | null; context_type: 'document' | 'conversation';
  context_id: string; started_at: string; last_heartbeat_at: string;
  ended_at?: string | null; active_seconds: number; status: 'active' | 'completed' | 'expired';
  last_sequence: number;
};
export const startStudySession = async (values: {
  id: string; context_type: 'document' | 'conversation'; context_id: string; workspace_id?: string;
}): Promise<StudySession> => (await api.post('/learning/study-sessions/start', values)).data;
export const heartbeatStudySession = async (id: string, sequence: number): Promise<StudySession> =>
  (await api.post(`/learning/study-sessions/${id}/heartbeat`, { sequence })).data;
export const finishStudySession = async (id: string, sequence: number): Promise<unknown> =>
  (await api.post(`/learning/study-sessions/${id}/finish`, { sequence })).data;
export const finishStudySessionKeepalive = async (id: string, sequence: number): Promise<unknown> => {
  const token = authToken();
  const response = await fetch(`/api/learning/study-sessions/${id}/finish`, {
    method: 'POST', keepalive: true,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ sequence }),
  });
  if (!response.ok) throw new Error(`Study session finish failed: ${response.status}`);
  return response.json();
};
export interface LearningProfile { id: string; display_name: string; daily_goal_minutes: number; daily_review_target: number; weekly_goal_days: number; timezone_name: string; preferred_mode: string; reminder_time?: string }
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
export const getCards = async (
  dueOnly = false,
  workspaceId?: string,
  filters: { sourceType?: Flashcard['source_type']; tag?: string; query?: string } = {},
): Promise<Flashcard[]> => (await api.get('/learning/cards', { params: {
  due_only: dueOnly,
  workspace_id: workspaceId,
  source_type: filters.sourceType,
  tag: filters.tag,
  query: filters.query,
} })).data;
export const createCard = async (values: CardDraft): Promise<Flashcard> => (await api.post('/learning/cards', values)).data;
export const updateCard = async (id: string, values: Partial<CardDraft>): Promise<Flashcard> => (await api.put(`/learning/cards/${id}`, values)).data;
export const createSelectionCard = async (values: SelectionCardDraft): Promise<Flashcard> => (await api.post('/learning/cards/from-selection', values)).data;
export const generateWorkspaceCards = async (workspaceId: string, knowledgePointIds: string[] = []): Promise<{ created_count: number; cards: Flashcard[] }> =>
  (await api.post(`/learning/workspaces/${workspaceId}/cards/generate`, { knowledge_point_ids: knowledgePointIds })).data;
export const getReviewSummary = async (timezoneOffsetMinutes: number): Promise<ReviewSummary> =>
  (await api.get('/learning/review/summary', { params: { timezone_offset_minutes: timezoneOffsetMinutes } })).data;
export const reviewCard = async (id: string, rating: 1 | 2 | 3 | 4, durationSeconds = 0): Promise<ReviewResponse> =>
  (await api.post(`/learning/cards/${id}/review`, { rating, duration_seconds: durationSeconds })).data;
export const deleteCard = async (id: string): Promise<void> => { await api.delete(`/learning/cards/${id}`); };
export const generateQuiz = async (workspaceId: string, count = 5, documentIds: string[] = []): Promise<QuizQuestion[]> => (await api.post('/learning/quizzes/generate', { workspace_id: workspaceId, document_ids: documentIds, count, question_type: 'mixed' })).data;
export const getQuizzes = async (wrongOnly = false, workspaceId?: string, documentIds: string[] = []): Promise<QuizQuestion[]> => (await api.get('/learning/quizzes', {
  params: { wrong_only: wrongOnly, workspace_id: workspaceId, document_ids: documentIds },
  paramsSerializer: { indexes: null },
})).data;
export const submitQuiz = async (id: string, answer: string): Promise<{ correct: boolean; reference_answer: string; explanation: string; source_label?: string; question: QuizQuestion }> => (await api.post(`/learning/quizzes/${id}/submit`, { answer })).data;

export const generateQuizSet = async (values: QuizSetGenerateRequest): Promise<QuizSetView> =>
  // 出题要走一次完整的模型生成（推理模型可能思考较久），给足等待时间。
  (await api.post('/learning/quiz-sets/generate', values, { timeout: 300000 })).data;
export const listQuizSets = async (scope: QuizSetHistoryScope = {}): Promise<QuizSetHistoryPage> =>
  (await api.get('/learning/quiz-sets', { params: scope })).data;
export const getQuizSet = async (quizSetId: string): Promise<QuizSetView> =>
  (await api.get(`/learning/quiz-sets/${quizSetId}`)).data;
export const createQuizRun = async (quizSetId: string, values: QuizRunCreateRequest = {}): Promise<QuizRunView> =>
  (await api.post(`/learning/quiz-sets/${quizSetId}/runs`, values)).data;
export const startQuizRun = async (runId: string): Promise<QuizRunView> =>
  (await api.post(`/learning/quiz-runs/${runId}/start`)).data;
export const submitQuizQuestion = async (
  runId: string,
  questionId: string,
  values: QuestionSubmitRequest,
): Promise<AttemptResult> => (await api.post(`/learning/quiz-runs/${runId}/questions/${questionId}/submit`, values)).data;
export const submitQuizPaper = async (runId: string, values: PaperSubmitRequest = {}): Promise<QuizRunView> =>
  // 整卷提交可能触发多道主观题的逐个评分，同样需要更长的等待时间。
  (await api.post(`/learning/quiz-runs/${runId}/submit`, values, { timeout: 300000 })).data;
export const retryQuizRun = async (runId: string): Promise<QuizRunView> =>
  (await api.post(`/learning/quiz-runs/${runId}/retry`)).data;
export const retryAttemptGrading = async (attemptId: string): Promise<AttemptResult> =>
  (await api.post(`/learning/attempts/${attemptId}/retry-grading`)).data;
export const getMistakes = async (filters: MistakeFilters = {}): Promise<AssessmentPage<MistakeRecord>> =>
  (await api.get('/learning/mistakes', { params: filters })).data;
export const redoMistake = async (mistakeId: string, values: MistakeRedoRequest): Promise<MistakeRedoResult> =>
  (await api.post(`/learning/mistakes/${mistakeId}/redo`, values)).data;
export const getWeakKnowledge = async (filters: AssessmentListScope = {}): Promise<AssessmentPage<WeakKnowledgeState>> =>
  (await api.get('/learning/weak-knowledge', { params: filters })).data;
export const recalculateWeakKnowledge = async (scope: WeakKnowledgeRecalculationScope = {}): Promise<WeakKnowledgeRecalculation> =>
  (await api.post('/learning/weak-knowledge/recalculate', scope)).data;
export const getLearningTasks = async (filters: LearningTaskFilters = {}): Promise<AssessmentPage<LearningTask>> =>
  (await api.get('/learning/tasks', { params: filters })).data;
export const completeLearningTask = async (taskId: string): Promise<LearningTask> =>
  (await api.post(`/learning/tasks/${taskId}/complete`)).data;
export const getLearningReport = async (days = 7) => (await api.get('/learning/report', { params: { days } })).data;
export type PeriodType = 'day' | 'week' | 'month';
export type ReportSuggestion = {
  id: string; status: 'pending' | 'ready' | 'failed'; suggestion?: string | null;
  model?: string | null; error_message?: string | null; stats_hash: string; generated_at?: string | null;
};
export type ReportComparison = { current: number; previous: number; percent_change: number | null; label: string };
export type LearningReport = {
  period: { type: PeriodType; timezone_name: string; local_start: string; local_end: string; utc_start: string; utc_end: string };
  total_active_seconds: number; activity_count: number; new_knowledge_points: number;
  review_count: number; quiz_accuracy: number; pending_grading_count: number;
  mastery_delta: number; weakness_changes: { improved: number; worsened: number; unchanged: number };
  metrics: Record<string, { value: unknown; evidence_query: { metric: string; period_type: PeriodType; anchor_date: string } }>;
  comparisons: Record<string, ReportComparison>;
  trend: Array<{ date: string; active_seconds: number; activities: number; reviews: number; new_knowledge_points: number }>;
  suggestion?: ReportSuggestion | null;
};
export type ReportEvidenceItem = {
  id: string; kind: string; title: string; duration_seconds: number; occurred_at: string;
  workspace_id?: string | null; workspace_name?: string | null; activity_type?: string;
  source_type?: string | null; source_id?: string | null; source_label: string;
  score?: number | null; max_score?: number; evaluation_status?: string; payload?: Record<string, unknown> | null;
};
export type ReportEvidencePage = { items: ReportEvidenceItem[]; next_cursor?: string | null; metric: string };
export type LearningGoals = {
  timezone_name: string;
  global: Record<string, GoalProgress>;
  workspaces: GoalProgress[];
};
export const getNaturalLearningReport = async (period: PeriodType, anchorDate: string): Promise<LearningReport> =>
  (await api.get(`/learning/reports/${period}`, { params: { anchor_date: anchorDate } })).data;
export const getReportEvidence = async (period: PeriodType, anchorDate: string, metric: string, cursor?: string): Promise<ReportEvidencePage> =>
  (await api.get(`/learning/reports/${period}/evidence`, { params: { anchor_date: anchorDate, metric, cursor } })).data;
export const generateReportSuggestion = async (period: PeriodType, anchorDate: string): Promise<ReportSuggestion> =>
  (await api.post(`/learning/reports/${period}/suggestion`, undefined, { params: { anchor_date: anchorDate } })).data;
export const getLearningGoals = async (): Promise<LearningGoals> => (await api.get('/learning/goals')).data;
export const updateGlobalGoals = async (values: {
  daily_minutes: number; daily_reviews: number; weekly_days: number; target_completion_date: string; timezone_name: string;
}): Promise<LearningGoals> => (await api.put('/learning/goals/global', values)).data;
export const updateWorkspaceGoal = async (workspaceId: string, values: { target_mastery: number; target_date: string }): Promise<GoalProgress> =>
  (await api.put(`/learning/goals/workspaces/${workspaceId}`, values)).data;
export const deleteWorkspaceGoal = async (workspaceId: string): Promise<GoalProgress> =>
  (await api.delete(`/learning/goals/workspaces/${workspaceId}`)).data;
export const exportLearningData = async () => (await api.get('/learning/export')).data;
export const createActivity = async (values: { workspace_id?: string; activity_type: string; title: string; duration_seconds?: number; payload?: object }) => (await api.post('/learning/activities', values)).data;
export const documentContentUrl = (id: string) => `/api/documents/${id}/content`;
export const getDocumentObjectUrl = async (id: string): Promise<string> => {
  const response = await api.get(`/documents/${id}/content`, { responseType: 'blob' });
  return URL.createObjectURL(response.data);
};

export interface AuthStatus { configured: boolean; setup_required: boolean; login_required: boolean }
export const getAuthStatus = async (): Promise<AuthStatus> => (await api.get('/auth/status')).data;

const storeSession = (payload: { token: string; user: CurrentUser }): CurrentUser => {
  localStorage.setItem('knowbase_session', payload.token);
  return payload.user;
};

export const setupAccount = async (values: { username: string; password: string; display_name?: string }): Promise<CurrentUser> =>
  storeSession((await api.post('/auth/setup', values)).data);

export const loginAccount = async (values: { username: string; password: string }): Promise<CurrentUser> =>
  storeSession((await api.post('/auth/login', values)).data);

export const logoutAccount = async (): Promise<void> => {
  try {
    await api.post('/auth/logout');
  } finally {
    localStorage.removeItem('knowbase_session');
  }
};

export const getMe = async (): Promise<CurrentUser> => (await api.get('/me')).data;
export const updateMe = async (values: { display_name?: string; avatar_url?: string; clear_avatar?: boolean }): Promise<CurrentUser> =>
  (await api.patch('/me', values)).data;
export const uploadAvatar = async (file: File): Promise<CurrentUser> => {
  const formData = new FormData();
  formData.append('file', file);
  return (await api.post('/me/avatar', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })).data;
};
export const clearAvatar = async (): Promise<CurrentUser> => (await api.delete('/me/avatar')).data;
export const getPreferences = async (): Promise<LearningPreferences> => (await api.get('/me/preferences')).data;
export const updatePreferences = async (values: Partial<LearningPreferences>): Promise<LearningPreferences> =>
  (await api.put('/me/preferences', values)).data;

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

export const updateEmbeddingSettings = async (
  values: { provider?: string; model?: string } | string,
): Promise<EmbeddingSettings> => {
  const payload = typeof values === 'string' ? { model: values } : values;
  const res = await api.put('/settings/embedding', payload);
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

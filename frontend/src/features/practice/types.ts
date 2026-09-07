export type PracticeAnswer = string | string[];

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type ReferenceAnswerPayload = JsonValue;
export type GradingRubricPayload = JsonValue;
export type AttemptFeedbackPayload = JsonValue;

export type AssessmentQuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'fill_blank'
  | 'short_answer'
  | 'concept_explanation';
export type AssessmentDifficulty = 'easy' | 'medium' | 'hard';
export type AssessmentAnswerMode = 'sequential' | 'full_paper';
export type QuizSetStatus = 'generating' | 'ready' | 'failed';
export type QuizRunStatus = 'not_started' | 'in_progress' | 'submitted';
export type AttemptEvaluationStatus = 'graded' | 'pending_ai' | 'grading_failed';
export type MistakeMasteryStatus = 'unresolved' | 'improving' | 'mastered';
export type LearningTaskStatus = 'pending' | 'completed' | 'dismissed';
export type LearningTaskType = 'reread' | 'simple_explanation' | 'new_example' | 'targeted_practice' | 'review';

export interface AssessmentSourceSnapshot {
  chunk_id?: string;
  document_id?: string;
  source_file?: string;
  page?: number;
  [key: string]: JsonValue | undefined;
}

export interface QuizAttempt {
  id: string;
  quiz_set_id: string;
  quiz_run_id: string;
  question_id: string;
  attempt_number: number;
  user_answer: PracticeAnswer;
  is_correct: boolean | null;
  score: number | null;
  max_score: number;
  evaluation_status: AttemptEvaluationStatus;
  feedback: AttemptFeedbackPayload | null;
  error_reason: string | null;
  duration_seconds: number;
  submitted_at: string;
}

export interface AssessmentQuestion {
  id: string;
  quiz_set_id: string | null;
  workspace_id: string;
  document_id: string | null;
  knowledge_point_id: string | null;
  question_type: AssessmentQuestionType;
  prompt: string;
  options: string[] | null;
  difficulty: AssessmentDifficulty;
  position: number;
  source_snapshot: AssessmentSourceSnapshot[];
  strict_sources: boolean;
  generation_model: string | null;
  attempt?: QuizAttempt;
  answer?: string;
  answer_payload?: ReferenceAnswerPayload;
  explanation?: string;
  grading_rubric?: GradingRubricPayload;
}

export interface QuizRunSummary {
  id: string;
  quiz_set_id: string;
  round_number: number;
  answer_mode: AssessmentAnswerMode;
  question_ids: string[] | null;
  status: QuizRunStatus;
  started_at: string | null;
  submitted_at: string | null;
  elapsed_seconds: number;
  score: number;
  max_score: number;
  correct_count: number;
  graded_count: number;
  created_at: string;
  updated_at: string;
  attempts: QuizAttempt[];
}

export interface QuizSetView {
  id: string;
  workspace_id: string;
  title: string;
  document_ids: string[];
  knowledge_point_ids: string[];
  section_filters: string[];
  question_count: number;
  difficulty: AssessmentDifficulty;
  question_types: AssessmentQuestionType[];
  strict_sources: boolean;
  answer_mode: AssessmentAnswerMode;
  duration_limit_seconds: number | null;
  status: QuizSetStatus;
  generation_model: string | null;
  generation_error: string | null;
  created_at: string;
  updated_at: string;
  questions: AssessmentQuestion[];
  latest_run: QuizRunSummary | null;
}

export interface QuizRunView extends QuizRunSummary {
  quiz_set: QuizSetView;
}

export interface QuizSetGenerateRequest {
  workspace_id: string;
  title?: string;
  document_ids?: string[];
  knowledge_point_ids?: string[];
  section_filters?: string[];
  count?: number;
  difficulty?: AssessmentDifficulty;
  question_types?: AssessmentQuestionType[];
  strict_sources?: boolean;
  answer_mode?: AssessmentAnswerMode;
  duration_limit_seconds?: number;
}

export interface QuizRunCreateRequest {
  answer_mode?: AssessmentAnswerMode;
  resume_unsubmitted?: boolean;
}

export interface QuestionSubmitRequest {
  answer: PracticeAnswer;
  duration_seconds?: number;
}

export interface PaperSubmitRequest {
  answers?: Record<string, PracticeAnswer>;
  duration_seconds?: number;
}

export interface AttemptResult {
  attempt: QuizAttempt;
  run: QuizRunView;
}

export interface AssessmentPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface AssessmentListScope {
  workspace_id?: string;
  document_id?: string;
  knowledge_point_id?: string;
  limit?: number;
  offset?: number;
}

export type WeakKnowledgeRecalculationScope = Pick<
  AssessmentListScope,
  'workspace_id' | 'document_id' | 'knowledge_point_id'
>;

export interface MistakeRecord {
  id: string;
  question_id: string;
  knowledge_point_id: string | null;
  workspace_id: string;
  latest_attempt_id: string | null;
  user_answer_snapshot: ReferenceAnswerPayload;
  correct_answer_snapshot: ReferenceAnswerPayload;
  error_reason: string | null;
  source_snapshot: AssessmentSourceSnapshot[];
  wrong_count: number;
  redo_count: number;
  consecutive_correct: number;
  mastery_status: MistakeMasteryStatus;
  first_wrong_at: string;
  last_wrong_at: string;
  last_redone_at: string | null;
  resolved_at: string | null;
  question: AssessmentQuestion;
  document_id: string | null;
  knowledge_point_title: string | null;
  source_label: string | null;
  source_type: 'chat' | 'quiz';
}

export interface MistakeRedoRequest {
  answer: PracticeAnswer;
  duration_seconds?: number;
}

export interface MistakeRedoResult extends AttemptResult {
  mistake: MistakeRecord;
}

export interface WeakKnowledgeState {
  id: string;
  knowledge_point_id: string;
  workspace_id: string;
  weakness_score: number;
  accuracy_component: number;
  repeat_error_component: number;
  review_feedback_component: number;
  response_time_component: number;
  recency_component: number;
  evidence: JsonValue;
  recommended_actions: Array<{ type: string; label: string; path: string }>;
  calculated_at: string;
  knowledge_point_title: string | null;
  document_id: string | null;
  source_page: number | null;
  source_heading: string | null;
}

export interface WeakKnowledgeRecalculation {
  recalculated_count: number;
  knowledge_point_ids: string[];
}

export interface LearningTask {
  id: string;
  workspace_id: string;
  knowledge_point_id: string | null;
  task_type: LearningTaskType;
  title: string;
  path: string | null;
  payload: JsonValue;
  due_at: string | null;
  priority: number;
  status: LearningTaskStatus;
  created_at: string;
  completed_at: string | null;
  knowledge_point_title: string | null;
  document_id: string | null;
  source_page: number | null;
  source_heading: string | null;
}

export interface LearningTaskFilters extends AssessmentListScope {
  status?: LearningTaskStatus;
  due_before?: string;
  due_after?: string;
}

export interface MistakeFilters extends AssessmentListScope {
  mastery_status?: MistakeMasteryStatus;
}

export interface PracticeSessionDraft {
  version: 1;
  runId: string;
  answers: Record<string, PracticeAnswer>;
}

export interface PracticeSessionState {
  run: QuizRunView;
  questions: AssessmentQuestion[];
  answers: Record<string, PracticeAnswer>;
  attemptsByQuestionId: Record<string, QuizAttempt>;
  revealedQuestionIds: ReadonlySet<string>;
  createdAt: number;
}

export interface PracticeResultSummary {
  gradedCount: number;
  correctCount: number;
  score: number;
  maxScore: number;
  accuracyPercent: number;
  pendingQuestionIds: string[];
  gradingFailedQuestionIds: string[];
}

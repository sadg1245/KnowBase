import type {
  AssessmentPage,
  AttemptResult,
  LearningTaskFilters,
  MistakeFilters,
  MistakeMasteryStatus,
  MistakeRecord,
  MistakeRedoResult,
  QuizAttempt,
  PracticeAnswer,
  WeakKnowledgeRecalculationScope,
} from './types';

interface MistakeFilterSelection {
  workspaceId?: string;
  documentId?: string;
  knowledgePointId?: string;
  masteryStatus?: MistakeMasteryStatus;
  limit: number;
  offset: number;
}

interface WeakFilterSelection {
  workspaceId?: string;
  documentId?: string;
  knowledgePointId?: string;
  limit: number;
  offset: number;
}

export const mistakeListFilters = (selection: MistakeFilterSelection): MistakeFilters => ({
  workspace_id: selection.workspaceId,
  document_id: selection.documentId,
  knowledge_point_id: selection.knowledgePointId,
  mastery_status: selection.masteryStatus,
  limit: selection.limit,
  offset: selection.offset,
});

export const weakKnowledgeListFilters = (selection: WeakFilterSelection) => ({
  workspace_id: selection.workspaceId,
  document_id: selection.documentId,
  knowledge_point_id: selection.knowledgePointId,
  limit: selection.limit,
  offset: selection.offset,
});

export const weakKnowledgeRecalculationScope = (
  selection: Pick<WeakFilterSelection, 'workspaceId' | 'documentId' | 'knowledgePointId'>,
): WeakKnowledgeRecalculationScope => ({
  workspace_id: selection.workspaceId,
  document_id: selection.documentId,
  knowledge_point_id: selection.knowledgePointId,
});

export const dueLearningTaskFilters = (dueBefore: string, limit = 50, offset = 0): LearningTaskFilters => ({
  status: 'pending',
  due_before: dueBefore,
  limit,
  offset,
});

export const replaceMistakeFromRedo = (
  mistakes: MistakeRecord[],
  result: MistakeRedoResult,
): { mistakes: MistakeRecord[]; attemptsByMistakeId: Record<string, QuizAttempt> } => ({
  mistakes: mistakes.map(item => item.id === result.mistake.id ? result.mistake : item),
  attemptsByMistakeId: { [result.mistake.id]: result.attempt },
});

interface RetryMistakeGradingOptions {
  token: number;
  isCurrent: (token: number) => boolean;
  attemptId: string;
  retryGrading: (attemptId: string) => Promise<AttemptResult>;
  loadMistakes: () => Promise<AssessmentPage<MistakeRecord>>;
}

export const redoMistakeAndRefresh = async ({
  token, isCurrent, mistakeId, answer, redo, loadMistakes,
}: {
  token: number;
  isCurrent: (token: number) => boolean;
  mistakeId: string;
  answer: PracticeAnswer;
  redo: (mistakeId: string, payload: { answer: PracticeAnswer }) => Promise<MistakeRedoResult>;
  loadMistakes: () => Promise<AssessmentPage<MistakeRecord>>;
}): Promise<{ attempt: QuizAttempt; page: AssessmentPage<MistakeRecord> } | null> => {
  const result = await redo(mistakeId, { answer });
  if (!isCurrent(token)) return null;
  const page = await loadMistakes();
  if (!isCurrent(token)) return null;
  return { attempt: result.attempt, page };
};

export const retryMistakeGradingAndRefresh = async ({
  token, isCurrent, attemptId, retryGrading, loadMistakes,
}: RetryMistakeGradingOptions): Promise<{ mistake?: MistakeRecord; attempt: QuizAttempt; page: AssessmentPage<MistakeRecord> } | null> => {
  const result = await retryGrading(attemptId);
  if (!isCurrent(token)) return null;
  const page = await loadMistakes();
  if (!isCurrent(token)) return null;
  const mistake = page.items.find(item => item.question_id === result.attempt.question_id);
  return { mistake, attempt: result.attempt, page };
};

export interface TaskCompletionCoordinator {
  run: <T>(
    taskId: string,
    operation: () => Promise<T>,
    onSuccess: (result: T) => void | Promise<void>,
    onError: (error: unknown) => void | Promise<void>,
  ) => Promise<boolean>;
  dispose: () => void;
}

export const createTaskCompletionCoordinator = (
  onPendingChange: (pendingIds: ReadonlySet<string>) => void,
): TaskCompletionCoordinator => {
  const pendingIds = new Set<string>();
  let active = true;
  const publish = () => { if (active) onPendingChange(new Set(pendingIds)); };
  return {
    run: async <T>(taskId: string, operation: () => Promise<T>, onSuccess: (result: T) => void | Promise<void>, onError: (error: unknown) => void | Promise<void>) => {
      if (pendingIds.has(taskId)) return false;
      pendingIds.add(taskId);
      publish();
      try {
        const result = await operation();
        if (!active) return false;
        await onSuccess(result);
        return true;
      } catch (error) {
        if (!active) return false;
        await onError(error);
        return false;
      } finally {
        pendingIds.delete(taskId);
        publish();
      }
    },
    dispose: () => {
      active = false;
      pendingIds.clear();
    },
  };
};

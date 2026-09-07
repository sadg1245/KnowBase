import type {
  LearningTaskFilters,
  MistakeFilters,
  MistakeMasteryStatus,
  MistakeRecord,
  MistakeRedoResult,
  QuizAttempt,
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

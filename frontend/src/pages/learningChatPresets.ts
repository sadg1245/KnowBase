import type { LearningMode } from '../services/api';

const nonBlank = (value: string | null): string | undefined => value?.trim() || undefined;

export interface RequestedLearningPreset {
  workspaceId?: string;
  knowledgePointId?: string;
  mode?: 'simple';
  prompt?: string;
}

export interface AppliedLearningPreset {
  workspaceId?: string;
  knowledgePointId?: string;
  knowledgePointTitle?: string;
  documentIds: string[];
  mode?: LearningMode;
  draft: string;
  shouldAutoSend: false;
}

export const requestedLearningPreset = (params: URLSearchParams): RequestedLearningPreset => ({
  workspaceId: nonBlank(params.get('workspace')) ?? nonBlank(params.get('workspace_id')),
  knowledgePointId: nonBlank(params.get('knowledge_point_id')),
  mode: params.get('mode') === 'simple' ? 'simple' : undefined,
  prompt: nonBlank(params.get('prompt')),
});

export const applyLearningRecommendationPreset = (
  requested: RequestedLearningPreset,
  workspaces: Array<{ id: string }>,
  points: Array<{ id: string; workspace_id: string; document_id?: string | null; title: string }>,
  readyDocumentIds: string[],
): AppliedLearningPreset => {
  const workspaceId = requested.workspaceId && workspaces.some(item => item.id === requested.workspaceId)
    ? requested.workspaceId
    : undefined;
  const point = workspaceId && requested.knowledgePointId
    ? points.find(item => item.id === requested.knowledgePointId && item.workspace_id === workspaceId)
    : undefined;
  const validPoint = point && (!point.document_id || readyDocumentIds.includes(point.document_id)) ? point : undefined;
  const validRecommendation = Boolean(
    workspaceId
    && requested.mode === 'simple'
    && (!requested.knowledgePointId || validPoint),
  );

  return {
    workspaceId,
    knowledgePointId: validPoint?.id,
    knowledgePointTitle: validPoint?.title,
    documentIds: validPoint?.document_id ? [validPoint.document_id] : [],
    mode: validRecommendation ? requested.mode : undefined,
    draft: validRecommendation && requested.prompt ? requested.prompt : '',
    shouldAutoSend: false,
  };
};

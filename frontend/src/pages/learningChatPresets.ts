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
  mode?: 'simple';
  draft: string;
}

interface ActiveLearningSessionScope {
  workspace_id?: string | null;
  document_ids: string[];
  mode: string;
}

export interface LearningPresetUiActions {
  cancelStream: () => void;
  resetDraft: () => void;
  resetPointTitle: () => void;
  resetDocuments: () => void;
  detachSession: () => void;
  setWorkspace: (workspaceId?: string) => void;
  setDocuments: (documentIds: string[]) => void;
  setMode: (mode: 'simple') => void;
  setDraft: (draft: string) => void;
  setPointTitle: (title?: string) => void;
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
  };
};

export const resetLearningRecommendationPreset = (
  actions: Pick<LearningPresetUiActions, 'cancelStream' | 'resetDraft' | 'resetPointTitle' | 'resetDocuments' | 'detachSession'>,
) => {
  actions.cancelStream();
  actions.detachSession();
  actions.resetDraft();
  actions.resetPointTitle();
  actions.resetDocuments();
};

const sameDocuments = (left: string[], right: string[]) => (
  left.length === right.length && left.every(id => right.includes(id))
);

export const commitLearningRecommendationPreset = (
  preset: AppliedLearningPreset,
  activeSession: ActiveLearningSessionScope | null,
  actions: Pick<LearningPresetUiActions, 'detachSession' | 'setWorkspace' | 'setDocuments' | 'setMode' | 'setDraft' | 'setPointTitle'>,
): boolean => {
  if (!preset.workspaceId || preset.mode !== 'simple') return false;
  if (activeSession && (
    activeSession.workspace_id !== preset.workspaceId
    || activeSession.mode !== preset.mode
    || !sameDocuments(activeSession.document_ids || [], preset.documentIds)
  )) actions.detachSession();
  actions.setWorkspace(preset.workspaceId);
  actions.setDocuments(preset.documentIds);
  actions.setMode(preset.mode);
  actions.setDraft(preset.draft);
  actions.setPointTitle(preset.knowledgePointTitle);
  return true;
};

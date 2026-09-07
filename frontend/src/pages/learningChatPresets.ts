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

export interface LearningPresetUiActions {
  cancelStream: () => void;
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

export type LearningRecommendationCommand =
  | { type: 'cancel-stream' }
  | { type: 'detach-session' }
  | { type: 'set-workspace'; value: string }
  | { type: 'set-documents'; value: string[] }
  | { type: 'set-mode'; value: 'simple' }
  | { type: 'set-draft'; value: string }
  | { type: 'set-point-title'; value?: string };

export const planLearningRecommendationPresetReset = (): LearningRecommendationCommand[] => [
  { type: 'cancel-stream' },
  { type: 'detach-session' },
  { type: 'set-draft', value: '' },
  { type: 'set-point-title', value: undefined },
  { type: 'set-documents', value: [] },
];

export const planLearningRecommendationPresetCommit = (
  preset: AppliedLearningPreset,
): LearningRecommendationCommand[] => {
  if (!preset.workspaceId || preset.mode !== 'simple') return [];
  return [
    { type: 'set-workspace', value: preset.workspaceId },
    { type: 'set-documents', value: preset.documentIds },
    { type: 'set-mode', value: preset.mode },
    { type: 'set-draft', value: preset.draft },
    { type: 'set-point-title', value: preset.knowledgePointTitle },
  ];
};

const unreachableCommand = (command: never): never => {
  throw new Error(`Unsupported learning recommendation command: ${JSON.stringify(command)}`);
};

export const executeLearningRecommendationCommands = (
  commands: LearningRecommendationCommand[],
  actions: LearningPresetUiActions,
) => {
  commands.forEach(command => {
    switch (command.type) {
      case 'cancel-stream': actions.cancelStream(); break;
      case 'detach-session': actions.detachSession(); break;
      case 'set-workspace': actions.setWorkspace(command.value); break;
      case 'set-documents': actions.setDocuments(command.value); break;
      case 'set-mode': actions.setMode(command.value); break;
      case 'set-draft': actions.setDraft(command.value); break;
      case 'set-point-title': actions.setPointTitle(command.value); break;
      default: unreachableCommand(command);
    }
  });
};

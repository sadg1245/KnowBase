interface PracticeWorkspace {
  id: string;
  name: string;
  document_count: number;
}


const nonBlankParam = (value: string | null): string | undefined => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
};


export const requestedPracticeScope = (params: URLSearchParams): {
  workspaceId?: string;
  knowledgePointId?: string;
} => ({
  workspaceId: nonBlankParam(params.get('workspace')) ?? nonBlankParam(params.get('workspace_id')),
  knowledgePointId: nonBlankParam(params.get('knowledge_point_id')),
});


export const resolveRequestedKnowledgePointId = (
  points: Array<{ id: string; workspace_id: string; document_id?: string | null }>,
  requestedId: string | undefined,
  workspaceId: string,
  effectiveDocumentIds: string[],
): string | undefined => {
  if (!requestedId) return undefined;
  const effectiveDocuments = new Set(effectiveDocumentIds);
  const point = points.find(item => item.id === requestedId && item.workspace_id === workspaceId);
  return point && (!point.document_id || effectiveDocuments.has(point.document_id)) ? point.id : undefined;
};


export const practiceWorkspaceOption = (workspace: PracticeWorkspace) => ({
  label: `${workspace.name} · ${workspace.document_count} 个文件`,
  value: workspace.id,
});


export const resolvePracticeWorkspaceSelection = (
  workspaces: PracticeWorkspace[],
  current?: string,
): string | undefined => {
  if (current && workspaces.some(workspace => workspace.id === current)) {
    return current;
  }
  return workspaces.length === 1 && workspaces[0].document_count > 0 ? workspaces[0].id : undefined;
};


export const readyPracticeDocuments = <T extends { status: string }>(documents: T[]): T[] => (
  documents.filter(document => document.status === 'ready')
);


export const resolvePracticeDocumentIds = <T extends { id: string; status: string }>(
  documents: T[],
  selectedIds: string[],
): string[] => {
  const readyIds = readyPracticeDocuments(documents).map(document => document.id);
  if (selectedIds.length === 0) return readyIds;

  const readyIdSet = new Set(readyIds);
  return selectedIds.filter(id => readyIdSet.has(id));
};


export const createPracticeRequestGuard = () => {
  let version = 0;

  return {
    start: () => {
      version += 1;
      return version;
    },
    invalidate: () => { version += 1; },
    isCurrent: (token: number) => token === version,
  };
};


interface GuardedRunRestoration<TQuizSet, TRun extends { status: string }> {
  token: number;
  isCurrent: (token: number) => boolean;
  loadQuizSet: () => Promise<TQuizSet>;
  existingRun: (quizSet: TQuizSet) => TRun | null;
  createRun: (quizSet: TQuizSet) => Promise<TRun>;
  startRun: (run: TRun) => Promise<TRun>;
}


export const restoreGuardedPracticeRun = async <TQuizSet, TRun extends { status: string }>({
  token,
  isCurrent,
  loadQuizSet,
  existingRun,
  createRun,
  startRun,
}: GuardedRunRestoration<TQuizSet, TRun>): Promise<TRun | null> => {
  const quizSet = await loadQuizSet();
  if (!isCurrent(token)) return null;

  let run = existingRun(quizSet);
  if (!run) {
    run = await createRun(quizSet);
    if (!isCurrent(token)) return null;
  }
  if (run.status === 'not_started') {
    run = await startRun(run);
    if (!isCurrent(token)) return null;
  }
  return run;
};


export const finishMatchingPracticeOperation = <T extends { token: number }>(
  current: T | undefined,
  completedToken: number,
): T | undefined => current?.token === completedToken ? undefined : current;


interface GuardedLegacySubmission<T> {
  token: number;
  questionId: string;
  isCurrent: (token: number) => boolean;
  currentQuestionId: () => string | undefined;
  submit: () => Promise<T>;
}


export const submitGuardedLegacyAnswer = async <T>({
  token,
  questionId,
  isCurrent,
  currentQuestionId,
  submit,
}: GuardedLegacySubmission<T>): Promise<T | null> => {
  const result = await submit();
  return isCurrent(token) && currentQuestionId() === questionId ? result : null;
};


export const practiceDocumentPlaceholder = (
  workspaceId: string | undefined,
  documents: { status: string }[],
): string => {
  if (!workspaceId) return '先选择知识库';
  return readyPracticeDocuments(documents).length ? '全部已解析文件' : '该知识库暂无可用文件';
};

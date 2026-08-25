interface PracticeWorkspace {
  id: string;
  name: string;
  document_count: number;
}


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


export const practiceDocumentPlaceholder = (
  workspaceId: string | undefined,
  documents: { status: string }[],
): string => {
  if (!workspaceId) return '先选择知识库';
  return readyPracticeDocuments(documents).length ? '全部已解析文件' : '该知识库暂无可用文件';
};

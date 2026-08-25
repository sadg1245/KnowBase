export interface DocumentWithStatus {
  id: string;
  status: string;
}

export const resolveWorkspaceSelection = <T extends { id: string }>(
  workspaces: T[],
  current?: string,
): string | undefined => {
  if (current && workspaces.some(workspace => workspace.id === current)) return current;
  return workspaces.length === 1 ? workspaces[0].id : undefined;
};

export const resetDocumentScope = (): string[] => [];

export const resolveDocumentScopeOnWorkspaceLoad = (pending?: string[]): string[] => (
  pending ? [...pending] : resetDocumentScope()
);

export const documentOptionLabel = (document: { filename: string; created_at: string }): string => {
  const importedAt = new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(document.created_at));
  return `${document.filename} · ${importedAt} 导入`;
};

const documentStatusLabels: Record<string, string> = {
  ready: '已解析',
  processing: '解析中',
  pending: '等待解析',
  failed: '解析失败',
};

export const documentSelectionOption = (document: DocumentWithStatus & { filename: string; created_at: string }) => ({
  label: `${documentOptionLabel(document)} · ${documentStatusLabels[document.status] ?? document.status}`,
  value: document.id,
  disabled: document.status !== 'ready',
});

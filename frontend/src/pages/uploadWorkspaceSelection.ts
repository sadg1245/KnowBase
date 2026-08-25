interface WorkspaceOption {
  id: string;
}

/** Resolve the upload target after the available workspaces have loaded. */
export function resolveUploadWorkspace(
  workspaces: WorkspaceOption[],
  selectedWorkspace: string,
): string {
  if (selectedWorkspace) {
    return workspaces.some((workspace) => workspace.id === selectedWorkspace)
      ? selectedWorkspace
      : '';
  }

  return workspaces.length === 1 ? workspaces[0].id : '';
}

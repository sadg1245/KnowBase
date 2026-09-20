/**
 * 「学习范围」选择器与内部 RetrievalScope 的映射。
 *
 * 设计依据：docs/superpowers/specs/2026-09-18-ai-learning-scope-dynamic-retrieval-design.md
 * 用户只看到「学习范围」，不接触 top-k / filter / collection 等检索内部概念。
 */

export type ScopeMode = 'strict' | 'focused' | 'smart' | 'global';

export type ScopeChoice = 'smart' | 'workspace' | 'document' | 'documents' | 'global';

export interface RetrievalScopePayload {
  mode: ScopeMode;
  workspace_ids: string[];
  document_ids: string[];
  knowledge_point_ids: string[];
  allow_workspace_expansion: boolean;
}

export interface ScopeInput {
  workspaceId?: string;
  documentIds: string[];
  knowledgePointId?: string;
  allowWorkspaceExpansion: boolean;
}

export const scopeChoices: ReadonlyArray<{ value: ScopeChoice; label: string; hint: string }> = [
  { value: 'smart', label: '智能选择', hint: '以当前知识库为起点，资料不足时自动扩展' },
  { value: 'workspace', label: '当前知识库', hint: '只在这个知识库里查找，不跨库' },
  { value: 'document', label: '当前文件', hint: '只根据选中的这一个文件回答' },
  { value: 'documents', label: '指定资料', hint: '只根据选中的文件回答，可选择是否允许补充' },
  { value: 'global', label: '全部知识库', hint: '在你的全部私人资料中查找' },
];

export const emptyScope = (): RetrievalScopePayload => ({
  mode: 'smart',
  workspace_ids: [],
  document_ids: [],
  knowledge_point_ids: [],
  allow_workspace_expansion: false,
});

const knowledgePointIds = (input: ScopeInput): string[] =>
  input.knowledgePointId ? [input.knowledgePointId] : [];

/** 去掉 mode 后的范围载荷，用于会话持久化。 */
export const scopeConfigPayload = (
  scope: RetrievalScopePayload,
): Omit<RetrievalScopePayload, 'mode'> => ({
  workspace_ids: scope.workspace_ids,
  document_ids: scope.document_ids,
  knowledge_point_ids: scope.knowledge_point_ids,
  allow_workspace_expansion: scope.allow_workspace_expansion,
});

/** 前端选项 → 后端 RetrievalScope。 */
export const buildScopePayload = (choice: ScopeChoice, input: ScopeInput): RetrievalScopePayload => {
  const workspaceIds = input.workspaceId ? [input.workspaceId] : [];
  const base: RetrievalScopePayload = {
    mode: 'smart',
    workspace_ids: workspaceIds,
    document_ids: [],
    knowledge_point_ids: knowledgePointIds(input),
    allow_workspace_expansion: false,
  };
  switch (choice) {
    case 'workspace':
      return { ...base, mode: 'strict' };
    case 'document':
      return { ...base, mode: 'strict', document_ids: input.documentIds.slice(0, 1) };
    case 'documents':
      return {
        ...base,
        mode: input.allowWorkspaceExpansion ? 'focused' : 'strict',
        document_ids: [...input.documentIds],
        allow_workspace_expansion: input.allowWorkspaceExpansion,
      };
    case 'global':
      return { ...base, mode: 'global', workspace_ids: [] };
    default:
      return { ...base, mode: 'smart', allow_workspace_expansion: true };
  }
};

/** 后端 RetrievalScope → 前端选项（打开历史会话时还原选择器）。 */
export const scopeChoiceFromPayload = (scope?: Partial<RetrievalScopePayload> | null): ScopeChoice => {
  if (!scope?.mode) return 'smart';
  if (scope.mode === 'global') return 'global';
  if (scope.mode === 'smart') return 'smart';
  if (scope.mode === 'focused') return 'documents';
  const documents = scope.document_ids ?? [];
  if (documents.length > 1) return 'documents';
  if (documents.length === 1) return 'document';
  return 'workspace';
};

export const scopeChoiceLabel = (choice: ScopeChoice): string =>
  scopeChoices.find((item) => item.value === choice)?.label ?? '智能选择';

export const scopeSummaryLabel = (choice: ScopeChoice, documentCount: number): string => {
  if (choice === 'documents' && documentCount > 0) return `指定资料 · ${documentCount} 个文件`;
  return scopeChoiceLabel(choice);
};

export interface ScopeNotice {
  mode: ScopeMode;
  expanded: boolean;
  dropped: number;
}

/** 范围扩展/剔除发生后，给用户一句人话解释；没有变化时返回 null。 */
export const scopeNoticeText = (notice?: ScopeNotice | null): string | null => {
  if (!notice) return null;
  if (notice.dropped > 0) return `已忽略 ${notice.dropped} 个不在你资料范围内的选项`;
  if (!notice.expanded) return null;
  return notice.mode === 'smart'
    ? '当前知识库资料不足，已在你的全部知识库中找到补充资料'
    : '已在更大范围内找到补充资料';
};

/** 是否需要用户先选一个知识库：只有限定范围时才必须。 */
export const scopeRequiresWorkspace = (choice: ScopeChoice): boolean => choice === 'workspace';

export const scopeRequiresDocuments = (choice: ScopeChoice): boolean =>
  choice === 'document' || choice === 'documents';

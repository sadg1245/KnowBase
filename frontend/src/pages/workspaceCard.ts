import { LearningStatus, LEARNING_STATUS_LABELS, Workspace } from '../services/api';

export interface WorkspaceCardViewModel {
  domainLabel: string;
  statusLabel: string;
  status: LearningStatus;
  statsLabel: string;
  progressPercent: number;
  coverUrl: string;
  lastStudiedLabel: string | null;
}

/** 知识库卡片展示字段：统计来自真实聚合值，空集合显示为 0。 */
export const workspaceCardViewModel = (workspace: Workspace): WorkspaceCardViewModel => {
  const status = (workspace.learning_status || 'not_started') as LearningStatus;
  const progress = Math.max(0, Math.min(100, Math.round(workspace.learning_progress || 0)));
  return {
    domainLabel: workspace.domain || '未分类',
    status,
    statusLabel: LEARNING_STATUS_LABELS[status] || LEARNING_STATUS_LABELS.not_started,
    statsLabel: `${workspace.document_count || 0} 份资料 · ${workspace.knowledge_point_count || 0} 个知识点`,
    progressPercent: progress,
    coverUrl: workspace.cover_url || '',
    lastStudiedLabel: workspace.last_studied_at ? workspace.last_studied_at.slice(0, 10) : null,
  };
};

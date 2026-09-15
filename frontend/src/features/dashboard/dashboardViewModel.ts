import type { DashboardTask } from '../../services/api';

export type DashboardTaskAction =
  | { kind: 'navigate'; path: string }
  | { kind: 'complete' }
  | { kind: 'none' };

export const dashboardTaskAction = (task: DashboardTask): DashboardTaskAction => {
  const derived = task.derived === true || task.id?.startsWith('derived:');
  if (derived) return task.path ? { kind: 'navigate', path: task.path } : { kind: 'none' };
  if (task.id && task.status === 'pending') return { kind: 'complete' };
  return task.path ? { kind: 'navigate', path: task.path } : { kind: 'none' };
};

export const taskCountLabel = (task: DashboardTask): string => {
  if (task.status === 'completed') return '今日已完成';
  if (typeof task.count !== 'number') return '待完成';
  const unit = task.type === 'review' ? '张' : task.type === 'mistake' ? '道' : '项';
  return `${task.count} ${unit}`;
};

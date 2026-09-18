import type { AuthStatus } from '../../services/api';

export type AuthScreen = 'app' | 'setup' | 'login';

/**
 * 单账号部署的入口判定：已登录直接进入应用，未建号时先建号，其余情况登录。
 * 认证状态不可用时按登录处理，避免绕过认证直接进入应用。
 */
export const resolveAuthScreen = (
  status: AuthStatus | null,
  hasSession: boolean,
): AuthScreen => {
  if (hasSession) return 'app';
  if (!status) return 'login';
  return status.setup_required ? 'setup' : 'login';
};

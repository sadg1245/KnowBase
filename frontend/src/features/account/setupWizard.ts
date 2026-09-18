export interface WizardDecisionInput {
  /** 是否为刚建号的新账号 */
  freshAccount: boolean;
  /** 后端是否已经配置好可用的模型凭证 */
  configured: boolean | null;
  /** 用户是否在本机选择过"稍后配置" */
  dismissed: boolean;
}

/**
 * 是否需要显示"配置你的 AI"向导：
 * - 刚建号的账号一律引导一次；
 * - 老账号在模型还没配好、且没有选择稍后配置时引导；
 * - 配置状态未知（接口失败）时不打扰用户。
 */
export const shouldShowModelWizard = ({
  freshAccount,
  configured,
  dismissed,
}: WizardDecisionInput): boolean => {
  if (freshAccount) return true;
  if (dismissed) return false;
  return configured === false;
};

export const WIZARD_DISMISS_KEY = 'knowbase_model_wizard_dismissed';

export const isWizardDismissed = (storage: Pick<Storage, 'getItem'> | null): boolean => {
  try {
    return storage?.getItem(WIZARD_DISMISS_KEY) === '1';
  } catch {
    return false;
  }
};

export const rememberWizardDismissed = (storage: Pick<Storage, 'setItem'> | null): void => {
  try {
    storage?.setItem(WIZARD_DISMISS_KEY, '1');
  } catch {
    /* 隐私模式下写入失败不影响使用 */
  }
};

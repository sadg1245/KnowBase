/** 练习语境的学习会话：检索层排除解答与答案，避免把参考答案提前交给学习者。 */
export type QuickQuestionMode = 'practice';

export type QuickQuestionState = {
  quickQuestion: string;
  workspaceId?: string;
  mode?: QuickQuestionMode;
  nonce: string;
};

export type ConsumedQuickQuestion = {
  question: string;
  workspaceId?: string;
  mode?: QuickQuestionMode;
  nonce: string;
};

export const quickQuestionDestination = (
  question: string,
  workspaceId: string | undefined,
  nonce: string,
  mode?: QuickQuestionMode,
) => {
  const state: QuickQuestionState = { quickQuestion: question, nonce };
  if (workspaceId) state.workspaceId = workspaceId;
  if (mode) state.mode = mode;
  return { pathname: '/learn', state };
};

export const consumeQuickQuestion = (
  value: unknown,
  consumedNonce?: string,
): ConsumedQuickQuestion | null => {
  if (!value || typeof value !== 'object') return null;
  const state = value as Partial<QuickQuestionState>;
  const question = typeof state.quickQuestion === 'string' ? state.quickQuestion.trim() : '';
  const nonce = typeof state.nonce === 'string' ? state.nonce : '';
  if (!question || !nonce || nonce === consumedNonce) return null;
  const consumed: ConsumedQuickQuestion = { question, nonce };
  if (typeof state.workspaceId === 'string' && state.workspaceId) consumed.workspaceId = state.workspaceId;
  if (state.mode === 'practice') consumed.mode = 'practice';
  return consumed;
};

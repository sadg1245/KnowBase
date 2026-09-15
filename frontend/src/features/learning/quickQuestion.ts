export type QuickQuestionState = {
  quickQuestion: string;
  workspaceId?: string;
  nonce: string;
};

export const quickQuestionDestination = (
  question: string,
  workspaceId: string | undefined,
  nonce: string,
) => ({
  pathname: '/learn',
  state: { quickQuestion: question, workspaceId, nonce } satisfies QuickQuestionState,
});

export const consumeQuickQuestion = (
  value: unknown,
  consumedNonce?: string,
): { question: string; workspaceId?: string; nonce: string } | null => {
  if (!value || typeof value !== 'object') return null;
  const state = value as Partial<QuickQuestionState>;
  const question = typeof state.quickQuestion === 'string' ? state.quickQuestion.trim() : '';
  const nonce = typeof state.nonce === 'string' ? state.nonce : '';
  if (!question || !nonce || nonce === consumedNonce) return null;
  return {
    question,
    workspaceId: typeof state.workspaceId === 'string' && state.workspaceId ? state.workspaceId : undefined,
    nonce,
  };
};

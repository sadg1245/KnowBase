export interface ProviderOption {
  label: string;
  value: string;
}

/** 可选模型提供商；ollama 表示用户自己在本机跑模型，不需要 API Key。 */
export const PROVIDERS: ProviderOption[] = [
  { label: 'DeepSeek（推荐，中文效果好）', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: '阿里通义 (DashScope)', value: 'dashscope' },
  { label: '智谱 AI (GLM)', value: 'zhipu' },
  { label: 'Ollama（本机运行，无需 Key）', value: 'ollama' },
];

export const MODELS: Record<string, ProviderOption[]> = {
  openai: [
    { label: 'GPT-4o', value: 'gpt-4o' },
    { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
    { label: 'GPT-4-Turbo', value: 'gpt-4-turbo' },
    { label: 'GPT-3.5-Turbo', value: 'gpt-3.5-turbo' },
  ],
  deepseek: [
    { label: 'DeepSeek V4 Flash', value: 'deepseek-v4-flash' },
    { label: 'DeepSeek V4 Pro', value: 'deepseek-v4-pro' },
    { label: 'DeepSeek-Chat', value: 'deepseek-chat' },
    { label: 'DeepSeek-Coder', value: 'deepseek-coder' },
  ],
  dashscope: [
    { label: 'Qwen-Max', value: 'qwen-max' },
    { label: 'Qwen-Plus', value: 'qwen-plus' },
    { label: 'Qwen-Turbo', value: 'qwen-turbo' },
  ],
  zhipu: [
    { label: 'GLM-4', value: 'glm-4' },
    { label: 'GLM-4-Flash', value: 'glm-4-flash' },
    { label: 'GLM-3-Turbo', value: 'glm-3-turbo' },
  ],
  ollama: [
    { label: 'qwen2:7b', value: 'qwen2:7b' },
    { label: 'llama3:8b', value: 'llama3:8b' },
    { label: 'mistral:7b', value: 'mistral:7b' },
  ],
};

export const EMBEDDING_MODELS: Record<string, ProviderOption[]> = {
  local: [{ label: 'BGE Small 中文 v1.5（本机运行，首次会自动下载）', value: 'BAAI/bge-small-zh-v1.5' }],
  openai: [
    { label: 'text-embedding-3-small', value: 'text-embedding-3-small' },
    { label: 'text-embedding-3-large', value: 'text-embedding-3-large' },
    { label: 'text-embedding-ada-002', value: 'text-embedding-ada-002' },
  ],
  dashscope: [
    { label: 'text-embedding-v2', value: 'text-embedding-v2' },
    { label: 'text-embedding-v3', value: 'text-embedding-v3' },
  ],
  ollama: [
    { label: 'nomic-embed-text', value: 'nomic-embed-text' },
    { label: 'mxbai-embed-large', value: 'mxbai-embed-large' },
  ],
};

export const defaultModelFor = (provider: string): string =>
  MODELS[provider]?.[0]?.value || '';

export const providerNeedsKey = (provider: string): boolean => provider !== 'ollama';

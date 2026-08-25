import type { EvidenceStatus, LearningMode, SourceItem } from '../../services/api';


export interface DisplayMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources: SourceItem[];
  evidenceStatus?: EvidenceStatus;
  suggestions: string[];
  status: 'streaming' | 'complete' | 'partial' | 'failed';
}

export const learningModes: { value: LearningMode; label: string; hint: string }[] = [
  { value: 'direct', label: '直接回答', hint: '先给结论和最短证据链' },
  { value: 'simple', label: '通俗讲解', hint: '用类比和简单例子解释' },
  { value: 'deep', label: '深度讲解', hint: '原理、推导、例子与误区' },
  { value: 'socratic', label: '苏格拉底引导', hint: '每次追问一个关键问题' },
  { value: 'feynman', label: '费曼学习', hint: '复述后定位理解漏洞' },
  { value: 'quiz', label: '出题测试', hint: '围绕当前资料生成题目' },
];

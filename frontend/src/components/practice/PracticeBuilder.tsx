import React, { useState } from 'react';
import { Button, Checkbox, InputNumber, Radio, Select, Switch } from 'antd';
import { HistoryOutlined, ThunderboltOutlined } from '@ant-design/icons';

import type {
  AssessmentAnswerMode,
  AssessmentDifficulty,
  AssessmentQuestionType,
  QuizSetGenerateRequest,
} from '../../features/practice/types';
import type { Document, KnowledgePoint, Workspace } from '../../services/api';
import { documentSelectionOption } from '../../pages/documentScope';
import {
  practiceDocumentPlaceholder,
  practiceWorkspaceOption,
  readyPracticeDocuments,
  resolvePracticeDocumentIds,
} from '../../pages/practiceScope';


const QUESTION_TYPES: Array<{ label: string; value: AssessmentQuestionType }> = [
  { label: '单项选择题', value: 'single_choice' },
  { label: '多项选择题', value: 'multiple_choice' },
  { label: '判断题', value: 'true_false' },
  { label: '填空题', value: 'fill_blank' },
  { label: '简答题', value: 'short_answer' },
  { label: '解释概念题', value: 'concept_explanation' },
];

const DEFAULT_QUESTION_TYPES = QUESTION_TYPES.map(item => item.value);

export interface QuizSetRequestValues {
  workspaceId: string;
  documents: Pick<Document, 'id' | 'status'>[];
  selectedDocumentIds: string[];
  selectedKnowledgePointIds: string[];
  count: number;
  difficulty: AssessmentDifficulty;
  questionTypes: AssessmentQuestionType[];
  strictSources: boolean;
  answerMode: AssessmentAnswerMode;
  durationMinutes: number | null;
}

export const buildQuizSetGenerateRequest = (values: QuizSetRequestValues): QuizSetGenerateRequest => {
  const duration = values.durationMinutes && values.durationMinutes > 0
    ? { duration_limit_seconds: Math.round(values.durationMinutes * 60) }
    : {};
  return {
    workspace_id: values.workspaceId,
    document_ids: resolvePracticeDocumentIds(values.documents, values.selectedDocumentIds),
    knowledge_point_ids: [...values.selectedKnowledgePointIds],
    section_filters: [],
    count: values.count,
    difficulty: values.difficulty,
    question_types: [...values.questionTypes],
    strict_sources: values.strictSources,
    answer_mode: values.answerMode,
    ...duration,
  };
};

interface PracticeBuilderProps {
  workspaces: Workspace[];
  documents: Document[];
  knowledgePoints: KnowledgePoint[];
  workspaceId?: string;
  selectedDocumentIds: string[];
  selectedKnowledgePointIds: string[];
  workspacesLoading?: boolean;
  scopeLoading?: boolean;
  generating?: boolean;
  onWorkspaceChange: (workspaceId?: string) => void;
  onDocumentChange: (documentIds: string[]) => void;
  onKnowledgePointChange: (knowledgePointIds: string[]) => void;
  onGenerate: (request: QuizSetGenerateRequest) => void | Promise<void>;
}

export const PracticeBuilder: React.FC<PracticeBuilderProps> = ({
  workspaces,
  documents,
  knowledgePoints,
  workspaceId,
  selectedDocumentIds,
  selectedKnowledgePointIds,
  workspacesLoading = false,
  scopeLoading = false,
  generating = false,
  onWorkspaceChange,
  onDocumentChange,
  onKnowledgePointChange,
  onGenerate,
}) => {
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState<AssessmentDifficulty>('medium');
  const [questionTypes, setQuestionTypes] = useState<AssessmentQuestionType[]>(DEFAULT_QUESTION_TYPES);
  const [strictSources, setStrictSources] = useState(true);
  const [answerMode, setAnswerMode] = useState<AssessmentAnswerMode>('sequential');
  const [timed, setTimed] = useState(false);
  const [durationMinutes, setDurationMinutes] = useState(20);
  const readyDocuments = readyPracticeDocuments(documents);
  const effectiveDocumentIds = resolvePracticeDocumentIds(documents, selectedDocumentIds);
  const effectiveDocumentSet = new Set(effectiveDocumentIds);
  const pointOptions = knowledgePoints
    .filter(point => !point.document_id || effectiveDocumentSet.has(point.document_id))
    .map(point => ({ label: point.source_heading ? `${point.title} · ${point.source_heading}` : point.title, value: point.id }));
  const canGenerate = Boolean(workspaceId)
    && !scopeLoading
    && effectiveDocumentIds.length > 0
    && questionTypes.length > 0;

  const generate = () => {
    if (!workspaceId || !canGenerate) return;
    void onGenerate(buildQuizSetGenerateRequest({
      workspaceId,
      documents,
      selectedDocumentIds,
      selectedKnowledgePointIds,
      count,
      difficulty,
      questionTypes,
      strictSources,
      answerMode,
      durationMinutes: timed ? durationMinutes : null,
    }));
  };

  return <section className="practice-builder paper-card" aria-labelledby="practice-builder-title">
    <div className="practice-builder-heading">
      <div>
        <div className="page-eyebrow">ASSESSMENT BRIEF · 自定义测验</div>
        <h2 id="practice-builder-title">出一份真正适合当前阶段的题</h2>
        <p>先圈定资料，再选择题型和作答节奏。答案会在允许揭晓时出现。</p>
      </div>
      <Button href="/practice?wrong=1" icon={<HistoryOutlined />}>历史错题</Button>
    </div>

    <div className="practice-builder-grid">
      <label className="practice-field practice-field-wide">
        <span>知识库</span>
        <Select
          showSearch
          allowClear
          aria-label="知识库"
          placeholder="选择知识库"
          value={workspaceId}
          loading={workspacesLoading}
          onChange={onWorkspaceChange}
          options={workspaces.map(practiceWorkspaceOption)}
          optionFilterProp="label"
        />
      </label>
      <label className="practice-field practice-field-wide">
        <span>资料范围</span>
        <Select
          mode="multiple"
          showSearch
          allowClear
          maxTagCount="responsive"
          aria-label="资料范围"
          placeholder={scopeLoading ? '正在加载资料' : practiceDocumentPlaceholder(workspaceId, documents)}
          value={selectedDocumentIds}
          disabled={!workspaceId || scopeLoading || readyDocuments.length === 0}
          loading={scopeLoading}
          onChange={onDocumentChange}
          options={readyDocuments.map(documentSelectionOption)}
          optionFilterProp="label"
        />
        <small>{selectedDocumentIds.length === 0 && readyDocuments.length > 0 ? `默认使用全部 ${readyDocuments.length} 份已解析资料` : '只会从已解析资料中出题'}</small>
      </label>
      <label className="practice-field practice-field-wide">
        <span>章节或知识点</span>
        <Select
          mode="multiple"
          showSearch
          allowClear
          maxTagCount="responsive"
          aria-label="章节或知识点"
          placeholder="全部章节与知识点"
          value={selectedKnowledgePointIds}
          disabled={!workspaceId || scopeLoading}
          loading={scopeLoading}
          onChange={onKnowledgePointChange}
          options={pointOptions}
          optionFilterProp="label"
        />
      </label>
      <label className="practice-field">
        <span>题目数量</span>
        <InputNumber min={1} max={50} value={count} onChange={value => setCount(value ?? 5)} />
      </label>
      <label className="practice-field">
        <span>难度</span>
        <Select<AssessmentDifficulty>
          value={difficulty}
          onChange={setDifficulty}
          options={[
            { label: '基础', value: 'easy' },
            { label: '适中', value: 'medium' },
            { label: '挑战', value: 'hard' },
          ]}
        />
      </label>
      <fieldset className="practice-field practice-field-full">
        <legend>题型</legend>
        <Checkbox.Group
          className="practice-question-types"
          value={questionTypes}
          onChange={values => setQuestionTypes(values as AssessmentQuestionType[])}
          options={QUESTION_TYPES}
        />
      </fieldset>
      <fieldset className="practice-field practice-field-wide">
        <legend>作答方式</legend>
        <Radio.Group value={answerMode} onChange={event => setAnswerMode(event.target.value)}>
          <Radio.Button value="sequential">逐题答题</Radio.Button>
          <Radio.Button value="full_paper">整卷答题</Radio.Button>
        </Radio.Group>
      </fieldset>
      <div className="practice-field practice-switch-field">
        <span>资料约束</span>
        <div><Switch checked={strictSources} onChange={setStrictSources} /> <strong>严格依据资料</strong></div>
      </div>
      <div className="practice-field practice-duration-field">
        <span>限时</span>
        <div>
          <Switch checked={timed} onChange={setTimed} />
          <InputNumber
            min={1}
            max={240}
            value={durationMinutes}
            disabled={!timed}
            onChange={value => setDurationMinutes(value ?? 20)}
          />
          <em>分钟</em>
        </div>
      </div>
    </div>

    <div className="practice-builder-footer">
      <span>{questionTypes.length ? `已选 ${questionTypes.length} 种题型` : '至少选择一种题型'}</span>
      <Button
        type="primary"
        size="large"
        icon={<ThunderboltOutlined />}
        loading={generating}
        disabled={!canGenerate}
        onClick={generate}
      >生成测验</Button>
    </div>
  </section>;
};

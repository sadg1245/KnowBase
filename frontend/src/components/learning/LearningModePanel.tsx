import React from 'react';
import { Select, Switch, Tag, Typography } from 'antd';
import { CheckCircleFilled, ExclamationCircleFilled } from '@ant-design/icons';

import type { Document, LearningMode, Workspace } from '../../services/api';
import { evidenceStatusLabel } from '../../features/learning/learningConversationState';
import { answerPolicyLabel } from '../../features/learning/answerLayers';
import { learningModes } from '../../features/learning/types';
import { documentSelectionOption } from '../../pages/documentScope';
import { scopeChoices, type ScopeChoice } from '../../pages/learningScope';


const { Text } = Typography;

interface Props {
  workspaces: Workspace[];
  workspaceId?: string;
  documents: Document[];
  documentIds: string[];
  documentsLoading: boolean;
  mode: LearningMode;
  evidenceStatus?: string;
  degradationReason?: string;
  onWorkspace: (value?: string) => void;
  onDocuments: (value: string[]) => void;
  onMode: (value: LearningMode) => void;
  scopeChoice?: ScopeChoice;
  onScopeChoice?: (value: ScopeChoice) => void;
  allowWorkspaceExpansion?: boolean;
  onAllowWorkspaceExpansion?: (value: boolean) => void;
}


export const LearningModePanel: React.FC<Props> = ({
  workspaces, workspaceId, documents, documentIds, documentsLoading, mode,
  evidenceStatus, degradationReason, onWorkspace, onDocuments, onMode,
  scopeChoice = 'smart', onScopeChoice, allowWorkspaceExpansion = false, onAllowWorkspaceExpansion,
}) => <aside className="learning-mode-panel" aria-label="学习设置">
  <section>
    <Text className="learning-panel-label">学习范围</Text>
    <Select
      value={scopeChoice}
      onChange={(value: ScopeChoice) => onScopeChoice?.(value)}
      optionFilterProp="label"
      options={scopeChoices.map((item) => ({
        label: item.label,
        value: item.value,
        title: item.hint,
      }))}
    />
    {scopeChoice === 'documents' ? <label className="learning-scope-toggle">
      <Switch size="small" checked={allowWorkspaceExpansion} onChange={onAllowWorkspaceExpansion} />
      <span>资料不足时搜索当前知识库</span>
    </label> : null}
    <Text type="secondary">{scopeChoices.find((item) => item.value === scopeChoice)?.hint}</Text>
  </section>
  <section>
    <Text className="learning-panel-label">资料范围</Text>
    <Select
      showSearch
      allowClear
      value={workspaceId}
      onChange={onWorkspace}
      placeholder="选择知识库"
      optionFilterProp="label"
      options={workspaces.map((item) => ({ label: item.name, value: item.id }))}
    />
    <Select
      mode="multiple"
      allowClear
      maxTagCount="responsive"
      value={documentIds}
      onChange={onDocuments}
      placeholder={workspaceId ? '全部文件' : '先选择知识库'}
      loading={documentsLoading}
      disabled={!workspaceId || documentsLoading || documents.length === 0}
      optionFilterProp="label"
      options={documents.map(documentSelectionOption)}
    />
  </section>
  <section>
    <Text className="learning-panel-label">学习方式</Text>
    <div className="learning-mode-list">
      {learningModes.map((item) => <button key={item.value} className={mode === item.value ? 'is-active' : ''} onClick={() => onMode(item.value)}>
        <strong>{item.label}</strong><span>{item.hint}</span>
      </button>)}
    </div>
  </section>
  <section className="learning-policy-row">
    <div><strong>资料优先</strong><span>先查你的资料；没查到就明确标注为模型补充</span></div>
  </section>
  <section className="learning-evidence-card">
    <Text className="learning-panel-label">当前证据</Text>
    <Tag icon={evidenceStatus === 'supported' ? <CheckCircleFilled /> : <ExclamationCircleFilled />} color={evidenceStatus === 'supported' ? 'success' : evidenceStatus ? 'warning' : 'default'}>
      {answerPolicyLabel(evidenceStatus)}
    </Tag>
    <Text type="secondary">{evidenceStatusLabel(evidenceStatus)}</Text>
    {degradationReason ? <Text type="secondary">{degradationReason}</Text> : null}
  </section>
</aside>;

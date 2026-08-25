import React from 'react';
import { Select, Switch, Tag, Typography } from 'antd';
import { CheckCircleFilled, ExclamationCircleFilled } from '@ant-design/icons';

import type { Document, LearningMode, Workspace } from '../../services/api';
import { evidenceStatusLabel } from '../../features/learning/learningConversationState';
import { learningModes } from '../../features/learning/types';
import { documentSelectionOption } from '../../pages/documentScope';


const { Text } = Typography;

interface Props {
  workspaces: Workspace[];
  workspaceId?: string;
  documents: Document[];
  documentIds: string[];
  documentsLoading: boolean;
  mode: LearningMode;
  strict: boolean;
  evidenceStatus?: string;
  degradationReason?: string;
  onWorkspace: (value?: string) => void;
  onDocuments: (value: string[]) => void;
  onMode: (value: LearningMode) => void;
  onStrict: (value: boolean) => void;
}


export const LearningModePanel: React.FC<Props> = ({
  workspaces, workspaceId, documents, documentIds, documentsLoading, mode, strict,
  evidenceStatus, degradationReason, onWorkspace, onDocuments, onMode, onStrict,
}) => <aside className="learning-mode-panel" aria-label="学习设置">
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
  <section className="learning-strict-row">
    <div><strong>严格依据资料</strong><span>资料不足时明确拒答</span></div>
    <Switch checked={strict} onChange={onStrict} />
  </section>
  <section className="learning-evidence-card">
    <Text className="learning-panel-label">当前证据</Text>
    <Tag icon={evidenceStatus === 'supported' ? <CheckCircleFilled /> : <ExclamationCircleFilled />} color={evidenceStatus === 'supported' ? 'success' : evidenceStatus ? 'warning' : 'default'}>
      {evidenceStatusLabel(evidenceStatus)}
    </Tag>
    {degradationReason ? <Text type="secondary">{degradationReason}</Text> : null}
  </section>
</aside>;

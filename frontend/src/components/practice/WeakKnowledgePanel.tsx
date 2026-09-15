import React from 'react';
import { Button, Empty, Pagination, Progress, Select, Skeleton, Tag } from 'antd';
import { CompassOutlined, ReloadOutlined } from '@ant-design/icons';

import type { AssessmentListScope, WeakKnowledgeState } from '../../features/practice/types';

type SelectOption = { label: string; value: string };

interface WeakKnowledgePanelProps {
  items: WeakKnowledgeState[];
  total: number;
  filters: AssessmentListScope;
  documentOptions: SelectOption[];
  knowledgePointOptions: SelectOption[];
  loading?: boolean;
  recalculating?: boolean;
  onFiltersChange: (filters: AssessmentListScope) => void;
  onAction: (path: string) => void;
  onRecalculate: () => void | Promise<void>;
}

export const weaknessBand = (score: number): { label: string; className: string; color: string } => {
  if (score >= 80) return { label: '优先处理', className: 'is-high', color: '#a84f4f' };
  if (score >= 60) return { label: '薄弱', className: 'is-medium', color: '#b27a3c' };
  if (score >= 30) return { label: '需要巩固', className: 'is-medium', color: '#b27a3c' };
  return { label: '稳定', className: 'is-low', color: '#167d8d' };
};

const components: Array<{ key: keyof WeakKnowledgeState; label: string; weight: string }> = [
  { key: 'accuracy_component', label: '正确率', weight: '35%' },
  { key: 'repeat_error_component', label: '重复错误', weight: '25%' },
  { key: 'review_feedback_component', label: '复习反馈', weight: '15%' },
  { key: 'response_time_component', label: '答题用时', weight: '10%' },
  { key: 'recency_component', label: '学习间隔', weight: '15%' },
];

const evidenceNumber = (item: WeakKnowledgeState, key: string) => {
  const evidence = item.evidence;
  if (!evidence || typeof evidence !== 'object' || Array.isArray(evidence)) return 0;
  const value = evidence[key];
  return typeof value === 'number' ? value : 0;
};

export const WeakKnowledgePanel: React.FC<WeakKnowledgePanelProps> = ({
  items,
  total,
  filters,
  documentOptions,
  knowledgePointOptions,
  loading = false,
  recalculating = false,
  onFiltersChange,
  onAction,
  onRecalculate,
}) => {
  const limit = filters.limit ?? 20;
  const offset = filters.offset ?? 0;
  const patch = (values: Partial<AssessmentListScope>) => onFiltersChange({ ...filters, ...values, offset: values.offset ?? 0 });

  return <section className="weak-knowledge-panel" aria-labelledby="weak-knowledge-title">
    <div className="practice-loop-heading">
      <div><div className="page-eyebrow">DIAGNOSTIC INDEX · 五项证据</div><h2 id="weak-knowledge-title">薄弱知识行动单</h2></div>
      <Button icon={<ReloadOutlined />} loading={recalculating} onClick={() => void onRecalculate()}>重新计算</Button>
    </div>
    <div className="practice-loop-filters is-compact" aria-label="薄弱知识筛选">
      <Select aria-label="按资料筛选薄弱知识" allowClear placeholder="全部来源资料" value={filters.document_id} options={documentOptions} onChange={document_id => patch({ document_id })} />
      <Select aria-label="按知识点筛选薄弱知识" allowClear placeholder="全部知识点" value={filters.knowledge_point_id} options={knowledgePointOptions} onChange={knowledge_point_id => patch({ knowledge_point_id })} />
    </div>
    {loading ? <div className="paper-card practice-loop-loading"><Skeleton active paragraph={{ rows: 6 }} /></div> : items.length === 0
      ? <div className="paper-card empty-guide"><Empty description="完成练习后，这里会给出证据充分的巩固建议" /></div>
      : <div className="weak-knowledge-list">{items.map(item => {
        const band = weaknessBand(item.weakness_score);
        return <article className={`weak-knowledge-card paper-card ${band.className}`} key={item.id}>
          <div className="weak-knowledge-summary">
            <div><Tag>{band.label}</Tag><h3>{item.knowledge_point_title || '未命名知识点'}</h3><p>{item.source_heading || (item.source_page ? `第 ${item.source_page} 页` : '跨资料综合证据')}</p></div>
            <div className="weak-score" aria-label={`薄弱总分 ${item.weakness_score} 分，${band.label}`}><strong>{Math.round(item.weakness_score)}</strong><span>/ 100</span></div>
          </div>
          <div className="weak-components">{components.map(component => {
            const value = Number(item[component.key]);
            return <div key={component.key} aria-label={`${component.label} ${Math.round(value)} 分，权重 ${component.weight}`}>
              <div><span>{component.label}<small>权重 {component.weight}</small></span><strong>{Math.round(value)}</strong></div>
              <Progress percent={Math.round(value)} showInfo={false} strokeColor={weaknessBand(value).color} trailColor="#e7edef" />
            </div>;
          })}</div>
          <div className="weak-evidence" aria-label="作答证据">
            <strong>作答证据</strong>
            <span>已评分 {evidenceNumber(item, 'graded_attempt_count')} / 全部 {evidenceNumber(item, 'attempt_count')}</span>
            <span>未掌握错题 {evidenceNumber(item, 'unresolved_mistake_count')}</span>
            <span>复习 {evidenceNumber(item, 'review_count')} 次</span>
            <span>用时比较 {evidenceNumber(item, 'duration_comparison_count')} 次</span>
          </div>
          <div className="weak-actions"><strong><CompassOutlined /> 建议下一步</strong><div>{item.recommended_actions.map(action => <Button key={`${action.type}-${action.path}`} href={action.path} onClick={event => { event.preventDefault(); onAction(action.path); }}>{action.label}</Button>)}</div></div>
        </article>;
      })}</div>}
    {total > limit ? <Pagination className="practice-loop-pagination" current={Math.floor(offset / limit) + 1} pageSize={limit} total={total} showSizeChanger pageSizeOptions={[10, 20, 50]} onChange={(page, pageSize) => onFiltersChange({ ...filters, limit: pageSize, offset: (page - 1) * pageSize })} /> : null}
  </section>;
};

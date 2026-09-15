import React, { useEffect, useState } from 'react';
import { Alert, Button, Empty, Pagination, Select, Skeleton, Tag } from 'antd';
import { BookOutlined, CheckCircleOutlined, HistoryOutlined, RedoOutlined } from '@ant-design/icons';

import type {
  AssessmentSourceSnapshot,
  MistakeFilters,
  MistakeMasteryStatus,
  MistakeRecord,
  PracticeAnswer,
  QuizAttempt,
} from '../../features/practice/types';
import { answerIsPresent, QuestionInput } from './QuestionInput';

type SelectOption = { label: string; value: string };

interface MistakeNotebookProps {
  mistakes: MistakeRecord[];
  total: number;
  filters: MistakeFilters;
  workspaceOptions: SelectOption[];
  documentOptions: SelectOption[];
  knowledgePointOptions: SelectOption[];
  loading?: boolean;
  redoingId?: string;
  retryingAttemptId?: string;
  redoAttempts?: Record<string, QuizAttempt>;
  onFiltersChange: (filters: MistakeFilters) => void;
  onRedo: (mistakeId: string, answer: PracticeAnswer) => void | Promise<void>;
  onRetryGrading: (mistakeId: string, attemptId: string) => void | Promise<void>;
  onSource: (path: string) => void;
}

const masteryCopy: Record<MistakeMasteryStatus, string> = {
  unresolved: '尚未掌握',
  improving: '正在改善',
  mastered: '已经掌握',
};

const printable = (value: unknown): string => {
  if (Array.isArray(value)) return value.map(printable).join('、');
  if (value && typeof value === 'object') return JSON.stringify(value, null, 2);
  return value === null || value === undefined || value === '' ? '暂无记录' : String(value);
};

export const mistakeSourcePath = (mistake: MistakeRecord, source: AssessmentSourceSnapshot): string | null => {
  const documentId = typeof source.document_id === 'string' ? source.document_id : mistake.document_id;
  if (!documentId) return null;
  const query = new URLSearchParams();
  if (typeof source.chunk_id === 'string' && source.chunk_id) query.set('chunk', source.chunk_id);
  if (typeof source.page === 'number') query.set('page', String(source.page));
  const suffix = query.toString();
  return `/knowledge/${mistake.workspace_id}/documents/${documentId}${suffix ? `?${suffix}` : ''}`;
};

interface MistakeRedoPanelProps {
  mistake: MistakeRecord;
  answer?: PracticeAnswer;
  attempt?: QuizAttempt;
  redoing?: boolean;
  retrying?: boolean;
  onAnswerChange: (answer: PracticeAnswer) => void;
  onClose: () => void;
  onRedo: (answer: PracticeAnswer) => void | Promise<void>;
  onRetryGrading: (attemptId: string) => void | Promise<void>;
}

export const MistakeRedoPanel: React.FC<MistakeRedoPanelProps> = ({
  mistake, answer: suppliedAnswer, attempt: suppliedAttempt, redoing = false, retrying = false, onAnswerChange, onClose, onRedo, onRetryGrading,
}) => {
  const attempt = suppliedAttempt ?? mistake.recoverable_redo_attempt ?? undefined;
  const awaitingGrade = attempt?.evaluation_status === 'grading_failed' || attempt?.evaluation_status === 'pending_ai';
  const answer = suppliedAnswer ?? (awaitingGrade ? attempt?.user_answer : undefined);
  const subjective = mistake.question.question_type === 'short_answer' || mistake.question.question_type === 'concept_explanation';
  const retryEligible = awaitingGrade && subjective;
  return <div className="mistake-redo">
    <div><strong><RedoOutlined /> 重新练习</strong><Button type="link" onClick={onClose}>收起重新练习</Button></div>
    <small>按题型重新作答；提交后以服务端返回的掌握状态为准。</small>
    <QuestionInput question={mistake.question} value={answer} disabled={redoing || retrying || awaitingGrade} onChange={onAnswerChange} />
    {attempt ? <Alert
      className="mistake-redo-result"
      showIcon
      type={attempt.evaluation_status === 'graded' && attempt.is_correct ? 'success' : attempt.evaluation_status === 'graded' ? 'warning' : 'info'}
      icon={attempt.evaluation_status === 'graded' && attempt.is_correct ? <CheckCircleOutlined /> : <HistoryOutlined />}
      message={attempt.evaluation_status === 'grading_failed'
        ? subjective ? '评分暂未完成，可直接重试' : '评分状态异常，请刷新后再试'
        : attempt.evaluation_status === 'pending_ai'
          ? subjective ? '评分处理中，这次不会计为答错' : '评分状态异常，请刷新后再试'
          : attempt.is_correct ? `回答正确 · ${masteryCopy[mistake.mastery_status]}` : '这次仍需巩固'}
    /> : null}
    {retryEligible && attempt ? <Button type="primary" loading={retrying} onClick={() => void onRetryGrading(attempt.id)}>重新评分</Button>
      : awaitingGrade ? null
      : <Button type="primary" loading={redoing} disabled={!answerIsPresent(answer)} onClick={() => void onRedo(answer!)}>提交重做答案</Button>}
  </div>;
};

export const MistakeNotebook: React.FC<MistakeNotebookProps> = ({
  mistakes,
  total,
  filters,
  workspaceOptions,
  documentOptions,
  knowledgePointOptions,
  loading = false,
  redoingId,
  retryingAttemptId,
  redoAttempts = {},
  onFiltersChange,
  onRedo,
  onRetryGrading,
  onSource,
}) => {
  const [answers, setAnswers] = useState<Record<string, PracticeAnswer>>({});
  const [activeRedoId, setActiveRedoId] = useState<string>();
  const limit = filters.limit ?? 20;
  const offset = filters.offset ?? 0;
  const resetRedo = () => { setActiveRedoId(undefined); setAnswers({}); };
  const patchFilters = (patch: Partial<MistakeFilters>) => {
    resetRedo();
    onFiltersChange({ ...filters, ...patch, offset: patch.offset ?? 0 });
  };
  useEffect(() => {
    resetRedo();
  }, [filters.workspace_id, filters.document_id, filters.knowledge_point_id, filters.mastery_status, filters.limit, filters.offset]);
  const closeRedo = (mistakeId: string) => {
    setActiveRedoId(undefined);
    setAnswers(current => {
      const next = { ...current };
      delete next[mistakeId];
      return next;
    });
  };

  return <section className="mistake-notebook" aria-labelledby="mistake-notebook-title">
    <div className="practice-loop-heading">
      <div><div className="page-eyebrow">ERROR LEDGER · 从错误证据重新出发</div><h2 id="mistake-notebook-title">错题笔记</h2></div>
      <span>{total} 条可追踪记录</span>
    </div>
    <div className="practice-loop-filters" aria-label="错题筛选">
      <Select aria-label="按知识库筛选错题" allowClear placeholder="全部知识库" value={filters.workspace_id} options={workspaceOptions} onChange={workspace_id => patchFilters({ workspace_id, document_id: undefined, knowledge_point_id: undefined })} />
      <Select aria-label="按资料筛选错题" allowClear placeholder="全部来源资料" value={filters.document_id} options={documentOptions} onChange={document_id => patchFilters({ document_id })} />
      <Select aria-label="按知识点筛选错题" allowClear placeholder="全部知识点" value={filters.knowledge_point_id} options={knowledgePointOptions} onChange={knowledge_point_id => patchFilters({ knowledge_point_id })} />
      <Select aria-label="按掌握状态筛选错题" allowClear placeholder="全部掌握状态" value={filters.mastery_status} options={Object.entries(masteryCopy).map(([value, label]) => ({ value, label }))} onChange={mastery_status => patchFilters({ mastery_status })} />
    </div>
    {loading ? <div className="paper-card practice-loop-loading"><Skeleton active paragraph={{ rows: 7 }} /></div> : mistakes.length === 0
      ? <div className="paper-card empty-guide"><Empty description="当前筛选范围还没有错题记录" /></div>
      : <div className="mistake-ledger-list">{mistakes.map((mistake, index) => {
        const answer = answers[mistake.id];
        const latestRedo = redoAttempts[mistake.id] ?? mistake.recoverable_redo_attempt ?? undefined;
        const sources = mistake.source_snapshot.length ? mistake.source_snapshot : mistake.question.source_snapshot;
        return <article className={`mistake-ledger paper-card is-${mistake.mastery_status}`} key={mistake.id}>
          <aside className="mistake-ledger-margin" aria-label={`错题 ${index + 1}，${masteryCopy[mistake.mastery_status]}`}>
            <span className="mistake-ledger-number">{String(index + 1).padStart(2, '0')}</span>
            <Tag>{masteryCopy[mistake.mastery_status]}</Tag>
            <small>错误 {mistake.wrong_count} 次</small>
            <small>重做 {mistake.redo_count} 次</small>
          </aside>
          <div className="mistake-ledger-body">
            <div className="mistake-ledger-meta"><Tag>{mistake.source_type === 'chat' ? '对话错题' : '测验错题'}</Tag><span>最后出错 {new Date(mistake.last_wrong_at).toLocaleDateString('zh-CN')}</span></div>
            <h3>{mistake.question.prompt}</h3>
            <dl className="mistake-ledger-details">
              <div><dt>你的答案</dt><dd>{printable(mistake.user_answer_snapshot)}</dd></div>
              <div><dt>正确答案</dt><dd>{printable(mistake.correct_answer_snapshot)}</dd></div>
              <div><dt>错误原因</dt><dd>{mistake.error_reason || '尚未记录具体原因'}</dd></div>
              <div><dt>知识点</dt><dd>{mistake.knowledge_point_title || '未关联知识点'}</dd></div>
              <div><dt>错误次数</dt><dd>{mistake.wrong_count}</dd></div>
              <div><dt>重做次数</dt><dd>{mistake.redo_count}</dd></div>
              <div><dt>连续答对</dt><dd>{mistake.consecutive_correct}</dd></div>
              <div><dt>当前掌握状态</dt><dd>{masteryCopy[mistake.mastery_status]}</dd></div>
            </dl>
            <div className="mistake-sources"><strong><BookOutlined /> 来源资料</strong>{sources.length ? sources.map((source, sourceIndex) => {
              const path = mistakeSourcePath(mistake, source);
              const label = [source.source_file || mistake.source_label || `证据 ${sourceIndex + 1}`, typeof source.page === 'number' ? `第 ${source.page} 页` : null].filter(Boolean).join(' · ');
              return path ? <Button key={`${path}-${sourceIndex}`} type="link" href={path} onClick={event => { event.preventDefault(); onSource(path); }}>{label}</Button> : <span key={sourceIndex}>{label}</span>;
            }) : <span>{mistake.source_label || '来源位置未记录'}</span>}</div>
            {activeRedoId === mistake.id ? <MistakeRedoPanel
              mistake={mistake}
              answer={answer}
              attempt={latestRedo}
              redoing={redoingId === mistake.id}
              retrying={Boolean(latestRedo && retryingAttemptId === latestRedo.id)}
              onAnswerChange={value => setAnswers(current => ({ ...current, [mistake.id]: value }))}
              onClose={() => closeRedo(mistake.id)}
              onRedo={value => onRedo(mistake.id, value)}
              onRetryGrading={attemptId => onRetryGrading(mistake.id, attemptId)}
            /> : <Button className="mistake-open-redo" icon={<RedoOutlined />} onClick={() => setActiveRedoId(mistake.id)}>{latestRedo && latestRedo.evaluation_status !== 'graded' ? '继续评分' : '打开重新练习'}</Button>}
          </div>
        </article>;
      })}</div>}
    {total > limit ? <Pagination className="practice-loop-pagination" current={Math.floor(offset / limit) + 1} pageSize={limit} total={total} showSizeChanger pageSizeOptions={[10, 20, 50]} onChange={(page, pageSize) => { resetRedo(); onFiltersChange({ ...filters, limit: pageSize, offset: (page - 1) * pageSize }); }} /> : null}
  </section>;
};

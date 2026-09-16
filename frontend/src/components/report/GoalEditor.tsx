import React, { useEffect, useState } from 'react';
import { Alert, Button, Input, InputNumber } from 'antd';
import { CloseOutlined } from '@ant-design/icons';

export type GlobalGoalForm = {
  minutes: number; reviews: number; weeklyDays: number; targetDate: string; timezoneName: string;
};
export type WorkspaceGoalForm = {
  id: string; name: string; targetMastery?: number; targetDate?: string;
};

export const toGlobalGoalPayload = (values: GlobalGoalForm) => {
  if (values.minutes < 5 || values.minutes > 480) throw new Error('每日学习分钟数需在 5–480 之间');
  if (values.reviews < 1 || values.reviews > 200) throw new Error('每日复习卡片数需在 1–200 之间');
  if (values.weeklyDays < 1 || values.weeklyDays > 7) throw new Error('每周学习天数需在 1–7 之间');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.targetDate)) throw new Error('请选择总目标日期');
  if (!values.timezoneName.trim()) throw new Error('请填写 IANA 时区');
  return {
    daily_minutes: values.minutes,
    daily_reviews: values.reviews,
    weekly_days: values.weeklyDays,
    target_completion_date: values.targetDate,
    timezone_name: values.timezoneName.trim(),
  };
};

export const GoalEditor: React.FC<{
  open: boolean;
  initial: GlobalGoalForm;
  workspaces: WorkspaceGoalForm[];
  saving: boolean;
  error?: string;
  onClose: () => void;
  onSave: (global: GlobalGoalForm, workspaces: WorkspaceGoalForm[]) => void;
}> = ({ open, initial, workspaces, saving, error, onClose, onSave }) => {
  const [global, setGlobal] = useState(initial);
  const [workspaceGoals, setWorkspaceGoals] = useState(workspaces);
  const [validation, setValidation] = useState<string>();
  useEffect(() => { if (open) { setGlobal(initial); setWorkspaceGoals(workspaces); setValidation(undefined); } }, [initial, open, workspaces]);
  const save = () => {
    try { toGlobalGoalPayload(global); setValidation(undefined); onSave(global, workspaceGoals); }
    catch (reason) { setValidation(reason instanceof Error ? reason.message : '目标设置无效'); }
  };
  const field = (label: string, value: number, min: number, max: number, key: keyof GlobalGoalForm) => <label>
    <span>{label}</span><InputNumber min={min} max={max} value={value} onChange={next => setGlobal(current => ({ ...current, [key]: Number(next) }))} />
  </label>;
  if (!open) return null;
  return <div className="goal-editor-overlay" role="dialog" aria-modal="true" aria-labelledby="goal-editor-title">
    <div className="goal-editor-dialog">
      <header><div><span className="dashboard-kicker">Learning goals</span><h2 id="goal-editor-title">调整学习目标</h2></div><Button type="text" aria-label="关闭目标编辑" icon={<CloseOutlined />} onClick={onClose} /></header>
      <div className="goal-editor">
      {(error || validation) ? <Alert type="error" showIcon message={error || validation} /> : null}
      <div className="goal-editor-global">
        {field('每日学习分钟数', global.minutes, 5, 480, 'minutes')}
        {field('每日复习卡片数', global.reviews, 1, 200, 'reviews')}
        {field('每周学习天数', global.weeklyDays, 1, 7, 'weeklyDays')}
        <label><span>总目标日期</span><Input type="date" value={global.targetDate} onChange={event => setGlobal(current => ({ ...current, targetDate: event.target.value }))} /></label>
        <label className="goal-editor-wide"><span>IANA 时区</span><Input value={global.timezoneName} onChange={event => setGlobal(current => ({ ...current, timezoneName: event.target.value }))} placeholder="Asia/Shanghai" /></label>
      </div>
      <h3>特定知识库目标</h3>
      <div className="goal-editor-workspaces">{workspaceGoals.length ? workspaceGoals.map((item, index) => <div key={item.id}>
        <strong>{item.name}</strong>
        <label><span>目标掌握度</span><InputNumber min={1} max={100} value={item.targetMastery} placeholder="未设置" onChange={value => setWorkspaceGoals(current => current.map((row, rowIndex) => rowIndex === index ? { ...row, targetMastery: value == null ? undefined : Number(value) } : row))} /></label>
        <label><span>完成日期</span><Input type="date" value={item.targetDate} onChange={event => setWorkspaceGoals(current => current.map((row, rowIndex) => rowIndex === index ? { ...row, targetDate: event.target.value || undefined } : row))} /></label>
      </div>) : <p>创建知识库后，可以为它设置单独的掌握目标。</p>}</div>
      <div className="goal-editor-actions"><Button onClick={onClose}>取消</Button><Button type="primary" loading={saving} onClick={save}>保存学习目标</Button></div>
      </div>
    </div>
  </div>;
};

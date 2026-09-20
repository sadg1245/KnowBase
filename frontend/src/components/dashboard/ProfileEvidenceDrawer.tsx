import React from 'react';
import { Button, Drawer, Empty, Progress, Tag } from 'antd';

import type { ProfileWeakEvidence, ProfileWeakPoint } from '../../services/api';
import {
  attemptAccuracyLabel, attemptMarks, lastStudiedLabel, masteryStatusMeta,
  percent, reviewSummary,
} from '../../features/dashboard/profileViewModel';

const COMPONENT_LABELS: Array<{ key: string; label: string; weight: string }> = [
  { key: 'accuracy', label: '正确率', weight: '35%' },
  { key: 'repeat_error', label: '重复错误', weight: '25%' },
  { key: 'review_feedback', label: '复习反馈', weight: '15%' },
  { key: 'response_time', label: '答题用时', weight: '10%' },
  { key: 'recency', label: '学习间隔', weight: '15%' },
];

export const attemptLine = (evidence: ProfileWeakEvidence): string => {
  const marks = attemptMarks(evidence);
  return marks.length ? `${marks.join(' ')} · ${attemptAccuracyLabel(evidence)}` : attemptAccuracyLabel(evidence);
};

/** 抽屉展示的确定性分节；测试直接断言这些文字，避免界面改版后依据消失。 */
export const evidenceSections = (point: ProfileWeakPoint): Array<{ title: string; lines: string[] }> => {
  const evidence = point.evidence;
  const attemptLines = [
    evidence.recent_attempts.length
      ? `最近 ${evidence.recent_attempts.length} 题：${attemptLine(evidence)}`
      : attemptLine(evidence),
    evidence.mistake_count ? `未掌握错题 ${evidence.mistake_count} 道` : '目前没有未掌握错题',
  ];
  if (evidence.repeat_error_count > evidence.mistake_count) {
    attemptLines.push(`同一批错题累计重复错误 ${evidence.repeat_error_count} 次`);
  }
  const sections: Array<{ title: string; lines: string[] }> = [
    { title: '练习表现', lines: attemptLines },
    { title: '复习表现', lines: [`最近复习：${reviewSummary(evidence)}`] },
  ];
  if (evidence.mistake_patterns.length) {
    sections.push({
      title: '错误记录',
      lines: evidence.mistake_patterns.map(item => `${item.pattern} · 重复错误 ${item.count} 次`),
    });
  }
  sections.push({
    title: '最近学习',
    lines: [lastStudiedLabel(evidence)],
  });
  sections.push({
    title: '系统状态',
    lines: [
      `掌握度 ${percent(point.mastery)}%（${point.mastery_status_label}）· 薄弱分 ${percent(point.weakness_score)}`,
      evidence.state_note || '薄弱分来自正确率、重复错误、复习反馈、用时与学习间隔',
    ],
  });
  return sections;
};

export const ProfileEvidenceDrawer: React.FC<{
  open: boolean;
  point?: ProfileWeakPoint | null;
  onClose: () => void;
  onAction: (path: string) => void;
}> = ({ open, point, onClose, onAction }) => <Drawer
  width={460}
  open={open}
  onClose={onClose}
  title={point ? `为什么 ${point.name} 是 ${percent(point.mastery)}%？` : '画像依据'}
  destroyOnHidden
>
  {point ? <div className="profile-evidence">
    <p className="profile-evidence-lead">画像只使用你的真实学习记录，下面是全部依据。</p>
    {evidenceSections(point).map(section => <section key={section.title}>
      <h4>{section.title}</h4>
      {section.lines.map(line => <p key={line}>{line}</p>)}
    </section>)}
    <section>
      <h4>薄弱分构成</h4>
      <div className="profile-evidence-components">{COMPONENT_LABELS.map(component => {
        const value = Number(point.evidence.components[component.key] ?? 0);
        return <div key={component.key}>
          <div><span>{component.label}<small>权重 {component.weight}</small></span><strong>{Math.round(value)}</strong></div>
          <Progress percent={Math.round(value)} showInfo={false} strokeColor="#c98b37" trailColor="#e7edef" />
        </div>;
      })}</div>
    </section>
    <section>
      <h4>建议</h4>
      <div className="profile-evidence-actions">{point.actions.filter(action => action.path).map(action => <Button
        key={action.type}
        size="small"
        onClick={() => onAction(action.path as string)}
      >{action.label}</Button>)}</div>
    </section>
    <Tag bordered={false} className="profile-evidence-note">学习画像用于调整教学与练习安排，不作为资料事实引用。</Tag>
  </div> : <Empty description="选择一条薄弱知识点查看依据" />}
</Drawer>;

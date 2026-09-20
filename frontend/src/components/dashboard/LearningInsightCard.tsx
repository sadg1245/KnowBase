import React from 'react';
import { Button, Spin, Tag } from 'antd';
import { BulbOutlined } from '@ant-design/icons';

import type { ProfileInsight } from '../../services/api';
import { insightEvidenceLines } from '../../features/dashboard/profileViewModel';

export const LearningInsightCard: React.FC<{
  insight: ProfileInsight;
  onShowEvidence: (lines: string[]) => void;
  onStart: () => void;
  onGenerate?: () => void;
  generating?: boolean;
  generateError?: string | null;
}> = ({ insight, onShowEvidence, onStart, onGenerate, generating = false, generateError }) => {
  if (!insight.text) return null;
  const lines = insightEvidenceLines(insight);
  return <section className="dashboard-section profile-insight" aria-labelledby="profile-insight-title">
    <header className="dashboard-section-heading">
      <div>
        <span className="dashboard-kicker">AI insight</span>
        <h2 id="profile-insight-title"><BulbOutlined /> AI 学习洞察</h2>
      </div>
      <Tag bordered={false}>{insight.generated_by === 'ai' ? 'AI 生成' : '依据规则'}</Tag>
    </header>
    <p className="profile-insight-text">{insight.text}</p>
    {generateError ? <p className="profile-insight-error">{generateError}</p> : null}
    <div className="profile-insight-actions">
      {lines.length ? <Button onClick={() => onShowEvidence(lines)}>查看依据</Button> : null}
      <Button type="primary" onClick={onStart}>开始学习</Button>
      {onGenerate && insight.generated_by !== 'ai'
        ? <Button type="text" disabled={generating} onClick={onGenerate}>{generating ? <Spin size="small" /> : '让 AI 总结'}</Button>
        : null}
    </div>
  </section>;
};

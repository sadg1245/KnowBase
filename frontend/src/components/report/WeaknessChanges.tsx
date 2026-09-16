import React from 'react';
import type { LearningReport } from '../../services/api';

export const WeaknessChanges: React.FC<{ changes: LearningReport['weakness_changes']; onOpen: () => void }> = ({ changes, onOpen }) => <button className="report-weakness" onClick={onOpen}>
  <span className="dashboard-kicker">Weakness shift</span>
  <h2>薄弱知识变化</h2>
  <div><span className="is-good"><strong>{changes.improved}</strong> 已改善</span><span className="is-warm"><strong>{changes.worsened}</strong> 需关注</span><span><strong>{changes.unchanged}</strong> 暂无变化</span></div>
  <small>查看组成记录 →</small>
</button>;

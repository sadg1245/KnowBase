import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Drawer, Empty, Skeleton, Tag, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';

import {
  evidenceDiagnosticLines, hitRows, runSummary, type EvidenceDiagnostics,
} from '../../features/learning/retrievalDiagnostics';
import { getRetrievalRun } from '../../services/api';
import type { RetrievalRunDetail } from '../../services/api';

const { Text } = Typography;

/** 纯展示面板：由 Drawer 提供数据，便于服务端渲染测试。 */
export const RetrievalDiagnosticsPanel: React.FC<{
  detail?: RetrievalRunDetail | null;
  evidence?: EvidenceDiagnostics | null;
  loading?: boolean;
  error?: string | null;
  onReload?: () => void;
}> = ({ detail, evidence, loading = false, error, onReload }) => {
  const lines = evidenceDiagnosticLines(evidence);
  const rows = hitRows(detail);
  const summary = runSummary(detail);
  return <div className="retrieval-diagnostics">
    {lines.length ? <ul className="retrieval-diagnostics-lines">{lines.map(line => <li key={`${line.label}-${line.value}`}>
      <span>{line.label}</span>
      <Tag bordered={false} className={`is-${line.tone}`}>{line.value}</Tag>
    </li>)}</ul> : null}
    {error ? <Alert type="warning" showIcon message="检索详情暂时取不到" description={error} /> : null}
    {loading ? <Skeleton active paragraph={{ rows: 4 }} /> : null}
    {summary ? <p className="retrieval-diagnostics-summary">{summary}</p> : null}
    {!loading && detail && rows.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这次检索没有保留候选" /> : null}
    {rows.length ? <ul className="retrieval-diagnostics-hits">{rows.map(row => <li key={row.chunkId}>
      <div><Text strong>{row.chunkId}</Text><Tag bordered={false}>{row.kinds}</Tag></div>
      <small>{row.source}</small>
      <small>{row.rank} · {row.scores} · 画像 {row.bonus}</small>
    </li>)}</ul> : null}
    {onReload ? <Button size="small" icon={<ReloadOutlined />} onClick={onReload}>刷新</Button> : null}
  </div>;
};

export const RetrievalDiagnostics: React.FC<{
  open: boolean;
  runId?: string | null;
  evidence?: EvidenceDiagnostics | null;
  onClose: () => void;
}> = ({ open, runId, evidence, onClose }) => {
  const [detail, setDetail] = useState<RetrievalRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError(null);
    try {
      setDetail(await getRetrievalRun(runId));
    } catch {
      setError('请稍后重试，或确认这次回答已经完成检索记录。');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    if (open && runId) void load();
    return () => { setDetail(null); };
  }, [load, open, runId]);

  return <Drawer title="检索诊断" open={open} onClose={onClose} width={560}>
    <RetrievalDiagnosticsPanel
      detail={detail}
      evidence={evidence}
      loading={loading}
      error={error}
      onReload={() => void load()}
    />
  </Drawer>;
};

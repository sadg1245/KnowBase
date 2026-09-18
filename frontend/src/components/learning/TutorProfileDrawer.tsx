import React from 'react';
import { Button, Drawer, Empty, List, Progress, Space, Tag, Typography } from 'antd';

import type { LearningMemory, MemoryKind, TutorProfile } from '../../services/api';
import { filterMemories, memoryKindLabel, memorySourceLabel, profileSummary } from '../../features/learning/tutorProfile';

const { Text, Title } = Typography;

interface PanelProps {
  profile: TutorProfile | null;
  memories: LearningMemory[];
  kindFilter?: MemoryKind;
  loading: boolean;
  onFilter: (kind?: MemoryKind) => void;
  onToggle: (memory: LearningMemory) => void;
  onDelete: (memory: LearningMemory) => void;
}

export const TutorProfilePanel: React.FC<PanelProps> = ({
  profile, memories, kindFilter, loading, onFilter, onToggle, onDelete,
}) => {
  const visible = filterMemories(memories, kindFilter);
  return <div className="tutor-profile-panel">
    <Text type="secondary">这些是导师用来调整讲法的信息，不会当作你的资料证据。</Text>
    {profile ? <>
      <Title level={4}>学习画像</Title>
      <Text>{profileSummary(profile)}</Text>
      <div className="tutor-profile-weakness">
        {profile.weak_points.map(point => <div key={point.knowledge_point_id}>
          <Progress percent={Math.round(point.mastery * 100)} size="small" />
          <span>{point.title}</span>
        </div>)}
      </div>
    </> : null}
    <Space wrap className="tutor-profile-filters">
      {([undefined, 'mistake_pattern', 'session_summary', 'manual'] as (MemoryKind | undefined)[]).map(kind =>
        <Button
          key={kind ?? 'all'}
          size="small"
          type={kindFilter === kind ? 'primary' : 'default'}
          onClick={() => onFilter(kind)}
        >
          {kind ? memoryKindLabel(kind) : '全部'}
        </Button>)}
    </Space>
    {visible.length ? <List
      loading={loading}
      dataSource={visible}
      renderItem={item => <List.Item actions={[
        <Button key="toggle" type="link" size="small" onClick={() => onToggle(item)}>
          {item.is_active ? '停用' : '启用'}
        </Button>,
        <Button key="delete" type="link" size="small" danger onClick={() => onDelete(item)}>删除</Button>,
      ]}>
        <List.Item.Meta
          title={<Space><Tag>{memoryKindLabel(item.kind)}</Tag><span>{item.title}</span></Space>}
          description={<>
            <Text type="secondary">{memorySourceLabel(item)} · 使用 {item.use_count} 次</Text>
            <div>{item.content}</div>
          </>}
        />
      </List.Item>} /> : <Empty description="还没有学习记忆" />}
  </div>;
};

export const TutorProfileDrawer: React.FC<PanelProps & { open: boolean; onClose: () => void }> = ({
  open, onClose, ...panel
}) => <Drawer
  title="导师眼中的我"
  placement="right"
  width={420}
  open={open}
  onClose={onClose}
  className="tutor-profile-drawer"
>
  <TutorProfilePanel {...panel} />
</Drawer>;

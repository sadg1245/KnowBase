import React from 'react';
import { Button, Drawer, Space, Tag, Typography } from 'antd';
import { BookOutlined } from '@ant-design/icons';

import type { SourceItem } from '../../services/api';


const { Paragraph, Text } = Typography;

export const EvidenceDrawer: React.FC<{ source: SourceItem | null; onClose: () => void; onOpenSource?: (source: SourceItem) => void }> = ({ source, onClose, onOpenSource }) => <Drawer
  title="回答依据"
  open={Boolean(source)}
  onClose={onClose}
  width={500}
  className="learning-evidence-drawer"
>
  {source ? <>
    <Space wrap><Tag><BookOutlined /> {source.filename}</Tag>{source.page_number > 0 ? <Tag>第 {source.page_number} 页</Tag> : null}{source.heading ? <Tag>{source.heading}</Tag> : null}</Space>
    <Paragraph className="learning-source-content">{source.content}</Paragraph>
    <Button type="primary" style={{ marginBottom: 14 }} onClick={() => onOpenSource?.(source)}>查看原文</Button>
    <Text type="secondary">综合相关度 {Math.round(source.score * 100)}%</Text>
  </> : null}
</Drawer>;

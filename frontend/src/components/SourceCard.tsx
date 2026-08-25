import React from 'react';
import { Card, Typography, Tag, Space } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import { SourceItem } from '../services/api';

const { Text, Paragraph } = Typography;

interface SourceCardProps {
  source: SourceItem;
  index: number;
}

const SourceCard: React.FC<SourceCardProps> = ({ source, index }) => {
  const scorePercent = Math.round(source.score * 100);
  const scoreColor =
    scorePercent >= 80 ? '#52c41a' : scorePercent >= 60 ? '#faad14' : '#ff4d4f';

  return (
    <Card size="small" style={{ borderLeft: `3px solid ${scoreColor}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Space>
          <Tag color="blue">#{index}</Tag>
          <Space size={4}>
            <FileTextOutlined />
            <Text strong>{source.filename}</Text>
          </Space>
          {source.page_number > 0 && (
            <Tag>第 {source.page_number} 页</Tag>
          )}
        </Space>
        <Tag color={scoreColor} style={{ marginRight: 0 }}>
          相关度 {scorePercent}%
        </Tag>
      </div>
      <Paragraph
        style={{
          marginTop: 8,
          marginBottom: 0,
          color: '#666',
          fontSize: 13,
          lineHeight: 1.6,
        }}
        ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
      >
        {source.content}
      </Paragraph>
    </Card>
  );
};

export default SourceCard;

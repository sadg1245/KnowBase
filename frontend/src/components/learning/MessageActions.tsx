import React from 'react';
import { Button, Space, Tooltip } from 'antd';
import { CheckOutlined, CopyOutlined, DislikeOutlined, FileAddOutlined, LikeOutlined, ReadOutlined, WarningOutlined } from '@ant-design/icons';


interface Props {
  onCard: () => void;
  onNote: () => void;
  onMistake: () => void;
  onCopy: () => void;
  onFeedback: (helpful: boolean) => void;
}


export const MessageActions: React.FC<Props> = ({ onCard, onNote, onMistake, onCopy, onFeedback }) => <Space wrap size={2} className="learning-message-actions">
  <Button type="text" size="small" aria-label="保存为卡片" icon={<ReadOutlined />} onClick={onCard}>卡片</Button>
  <Button type="text" size="small" aria-label="保存为笔记" icon={<FileAddOutlined />} onClick={onNote}>笔记</Button>
  <Button type="text" size="small" aria-label="加入错题本" icon={<WarningOutlined />} onClick={onMistake}>错题</Button>
  <Button type="text" size="small" aria-label="复制回答" icon={<CopyOutlined />} onClick={onCopy}>复制</Button>
  <Tooltip title="这条回答有帮助"><Button type="text" size="small" aria-label="回答有帮助" icon={<LikeOutlined />} onClick={() => onFeedback(true)} /></Tooltip>
  <Tooltip title="这条回答需要改进"><Button type="text" size="small" aria-label="回答需要改进" icon={<DislikeOutlined />} onClick={() => onFeedback(false)} /></Tooltip>
</Space>;

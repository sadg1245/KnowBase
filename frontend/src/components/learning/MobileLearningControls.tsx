import React from 'react';
import { Button, Drawer, Space, Tag } from 'antd';
import { MenuOutlined, SettingOutlined } from '@ant-design/icons';

import type { LearningMode } from '../../services/api';
import { learningModes } from '../../features/learning/types';


interface Props {
  sessionOpen: boolean;
  settingsOpen: boolean;
  workspaceName?: string;
  fileCount: number;
  mode: LearningMode;
  onSessions: () => void;
  onSettings: () => void;
}


export const MobileLearningControls: React.FC<Props> = ({ workspaceName, fileCount, mode, onSessions, onSettings }) => <div className="learning-mobile-toolbar">
  <Button icon={<MenuOutlined />} onClick={onSessions}>会话</Button>
  <div className="learning-mobile-scope" aria-label="当前学习范围">
    <Tag>{workspaceName || '未选知识库'}</Tag>
    <Tag>{fileCount ? `${fileCount} 个文件` : '全部文件'}</Tag>
    <Tag>{learningModes.find((item) => item.value === mode)?.label || mode}</Tag>
  </div>
  <Button icon={<SettingOutlined />} onClick={onSettings}>设置</Button>
</div>;

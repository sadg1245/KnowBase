import React, { useState } from 'react';
import { App, Button, Checkbox, Empty, Input, List, Select, Skeleton, Tooltip } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined, StarFilled, StarOutlined } from '@ant-design/icons';

import type { ChatSession, Workspace } from '../../services/api';


interface Props {
  sessions: ChatSession[];
  activeId?: string;
  workspaces: Workspace[];
  loading: boolean;
  search: string;
  workspaceFilter?: string;
  favoritesOnly: boolean;
  onSearch: (value: string) => void;
  onWorkspaceFilter: (value?: string) => void;
  onFavoritesOnly: (value: boolean) => void;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onFavorite: (session: ChatSession) => void;
  onDelete: (id: string) => Promise<void>;
}

type SessionDeletionConfirmation = {
  title: string;
  content: string;
  okText: string;
  cancelText: string;
  centered: boolean;
  okButtonProps: { danger: boolean };
  onOk: () => Promise<void>;
};

type SessionDeletionActions = {
  confirm: (confirmation: SessionDeletionConfirmation) => void;
  remove: (sessionId: string) => Promise<void>;
  onSuccess: (sessionTitle: string) => void;
  onError: (error: unknown) => void;
};

export const requestSessionDeletion = (
  session: Pick<ChatSession, 'id' | 'title'>,
  actions: SessionDeletionActions,
) => {
  actions.confirm({
    title: `删除会话“${session.title}”？`,
    content: '聊天记录将被删除；已保存的卡片和笔记会保留。',
    okText: '确定删除',
    cancelText: '取消',
    centered: true,
    okButtonProps: { danger: true },
    onOk: async () => {
      try {
        await actions.remove(session.id);
        actions.onSuccess(session.title);
      } catch (error) {
        actions.onError(error);
        throw error;
      }
    },
  });
};


export const SessionSidebar: React.FC<Props> = ({
  sessions, activeId, workspaces, loading, search, workspaceFilter, favoritesOnly,
  onSearch, onWorkspaceFilter, onFavoritesOnly, onNew, onOpen, onRename, onFavorite, onDelete,
}) => {
  const { message, modal } = App.useApp();
  const [editingId, setEditingId] = useState<string>();
  const [editingTitle, setEditingTitle] = useState('');

  const finishRename = (id: string) => {
    const title = editingTitle.trim();
    if (title) onRename(id, title);
    setEditingId(undefined);
  };

  return <aside className="learning-session-sidebar" aria-label="学习会话">
    <Button type="primary" icon={<PlusOutlined />} block size="large" onClick={onNew}>新建会话</Button>
    <Input
      value={search}
      onChange={(event) => onSearch(event.target.value)}
      prefix={<SearchOutlined />}
      allowClear
      placeholder="搜索会话"
      aria-label="搜索会话"
    />
    <Select
      allowClear
      value={workspaceFilter}
      onChange={onWorkspaceFilter}
      placeholder="全部知识库"
      options={workspaces.map((item) => ({ label: item.name, value: item.id }))}
    />
    <Checkbox checked={favoritesOnly} onChange={(event) => onFavoritesOnly(event.target.checked)}>只看收藏</Checkbox>
    <div className="learning-session-list">
      {loading ? <Skeleton active paragraph={{ rows: 6 }} /> : sessions.length ? <List
        dataSource={sessions}
        split={false}
        renderItem={(session) => <List.Item className={`learning-session-row ${activeId === session.id ? 'is-active' : ''}`}>
          <div className="learning-session-main">
            {editingId === session.id ? <Input
              autoFocus
              value={editingTitle}
              onChange={(event) => setEditingTitle(event.target.value)}
              onBlur={() => finishRename(session.id)}
              onPressEnter={() => finishRename(session.id)}
              maxLength={255}
            /> : <button className="learning-session-title" onClick={() => onOpen(session.id)}>
              <strong>{session.title}</strong>
              <span>{new Date(session.last_message_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
            </button>}
            <div className="learning-session-actions">
              <Tooltip title={session.is_favorite ? '取消收藏' : '收藏'}><Button type="text" size="small" aria-label={session.is_favorite ? '取消收藏' : '收藏'} icon={session.is_favorite ? <StarFilled /> : <StarOutlined />} onClick={() => onFavorite(session)} /></Tooltip>
              <Tooltip title="重命名"><Button type="text" size="small" aria-label="重命名" icon={<EditOutlined />} onClick={() => { setEditingId(session.id); setEditingTitle(session.title); }} /></Tooltip>
              <Tooltip title="删除"><Button type="text" danger size="small" aria-label={`删除会话 ${session.title}`} icon={<DeleteOutlined />} onClick={() => requestSessionDeletion(session, {
                confirm: confirmation => { modal.confirm(confirmation); },
                remove: onDelete,
                onSuccess: sessionTitle => message.success(`会话“${sessionTitle}”已删除`),
                onError: () => message.error('删除会话失败，请稍后重试'),
              })} /></Tooltip>
            </div>
          </div>
        </List.Item>}
      /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有学习会话" />}
    </div>
  </aside>;
};

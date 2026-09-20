import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  ChatSession,
  createChatSession,
  deleteChatSession,
  getChatSession,
  getChatSessions,
  LearningMode,
  RetrievalScopePayload,
  updateChatSession,
  updateChatSessionScope,
} from '../services/api';


export const useChatSessions = () => {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [workspaceFilter, setWorkspaceFilter] = useState<string | undefined>();
  const [favoritesOnly, setFavoritesOnly] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setSessions(await getChatSessions(workspaceFilter, favoritesOnly ? true : undefined));
    } finally {
      setLoading(false);
    }
  }, [favoritesOnly, workspaceFilter]);

  useEffect(() => { void refresh(); }, [refresh]);

  const visibleSessions = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase();
    return keyword ? sessions.filter((item) => item.title.toLocaleLowerCase().includes(keyword)) : sessions;
  }, [search, sessions]);

  const openSession = useCallback(async (id: string) => {
    const detail = await getChatSession(id);
    setActiveSession(detail);
    localStorage.setItem('knowbase_learning_session', id);
    return detail;
  }, []);

  const newSession = useCallback(async (values: {
    workspace_id?: string;
    document_ids?: string[];
    mode?: LearningMode;
    strict_sources?: boolean;
    scope_mode?: RetrievalScopePayload['mode'];
    scope_config?: Omit<RetrievalScopePayload, 'mode'>;
  }) => {
    const created = await createChatSession(values);
    setSessions((current) => [created, ...current]);
    setActiveSession({ ...created, messages: [] });
    localStorage.setItem('knowbase_learning_session', created.id);
    return created;
  }, []);

  const patchSession = useCallback(async (id: string, values: Parameters<typeof updateChatSession>[1]) => {
    const updated = await updateChatSession(id, values);
    setSessions((current) => current.map((item) => item.id === id ? updated : item));
    setActiveSession((current) => current?.id === id ? { ...current, ...updated } : current);
    return updated;
  }, []);

  const patchScope = useCallback(async (id: string, scope: RetrievalScopePayload) => {
    const updated = await updateChatSessionScope(id, scope);
    setSessions((current) => current.map((item) => item.id === id ? updated : item));
    setActiveSession((current) => current?.id === id ? { ...current, ...updated } : current);
    return updated;
  }, []);

  const removeSession = useCallback(async (id: string) => {
    await deleteChatSession(id);
    setSessions((current) => current.filter((item) => item.id !== id));
    setActiveSession((current) => current?.id === id ? null : current);
    if (localStorage.getItem('knowbase_learning_session') === id) {
      localStorage.removeItem('knowbase_learning_session');
    }
  }, []);

  const mergeStreamSession = useCallback((value: { id: string; title: string }) => {
    setSessions((current) => {
      const found = current.find((item) => item.id === value.id);
      if (!found) return current;
      return [{ ...found, title: value.title }, ...current.filter((item) => item.id !== value.id)];
    });
    setActiveSession((current) => current?.id === value.id ? { ...current, title: value.title } : current);
  }, []);

  return {
    sessions: visibleSessions,
    activeSession,
    setActiveSession,
    loading,
    search,
    setSearch,
    workspaceFilter,
    setWorkspaceFilter,
    favoritesOnly,
    setFavoritesOnly,
    refresh,
    openSession,
    newSession,
    patchSession,
    patchScope,
    removeSession,
    mergeStreamSession,
  };
};

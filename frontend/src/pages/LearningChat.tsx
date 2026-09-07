import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { App, Button, Drawer, Space, Tag, Typography } from 'antd';
import { FileTextOutlined, MenuOutlined } from '@ant-design/icons';

import {
  ChatEvent,
  ChatMessage,
  createMessageCard,
  createMessageMistake,
  createMessageNote,
  createSessionSummaryNote,
  Document,
  getDocuments,
  getKnowledgeBaseDetail,
  getLearningProfile,
  getWorkspaces,
  LearningMode,
  normalizeChatSources,
  SourceItem,
  updateMessageFeedback,
  Workspace,
} from '../services/api';
import { useChatSessions } from '../hooks/useChatSessions';
import { useStreamingChat } from '../hooks/useStreamingChat';
import { applyChatEvent, AssistantDraft, createAssistantDraft, messagesAfterSessionDelete } from '../features/learning/learningConversationState';
import type { DisplayMessage } from '../features/learning/types';
import { scrollMessagesIntoView } from './learningChatScroll';
import { resolveDocumentScopeOnWorkspaceLoad, resolveWorkspaceSelection } from './documentScope';
import { ChatComposer } from '../components/learning/ChatComposer';
import { ChatTranscript } from '../components/learning/ChatTranscript';
import { EvidenceDrawer } from '../components/learning/EvidenceDrawer';
import { LearningModePanel } from '../components/learning/LearningModePanel';
import { MobileLearningControls } from '../components/learning/MobileLearningControls';
import { SessionSidebar } from '../components/learning/SessionSidebar';
import { sourceDetailTarget } from '../features/learning/sourceNavigation';
import { applyLearningRecommendationPreset, requestedLearningPreset, type RequestedLearningPreset } from './learningChatPresets';


const { Text, Title } = Typography;

const historyMessage = (item: ChatMessage): DisplayMessage => ({
  id: item.id,
  role: item.role,
  content: item.content,
  sources: normalizeChatSources(item.sources || []),
  evidenceStatus: item.evidence_status,
  suggestions: item.follow_up_questions || [],
  status: item.generation_status === 'partial' ? 'partial' : item.generation_status === 'failed' ? 'failed' : 'complete',
});


const LearningChat: React.FC = () => {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const presetQuery = params.toString();
  const initialPreset = requestedLearningPreset(params);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);
  const [workspaceId, setWorkspaceId] = useState<string | undefined>(initialPreset.workspaceId);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [mode, setMode] = useState<LearningMode>('simple');
  const [strict, setStrict] = useState(true);
  const [question, setQuestion] = useState('');
  const [presetPointTitle, setPresetPointTitle] = useState<string>();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [source, setSource] = useState<SourceItem | null>(null);
  const [currentEvidence, setCurrentEvidence] = useState<{ status?: string; degradationReason?: string }>({});
  const [sessionsDrawer, setSessionsDrawer] = useState(false);
  const [settingsDrawer, setSettingsDrawer] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const draftIdRef = useRef<string>();
  const draftRef = useRef<AssistantDraft>(createAssistantDraft());
  const restoredRef = useRef(false);
  const pendingDocumentIdsRef = useRef<string[] | undefined>();
  const pendingPresetRef = useRef<{ query: string; preset: RequestedLearningPreset }>({ query: presetQuery, preset: initialPreset });

  const sessionState = useChatSessions();
  const openSource = useCallback((item: SourceItem) => {
    const target = workspaceId ? sourceDetailTarget(workspaceId, item) : null;
    if (target) navigate(target);
    else setSource(item);
  }, [navigate, workspaceId]);

  const handleChatEvent = useCallback((event: ChatEvent) => {
    draftRef.current = applyChatEvent(draftRef.current, event as Record<string, unknown>);
    const draft = draftRef.current;
    if ('session' in event) sessionState.mergeStreamSession(event.session);
    if ('evidence' in event) setCurrentEvidence({ status: event.evidence.status, degradationReason: event.evidence.degradation_reason });
    if ('error' in event) message.error(event.error);
    const draftId = draftIdRef.current;
    if (!draftId) return;
    setMessages((current) => current.map((item) => item.id === draftId ? {
      ...item,
      id: draft.messageId || item.id,
      content: draft.content,
      sources: Array.isArray(draft.sources) ? normalizeChatSources(draft.sources as Parameters<typeof normalizeChatSources>[0]) : [],
      evidenceStatus: draft.evidence?.status,
      suggestions: draft.suggestions,
      status: draft.status,
    } : item));
    if ('done' in event) void sessionState.refresh();
  }, [message, sessionState.mergeStreamSession, sessionState.refresh]);

  const streaming = useStreamingChat(handleChatEvent);

  useEffect(() => {
    const preset = requestedLearningPreset(new URLSearchParams(presetQuery));
    pendingPresetRef.current = { query: presetQuery, preset };
    setQuestion('');
    setPresetPointTitle(undefined);
    if (preset.workspaceId && workspaces.some(item => item.id === preset.workspaceId)) {
      streaming.cancel();
      pendingDocumentIdsRef.current = undefined;
      setWorkspaceId(preset.workspaceId);
      setDocumentIds([]);
    }
  }, [presetQuery, streaming.cancel, workspaces]);

  useEffect(() => {
    let active = true;
    setWorkspacesLoading(true);
    Promise.all([getWorkspaces(), getLearningProfile()])
      .then(([workspaceItems, profile]) => {
        if (!active) return;
        setWorkspaces(workspaceItems);
        setWorkspaceId((current) => resolveWorkspaceSelection(workspaceItems, initialPreset.workspaceId || current));
        const preferred = profile.preferred_mode as LearningMode;
        if (['direct', 'simple', 'deep', 'socratic', 'feynman', 'quiz'].includes(preferred)) setMode(preferred);
      })
      .catch(() => message.error('知识库加载失败，请稍后重试'))
      .finally(() => { if (active) setWorkspacesLoading(false); });
    return () => { active = false; };
  }, [message]);

  useEffect(() => {
    setDocumentIds(resolveDocumentScopeOnWorkspaceLoad(pendingDocumentIdsRef.current));
    pendingDocumentIdsRef.current = undefined;
    setDocuments([]);
    if (!workspaceId) return;
    let active = true;
    setDocumentsLoading(true);
    const pendingAtStart = pendingPresetRef.current;
    const needsPointValidation = pendingAtStart.preset.workspaceId === workspaceId && Boolean(pendingAtStart.preset.knowledgePointId);
    Promise.all([getDocuments(workspaceId), needsPointValidation ? getKnowledgeBaseDetail(workspaceId) : Promise.resolve(null)])
      .then(([items, detail]) => {
        if (!active) return;
        setDocuments(items);
        const pending = pendingPresetRef.current;
        if (pending.preset.workspaceId !== workspaceId) return;
        const readyIds = items.filter(item => item.status === 'ready').map(item => item.id);
        const applied = applyLearningRecommendationPreset(pending.preset, workspaces, detail?.knowledge_points ?? [], readyIds);
        if (pending.query !== presetQuery) return;
        pendingPresetRef.current = { query: '', preset: {} };
        setPresetPointTitle(applied.knowledgePointTitle);
        setDocumentIds(applied.documentIds);
        setQuestion(applied.draft);
        if (applied.mode) setMode(applied.mode);
      })
      .catch(() => { if (active) message.error('资料列表加载失败'); })
      .finally(() => { if (active) setDocumentsLoading(false); });
    return () => { active = false; };
  }, [message, presetQuery, workspaceId, workspaces]);

  useEffect(() => { scrollMessagesIntoView(endRef.current); }, [messages]);

  const openSession = useCallback(async (id: string) => {
    streaming.cancel();
    try {
      const detail = await sessionState.openSession(id);
      pendingDocumentIdsRef.current = detail.document_ids || [];
      setWorkspaceId(detail.workspace_id || undefined);
      setDocumentIds(detail.document_ids || []);
      setMode(detail.mode);
      setStrict(detail.strict_sources);
      setMessages((detail.messages || []).map(historyMessage));
      const latestAssistant = [...(detail.messages || [])].reverse().find((item) => item.role === 'assistant');
      setCurrentEvidence({ status: latestAssistant?.evidence_status });
      setSessionsDrawer(false);
    } catch {
      message.error('会话加载失败');
    }
  }, [message, sessionState.openSession, streaming.cancel]);

  useEffect(() => {
    if (restoredRef.current || sessionState.loading) return;
    restoredRef.current = true;
    const explicitSession = params.get('session');
    const preset = requestedLearningPreset(params);
    const hasRecommendationPreset = Boolean(preset.workspaceId || preset.knowledgePointId || preset.prompt || preset.mode);
    const requested = explicitSession || (hasRecommendationPreset ? null : localStorage.getItem('knowbase_learning_session'));
    if (requested && sessionState.sessions.some((item) => item.id === requested)) void openSession(requested);
  }, [openSession, params, sessionState.loading, sessionState.sessions]);

  const createSession = useCallback(async () => {
    if (!workspaceId) {
      message.warning('请先在学习设置中选择知识库');
      setSettingsDrawer(true);
      return null;
    }
    streaming.cancel();
    const created = await sessionState.newSession({
      workspace_id: workspaceId,
      document_ids: documentIds,
      mode,
      strict_sources: strict,
    });
    setMessages([]);
    setCurrentEvidence({});
    setSessionsDrawer(false);
    return created;
  }, [documentIds, message, mode, sessionState.newSession, streaming.cancel, strict, workspaceId]);

  const sendQuestion = useCallback(async (value = question) => {
    const text = value.trim();
    if (!text || !workspaceId || streaming.loading) return;
    setQuestion('');
    let activeSession = sessionState.activeSession;
    if (!activeSession) activeSession = await createSession();
    if (!activeSession) return;
    const userId = crypto.randomUUID();
    const draftId = crypto.randomUUID();
    draftIdRef.current = draftId;
    draftRef.current = createAssistantDraft();
    setMessages((current) => [...current,
      { id: userId, role: 'user', content: text, sources: [], suggestions: [], status: 'complete' },
      { id: draftId, role: 'assistant', content: '', sources: [], suggestions: [], status: 'streaming' },
    ]);
    try {
      await streaming.send({
        question: text,
        workspaceId,
        documentIds,
        mode,
        strictSources: strict,
        sessionId: activeSession.id,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      const detail = error instanceof Error ? error.message : '学习对话中断';
      message.error(detail);
      setMessages((current) => current.map((item) => item.id === draftId ? { ...item, status: item.content ? 'partial' : 'failed' } : item));
    }
  }, [createSession, documentIds, message, mode, question, sessionState.activeSession, streaming, strict, workspaceId]);

  const patchScope = useCallback((changes: Parameters<typeof sessionState.patchSession>[1]) => {
    if (sessionState.activeSession) void sessionState.patchSession(sessionState.activeSession.id, changes);
  }, [sessionState.activeSession, sessionState.patchSession]);

  const handleWorkspace = (value?: string) => {
    streaming.cancel();
    pendingDocumentIdsRef.current = undefined;
    pendingPresetRef.current = { query: '', preset: {} };
    setPresetPointTitle(undefined);
    setWorkspaceId(value);
    setDocumentIds([]);
    patchScope({ workspace_id: value, document_ids: [] });
  };
  const handleDocuments = (values: string[]) => { setDocumentIds(values); patchScope({ document_ids: values }); };
  const handleMode = (value: LearningMode) => { setMode(value); patchScope({ mode: value }); };
  const handleStrict = (value: boolean) => { setStrict(value); patchScope({ strict_sources: value }); };

  const deleteSession = useCallback(async (id: string) => {
    const activeId = sessionState.activeSession?.id;
    await sessionState.removeSession(id);
    setMessages((current) => messagesAfterSessionDelete(activeId, id, current));
    if (activeId === id) setCurrentEvidence({});
  }, [sessionState.activeSession?.id, sessionState.removeSession]);

  const action = async (label: string, operation: () => Promise<unknown>) => {
    try { await operation(); message.success(`${label}已保存`); } catch { message.error(`${label}保存失败`); }
  };

  const workspaceName = useMemo(() => workspaces.find((item) => item.id === workspaceId)?.name, [workspaceId, workspaces]);
  const sessionSidebar = <SessionSidebar
    sessions={sessionState.sessions}
    activeId={sessionState.activeSession?.id}
    workspaces={workspaces}
    loading={sessionState.loading || workspacesLoading}
    search={sessionState.search}
    workspaceFilter={sessionState.workspaceFilter}
    favoritesOnly={sessionState.favoritesOnly}
    onSearch={sessionState.setSearch}
    onWorkspaceFilter={sessionState.setWorkspaceFilter}
    onFavoritesOnly={sessionState.setFavoritesOnly}
    onNew={() => void createSession()}
    onOpen={(id) => void openSession(id)}
    onRename={(id, title) => void sessionState.patchSession(id, { title })}
    onFavorite={(item) => void sessionState.patchSession(item.id, { is_favorite: !item.is_favorite })}
    onDelete={deleteSession}
  />;
  const modePanel = <LearningModePanel
    workspaces={workspaces}
    workspaceId={workspaceId}
    documents={documents}
    documentIds={documentIds}
    documentsLoading={documentsLoading}
    mode={mode}
    strict={strict}
    evidenceStatus={currentEvidence.status}
    degradationReason={currentEvidence.degradationReason}
    onWorkspace={handleWorkspace}
    onDocuments={handleDocuments}
    onMode={handleMode}
    onStrict={handleStrict}
  />;

  return <div className="learning-page">
    <MobileLearningControls
      sessionOpen={sessionsDrawer}
      settingsOpen={settingsDrawer}
      workspaceName={workspaceName}
      fileCount={documentIds.length}
      mode={mode}
      onSessions={() => setSessionsDrawer(true)}
      onSettings={() => setSettingsDrawer(true)}
    />
    <div className="learning-workspace">
      <div className="learning-desktop-sessions">{sessionSidebar}</div>
      <main className="learning-chat-column">
        <header className="learning-chat-header">
          <div>
            <Title level={2}>{sessionState.activeSession?.title || '新学习会话'}</Title>
            <Text>{workspaceName ? `${workspaceName} · ${documentIds.length ? `${documentIds.length} 个文件` : '全部文件'}` : '选择资料后开始学习'}</Text>
            {presetPointTitle ? <Tag className="learning-preset-context">当前建议：{presetPointTitle}</Tag> : null}
          </div>
          <Space>
            <Button className="learning-tablet-session-button" icon={<MenuOutlined />} onClick={() => setSessionsDrawer(true)}>会话</Button>
            <Button aria-label="保存会话笔记" icon={<FileTextOutlined />} disabled={!sessionState.activeSession || !messages.length} onClick={() => sessionState.activeSession && void action('会话笔记', () => createSessionSummaryNote(sessionState.activeSession!.id))}>保存会话笔记</Button>
          </Space>
        </header>
        <ChatTranscript
          messages={messages}
          endRef={endRef}
          onSource={openSource}
          onSuggestion={(value) => void sendQuestion(value)}
          onCard={(item) => void action('卡片', () => createMessageCard(item.id))}
          onNote={(item) => void action('笔记', () => createMessageNote(item.id))}
          onMistake={(item) => void action('错题', () => createMessageMistake(item.id))}
          onFeedback={(item, helpful) => void action('反馈', () => updateMessageFeedback(item.id, helpful, helpful ? 'accurate' : 'unclear'))}
        />
        <ChatComposer value={question} disabled={!workspaceId} loading={streaming.loading} onChange={setQuestion} onSend={() => void sendQuestion()} onCancel={streaming.cancel} />
      </main>
      <div className="learning-desktop-settings">{modePanel}</div>
    </div>
    <Drawer title="学习会话" placement="left" width={300} open={sessionsDrawer} onClose={() => setSessionsDrawer(false)} className="learning-session-drawer">{sessionSidebar}</Drawer>
    <Drawer title="学习设置" placement="bottom" height="82vh" open={settingsDrawer} onClose={() => setSettingsDrawer(false)} className="learning-settings-drawer">{modePanel}</Drawer>
    <EvidenceDrawer source={source} onClose={() => setSource(null)} onOpenSource={openSource} />
  </div>;
};

export default LearningChat;

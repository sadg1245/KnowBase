import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { App, Button, Drawer, Space, Tag, Typography } from 'antd';
import { AimOutlined, BulbOutlined, FileTextOutlined, MenuOutlined } from '@ant-design/icons';

import {
  ChatEvent,
  ChatMessage,
  createMessageCard,
  createMessageMistake,
  createMessageNote,
  createSessionSummaryNote,
  deleteMemory,
  Document,
  getMemories,
  getDocuments,
  getKnowledgeBaseDetail,
  getLearningProfile,
  getTutorProfile,
  getWorkspaces,
  LearningMemory,
  LearningMode,
  MemoryKind,
  normalizeChatSources,
  SourceItem,
  TutorProfile,
  updateMemory,
  updateMessageFeedback,
  Workspace,
} from '../services/api';
import { useChatSessions } from '../hooks/useChatSessions';
import { useStreamingChat } from '../hooks/useStreamingChat';
import { applyChatEvent, AssistantDraft, createAssistantDraft, messagesAfterSessionDelete } from '../features/learning/learningConversationState';
import type { DisplayMessage } from '../features/learning/types';
import { scrollMessagesIntoView } from './learningChatScroll';
import { resolveDocumentScopeOnWorkspaceLoad, resolveWorkspaceSelection } from './documentScope';
import {
  buildScopePayload,
  scopeChoiceFromPayload,
  scopeConfigPayload,
  scopeRequiresDocuments,
  scopeRequiresWorkspace,
  scopeNoticeText,
  scopeSummaryLabel,
  type ScopeChoice,
  type ScopeNotice,
} from './learningScope';
import { ChatComposer } from '../components/learning/ChatComposer';
import { ChatTranscript } from '../components/learning/ChatTranscript';
import { EvidenceDrawer } from '../components/learning/EvidenceDrawer';
import { LearningModePanel } from '../components/learning/LearningModePanel';
import { MobileLearningControls } from '../components/learning/MobileLearningControls';
import { RetrievalDiagnostics } from '../components/learning/RetrievalDiagnostics';
import { SessionSidebar } from '../components/learning/SessionSidebar';
import { TutorProfileDrawer } from '../components/learning/TutorProfileDrawer';
import { sourceDetailTarget } from '../features/learning/sourceNavigation';
import {
  applyLearningRecommendationPreset,
  executeLearningRecommendationCommands,
  planLearningRecommendationPresetCommit,
  planLearningRecommendationPresetReset,
  requestedLearningPreset,
  type RequestedLearningPreset,
} from './learningChatPresets';
import { consumeQuickQuestion } from '../features/learning/quickQuestion';
import { useActiveStudySession } from '../hooks/useActiveStudySession';


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
  const location = useLocation();
  const [params] = useSearchParams();
  const presetQuery = params.toString();
  const initialPreset = requestedLearningPreset(params);
  const initialQuickQuestion = consumeQuickQuestion(location.state, undefined);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);
  const [workspaceId, setWorkspaceId] = useState<string | undefined>(initialQuickQuestion?.workspaceId || initialPreset.workspaceId);
  const [documents, setDocuments] = useState<Document[]>([]);
  const urlDocumentId = params.get('document_id') || undefined;
  const [documentIds, setDocumentIds] = useState<string[]>(urlDocumentId ? [urlDocumentId] : []);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [mode, setMode] = useState<LearningMode>(initialQuickQuestion?.mode || 'simple');
  const [scopeChoice, setScopeChoice] = useState<ScopeChoice>(urlDocumentId ? 'document' : 'smart');
  const [allowScopeExpansion, setAllowScopeExpansion] = useState(false);
  const [knowledgePointId, setKnowledgePointId] = useState<string | undefined>(initialPreset.knowledgePointId);
  const [question, setQuestion] = useState(initialQuickQuestion?.question || '');
  const [presetPointTitle, setPresetPointTitle] = useState<string>();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [source, setSource] = useState<SourceItem | null>(null);
  const [currentEvidence, setCurrentEvidence] = useState<{
    status?: string;
    degradationReason?: string;
    retrievalRunId?: string | null;
    queryIntent?: string;
    rerankDegraded?: string | null;
    indexStale?: boolean;
    indexStaleReasons?: string[];
    contextNotes?: string[];
  }>({});
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [scopeNotice, setScopeNotice] = useState<ScopeNotice | null>(null);
  const [sessionsDrawer, setSessionsDrawer] = useState(false);
  const [settingsDrawer, setSettingsDrawer] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [tutorProfile, setTutorProfile] = useState<TutorProfile | null>(null);
  const [memories, setMemories] = useState<LearningMemory[]>([]);
  const [memoryFilter, setMemoryFilter] = useState<MemoryKind | undefined>();
  const [memoryLoading, setMemoryLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const draftIdRef = useRef<string>();
  const draftRef = useRef<AssistantDraft>(createAssistantDraft());
  const restoredRef = useRef(false);
  const pendingDocumentIdsRef = useRef<string[] | undefined>();
  const urlDocumentIdsRef = useRef<string[] | undefined>(urlDocumentId ? [urlDocumentId] : undefined);
  const pendingPresetRef = useRef<{ query: string; preset: RequestedLearningPreset }>({ query: presetQuery, preset: initialPreset });
  const workspacesRef = useRef(workspaces);
  const consumedQuickNonceRef = useRef<string>();
  workspacesRef.current = workspaces;

  const sessionState = useChatSessions();
  const currentScope = useMemo(() => buildScopePayload(scopeChoice, {
    workspaceId,
    documentIds,
    knowledgePointId,
    allowWorkspaceExpansion: allowScopeExpansion,
  }), [allowScopeExpansion, documentIds, knowledgePointId, scopeChoice, workspaceId]);
  const scopeRef = useRef(currentScope);
  scopeRef.current = currentScope;
  useActiveStudySession({
    contextType: 'conversation',
    contextId: sessionState.activeSession?.id,
    workspaceId: sessionState.activeSession?.workspace_id || workspaceId,
    enabled: Boolean(sessionState.activeSession),
  });
  const activeSessionRef = useRef(sessionState.activeSession);
  activeSessionRef.current = sessionState.activeSession;
  const detachActiveSession = useCallback(() => {
    const activeId = activeSessionRef.current?.id;
    activeSessionRef.current = null;
    sessionState.setActiveSession(null);
    if (activeId && localStorage.getItem('knowbase_learning_session') === activeId) {
      localStorage.removeItem('knowbase_learning_session');
    }
    setMessages([]);
    setCurrentEvidence({});
    setScopeNotice(null);
  }, [sessionState.setActiveSession]);
  const openSource = useCallback((item: SourceItem) => {
    const target = workspaceId ? sourceDetailTarget(workspaceId, item) : null;
    if (target) navigate(target);
    else setSource(item);
  }, [navigate, workspaceId]);

  const handleChatEvent = useCallback((event: ChatEvent) => {
    draftRef.current = applyChatEvent(draftRef.current, event as Record<string, unknown>);
    const draft = draftRef.current;
    if ('session' in event) sessionState.mergeStreamSession(event.session);
    if ('evidence' in event) setCurrentEvidence({
      status: event.evidence.status,
      degradationReason: event.evidence.degradation_reason,
      retrievalRunId: event.evidence.retrieval_run_id,
      queryIntent: event.evidence.query_intent,
      rerankDegraded: event.evidence.rerank_degraded,
      indexStale: event.evidence.index_stale,
      indexStaleReasons: event.evidence.index_stale_reasons,
      contextNotes: event.evidence.context_notes,
    });
    if ('scope' in event) setScopeNotice({
      mode: event.scope.mode,
      expanded: event.scope.expanded_scope,
      dropped: event.scope.dropped_ids.length,
    });
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
      answerLayers: draft.answerLayers,
      status: draft.status,
    } : item));
    if ('done' in event) void sessionState.refresh();
  }, [message, sessionState.mergeStreamSession, sessionState.refresh]);

  const streaming = useStreamingChat(handleChatEvent);

  useEffect(() => {
    const preset = requestedLearningPreset(new URLSearchParams(presetQuery));
    pendingPresetRef.current = { query: presetQuery, preset };
    executeLearningRecommendationCommands(planLearningRecommendationPresetReset(), {
      cancelStream: streaming.cancel,
      detachSession: detachActiveSession,
      setWorkspace: setWorkspaceId,
      setDocuments: setDocumentIds,
      setMode,
      setDraft: setQuestion,
      setPointTitle: setPresetPointTitle,
    });
    setKnowledgePointId(undefined);
    pendingDocumentIdsRef.current = undefined;
    if (preset.workspaceId && workspacesRef.current.some(item => item.id === preset.workspaceId)) {
      setWorkspaceId(preset.workspaceId);
    }
  }, [detachActiveSession, presetQuery, streaming.cancel]);

  useEffect(() => {
    const quick = consumeQuickQuestion(location.state, consumedQuickNonceRef.current);
    if (!quick) return;
    consumedQuickNonceRef.current = quick.nonce;
    if (quick.workspaceId) setWorkspaceId(quick.workspaceId);
    if (quick.mode) setMode(quick.mode);
    setQuestion(quick.question);
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.pathname, location.search, location.state, navigate]);

  useEffect(() => {
    let active = true;
    setWorkspacesLoading(true);
    Promise.all([getWorkspaces(), getLearningProfile()])
      .then(([workspaceItems, profile]) => {
        if (!active) return;
        setWorkspaces(workspaceItems);
        setWorkspaceId((current) => resolveWorkspaceSelection(workspaceItems, pendingPresetRef.current.preset.workspaceId || current));
        const preferred = profile.preferred_mode as LearningMode;
        if (['direct', 'simple', 'deep', 'socratic', 'feynman', 'quiz'].includes(preferred)) setMode(preferred);
      })
      .catch(() => message.error('知识库加载失败，请稍后重试'))
      .finally(() => { if (active) setWorkspacesLoading(false); });
    return () => { active = false; };
  }, [message]);

  useEffect(() => {
    const urlDocuments = urlDocumentIdsRef.current;
    setDocumentIds(resolveDocumentScopeOnWorkspaceLoad(pendingDocumentIdsRef.current ?? urlDocuments));
    pendingDocumentIdsRef.current = undefined;
    urlDocumentIdsRef.current = undefined;
    setDocuments([]);
    if (!workspaceId || workspacesLoading) return;
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
        setKnowledgePointId(applied.knowledgePointId);
        executeLearningRecommendationCommands(planLearningRecommendationPresetCommit(applied), {
          cancelStream: streaming.cancel,
          detachSession: detachActiveSession,
          setWorkspace: setWorkspaceId,
          setDocuments: setDocumentIds,
          setMode,
          setDraft: setQuestion,
          setPointTitle: setPresetPointTitle,
        });
      })
      .catch(() => { if (active) message.error('资料列表加载失败'); })
      .finally(() => { if (active) setDocumentsLoading(false); });
    return () => { active = false; };
  }, [detachActiveSession, message, presetQuery, streaming.cancel, workspaceId, workspaces, workspacesLoading]);

  useEffect(() => { scrollMessagesIntoView(endRef.current); }, [messages]);

  const loadTutorContext = useCallback(async () => {
    setMemoryLoading(true);
    try {
      const [profile, page] = await Promise.all([
        getTutorProfile(workspaceId),
        getMemories({ workspace_id: workspaceId }),
      ]);
      setTutorProfile(profile);
      setMemories(page.items);
    } catch {
      message.error('学习记录暂时没有加载成功');
    } finally {
      setMemoryLoading(false);
    }
  }, [message, workspaceId]);

  useEffect(() => {
    if (profileOpen) void loadTutorContext();
  }, [loadTutorContext, profileOpen]);

  const openSession = useCallback(async (id: string) => {
    streaming.cancel();
    try {
      const detail = await sessionState.openSession(id);
      pendingDocumentIdsRef.current = detail.document_ids || [];
      setWorkspaceId(detail.workspace_id || undefined);
      setDocumentIds(detail.document_ids || []);
      setScopeChoice(scopeChoiceFromPayload(detail.scope));
      setAllowScopeExpansion(Boolean(detail.scope?.allow_workspace_expansion));
      setMode(detail.mode);
      setMessages((detail.messages || []).map(historyMessage));
      setScopeNotice(null);
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
    if (scopeRequiresWorkspace(scopeChoice) && !workspaceId) {
      message.warning('请先在学习设置中选择知识库');
      setSettingsDrawer(true);
      return null;
    }
    if (scopeRequiresDocuments(scopeChoice) && documentIds.length === 0) {
      message.warning('请先在学习设置中选择资料');
      setSettingsDrawer(true);
      return null;
    }
    streaming.cancel();
    const scope = scopeRef.current;
    const created = await sessionState.newSession({
      workspace_id: workspaceId,
      document_ids: documentIds,
      mode,
      strict_sources: false,
      scope_mode: scope.mode,
      scope_config: scopeConfigPayload(scope),
    });
    setMessages([]);
    setCurrentEvidence({});
    setSessionsDrawer(false);
    return created;
  }, [documentIds, message, mode, scopeChoice, sessionState.newSession, streaming.cancel, workspaceId]);

  const sendQuestion = useCallback(async (value = question) => {
    const text = value.trim();
    if (!text || streaming.loading) return;
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
        sessionId: activeSession.id,
        scope: scopeRef.current,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      const detail = error instanceof Error ? error.message : '学习对话中断';
      message.error(detail);
      setMessages((current) => current.map((item) => item.id === draftId ? { ...item, status: item.content ? 'partial' : 'failed' } : item));
    }
  }, [createSession, documentIds, message, mode, question, sessionState.activeSession, streaming, workspaceId]);

  const pushScope = useCallback((next: ScopeChoice, options?: {
    workspaceId?: string;
    documentIds?: string[];
    allowExpansion?: boolean;
  }) => {
    const payload = buildScopePayload(next, {
      workspaceId: options?.workspaceId ?? workspaceId,
      documentIds: options?.documentIds ?? documentIds,
      knowledgePointId,
      allowWorkspaceExpansion: options?.allowExpansion ?? allowScopeExpansion,
    });
    if (sessionState.activeSession) {
      void sessionState.patchScope(sessionState.activeSession.id, payload);
    }
  }, [allowScopeExpansion, documentIds, knowledgePointId, sessionState.activeSession, sessionState.patchScope, workspaceId]);

  const patchSessionFields = useCallback((changes: Parameters<typeof sessionState.patchSession>[1]) => {
    if (sessionState.activeSession) void sessionState.patchSession(sessionState.activeSession.id, changes);
  }, [sessionState.activeSession, sessionState.patchSession]);

  const handleWorkspace = (value?: string) => {
    streaming.cancel();
    pendingDocumentIdsRef.current = undefined;
    pendingPresetRef.current = { query: '', preset: {} };
    setPresetPointTitle(undefined);
    setKnowledgePointId(undefined);
    setWorkspaceId(value);
    setDocumentIds([]);
    patchSessionFields({ workspace_id: value, document_ids: [] });
    pushScope(scopeChoice, { workspaceId: value, documentIds: [] });
  };
  const handleDocuments = (values: string[]) => {
    setDocumentIds(values);
    patchSessionFields({ document_ids: values });
    pushScope(scopeChoice, { documentIds: values });
  };
  const handleScopeChoice = (value: ScopeChoice) => {
    setScopeChoice(value);
    pushScope(value);
  };
  const handleScopeExpansion = (value: boolean) => {
    setAllowScopeExpansion(value);
    pushScope(scopeChoice, { allowExpansion: value });
  };
  const handleMode = (value: LearningMode) => { setMode(value); patchSessionFields({ mode: value }); };
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
    evidenceStatus={currentEvidence.status}
    degradationReason={currentEvidence.degradationReason}
    scopeChoice={scopeChoice}
    onScopeChoice={handleScopeChoice}
    allowWorkspaceExpansion={allowScopeExpansion}
    onAllowWorkspaceExpansion={handleScopeExpansion}
    onWorkspace={handleWorkspace}
    onDocuments={handleDocuments}
    onMode={handleMode}
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
            <Text>{`${workspaceName || '全部知识库'} · ${scopeSummaryLabel(scopeChoice, documentIds.length)}`}</Text>
            {presetPointTitle ? <Tag className="learning-preset-context">当前建议：{presetPointTitle}</Tag> : null}
            {scopeNoticeText(scopeNotice) ? <Tag color="blue">{scopeNoticeText(scopeNotice)}</Tag> : null}
          </div>
          <Space>
            <Button
              icon={<AimOutlined />}
              disabled={!currentEvidence.retrievalRunId}
              onClick={() => setDiagnosticsOpen(true)}
            >检索诊断</Button>
            <Button icon={<BulbOutlined />} onClick={() => setProfileOpen(true)}>导师眼中的我</Button>
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
        <ChatComposer value={question} disabled={workspacesLoading || documentsLoading} loading={streaming.loading} onChange={setQuestion} onSend={() => void sendQuestion()} onCancel={streaming.cancel} />
      </main>
      <div className="learning-desktop-settings">{modePanel}</div>
    </div>
    <Drawer title="学习会话" placement="left" width={300} open={sessionsDrawer} onClose={() => setSessionsDrawer(false)} className="learning-session-drawer">{sessionSidebar}</Drawer>
    <Drawer title="学习设置" placement="bottom" height="82vh" open={settingsDrawer} onClose={() => setSettingsDrawer(false)} className="learning-settings-drawer">{modePanel}</Drawer>
    <TutorProfileDrawer
      open={profileOpen}
      onClose={() => setProfileOpen(false)}
      profile={tutorProfile}
      memories={memories}
      kindFilter={memoryFilter}
      loading={memoryLoading}
      onFilter={setMemoryFilter}
      onToggle={(memory) => void updateMemory(memory.id, { is_active: !memory.is_active }).then(loadTutorContext)}
      onDelete={(memory) => void deleteMemory(memory.id).then(loadTutorContext)}
    />
    <EvidenceDrawer source={source} onClose={() => setSource(null)} onOpenSource={openSource} />
    <RetrievalDiagnostics
      open={diagnosticsOpen}
      runId={currentEvidence.retrievalRunId}
      evidence={{
        status: currentEvidence.status,
        degradationReason: currentEvidence.degradationReason,
        queryIntent: currentEvidence.queryIntent,
        rerankDegraded: currentEvidence.rerankDegraded,
        indexStale: currentEvidence.indexStale,
        indexStaleReasons: currentEvidence.indexStaleReasons,
        contextNotes: currentEvidence.contextNotes,
      }}
      onClose={() => setDiagnosticsOpen(false)}
    />
  </div>;
};

export default LearningChat;

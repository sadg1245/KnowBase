import React, { useCallback, useEffect, useState } from 'react';
import { App, Button, Empty, Modal, Skeleton } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { ReviewOverview } from '../components/review/ReviewOverview';
import { CardLibrary, type CardLibraryFilters } from '../components/review/CardLibrary';
import { CardEditorModal } from '../components/review/CardEditorModal';
import { ReviewSessionPanel } from '../components/review/ReviewSessionPanel';
import { ReviewResults } from '../components/review/ReviewResults';
import { createReviewSession, flipCard, recordReview, reviewDurationSeconds, reviewResults } from '../features/review/reviewSession';
import type { ReviewRating, ReviewSessionState } from '../features/review/types';
import {
  createCard, deleteCard, getCards, getReviewSummary, getWorkspaces,
  reviewCard, updateCard, type CardDraft, type Flashcard, type ReviewSummary, type Workspace,
} from '../services/api';

type ReviewMode = 'overview' | 'library' | 'session' | 'results';

const ReviewCenter: React.FC = () => {
  const { message } = App.useApp();
  const [mode, setMode] = useState<ReviewMode>('overview');
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [dueCards, setDueCards] = useState<Flashcard[]>([]);
  const [libraryCards, setLibraryCards] = useState<Flashcard[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [session, setSession] = useState<ReviewSessionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingCard, setEditingCard] = useState<Flashcard | null>(null);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSummary, nextDue] = await Promise.all([
        getReviewSummary(-new Date().getTimezoneOffset()),
        getCards(true),
      ]);
      setSummary(nextSummary);
      setDueCards(nextDue);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '复习概览没有加载成功');
    } finally { setLoading(false); }
  }, [message]);

  const loadLibrary = useCallback(async (filters: CardLibraryFilters = {}) => {
    setLibraryLoading(true);
    try { setLibraryCards(await getCards(false, undefined, filters)); }
    catch (error: any) { message.error(error?.response?.data?.detail || '卡片库没有加载成功'); }
    finally { setLibraryLoading(false); }
  }, [message]);

  useEffect(() => { void loadOverview(); }, [loadOverview]);

  const loadWorkspaceOptions = async (): Promise<Workspace[]> => {
    if (workspaces.length) return workspaces;
    const next = await getWorkspaces();
    setWorkspaces(next);
    return next;
  };

  const openLibrary = async () => {
    setMode('library');
    try { await Promise.all([loadWorkspaceOptions(), loadLibrary()]); }
    catch { message.error('知识库列表没有加载成功'); }
  };

  const openEditor = async (card: Flashcard | null) => {
    try {
      const options = await loadWorkspaceOptions();
      if (!options.length) { message.info('请先创建一个知识库'); return; }
    } catch { message.error('知识库列表没有加载成功'); return; }
    setEditingCard(card);
    setEditorOpen(true);
  };

  const saveCard = async (values: CardDraft) => {
    setSubmitting(true);
    try {
      if (editingCard) await updateCard(editingCard.id, values);
      else await createCard(values);
      message.success(editingCard ? '卡片已更新' : '卡片已创建');
      setEditorOpen(false);
      setEditingCard(null);
      await Promise.all([loadLibrary(), loadOverview()]);
    } catch (error: any) { message.error(error?.response?.data?.detail || '卡片保存失败'); }
    finally { setSubmitting(false); }
  };

  const removeCard = (card: Flashcard) => Modal.confirm({
    title: '删除这张卡片？',
    content: `“${card.front}”及其复习记录将无法继续使用。`,
    okText: '删除', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: async () => {
      try {
        await deleteCard(card.id);
        message.success('卡片已删除');
        await Promise.all([loadLibrary(), loadOverview()]);
      } catch (error: any) { message.error(error?.response?.data?.detail || '卡片删除失败'); }
    },
  });

  const startReview = () => {
    if (!dueCards.length) { message.info('今天没有待复习卡片'); return; }
    setSession(createReviewSession(dueCards, Date.now()));
    setMode('session');
  };

  const rateCard = async (rating: ReviewRating) => {
    if (!session || submitting) return;
    const current = session.cards[session.index];
    if (!current) return;
    const finishedAt = Date.now();
    setSubmitting(true);
    try {
      const response = await reviewCard(current.id, rating, reviewDurationSeconds(session, finishedAt));
      const next = recordReview(session, { rating, finishedAt, response });
      setSession(next);
      if (next.index >= next.cards.length) setMode('results');
    } catch (error: any) { message.error(error?.response?.data?.detail || '本次复习没有保存，请重试'); }
    finally { setSubmitting(false); }
  };

  const returnToOverview = () => {
    setMode('overview');
    void loadOverview();
  };

  if (loading && mode === 'overview') return <div className="paper-card review-page-loading"><Skeleton active paragraph={{ rows: 9 }} /></div>;
  if (mode === 'overview') return summary
    ? <ReviewOverview summary={summary} onStart={startReview} onManage={() => void openLibrary()} />
    : <div className="paper-card review-page-error"><Empty description="复习概览暂时不可用"><Button onClick={() => void loadOverview()}>重新加载</Button></Empty></div>;
  if (mode === 'session' && session) return <ReviewSessionPanel state={session} submitting={submitting} onFlip={() => setSession(flipCard(session))} onRate={rateCard} onExit={returnToOverview} />;
  if (mode === 'results' && session) return <ReviewResults results={reviewResults(session)} onOverview={returnToOverview} onCards={() => void openLibrary()} />;

  return <div>
    <Button className="review-back" type="text" icon={<ArrowLeftOutlined />} onClick={returnToOverview}>返回复习概览</Button>
    <CardLibrary cards={libraryCards} loading={libraryLoading} onCreate={() => void openEditor(null)} onEdit={card => void openEditor(card)} onDelete={removeCard} onFiltersChange={filters => void loadLibrary(filters)} />
    <CardEditorModal open={editorOpen} card={editingCard} workspaces={workspaces} submitting={submitting} onCancel={() => setEditorOpen(false)} onSubmit={saveCard} />
  </div>;
};

export default ReviewCenter;

import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { App, Alert, Button, Empty, Input, Progress, Radio, Select, Space, Tag } from 'antd';
import { ArrowLeftOutlined, CheckCircleOutlined, CloseCircleOutlined, HistoryOutlined } from '@ant-design/icons';

import { PracticeBuilder, type PracticeSection } from '../components/practice/PracticeBuilder';
import { QuizRunner } from '../components/practice/QuizRunner';
import type { PracticeAnswer, PracticeSessionState, QuizSetGenerateRequest, QuizRunView } from '../features/practice/types';
import {
  clearPracticeSessionDraft,
  createPracticeSession,
  loadPracticeSessionDraft,
  savePracticeSessionDraft,
  setAnswer as setSessionAnswer,
} from '../features/practice/practiceSession';
import {
  createQuizRun,
  Document,
  generateQuizSet,
  getDocuments,
  getKnowledgeBaseDetail,
  getQuizzes,
  getQuizSet,
  getWorkspaces,
  KnowledgePoint,
  QuizQuestion,
  retryAttemptGrading,
  retryQuizRun,
  startQuizRun,
  submitQuiz,
  submitQuizPaper,
  submitQuizQuestion,
  Workspace,
} from '../services/api';
import { documentSelectionOption, resetDocumentScope } from './documentScope';
import {
  createPracticeRequestGuard,
  finishMatchingPracticeOperation,
  practiceDocumentPlaceholder,
  practiceWorkspaceOption,
  readyPracticeDocuments,
  requestedPracticeScope,
  restoreGuardedPracticeRun,
  resolvePracticeDocumentIds,
  resolveRequestedKnowledgePointId,
  resolvePracticeWorkspaceSelection,
  submitGuardedLegacyAnswer,
} from './practiceScope';


const asRunView = (quizSet: Awaited<ReturnType<typeof getQuizSet>>): QuizRunView | null => (
  quizSet.latest_run ? { ...quizSet.latest_run, quiz_set: quizSet } : null
);

const errorDetail = (error: unknown, fallback: string): string => {
  if (typeof error !== 'object' || error === null) return fallback;
  const response = 'response' in error ? error.response : null;
  if (typeof response !== 'object' || response === null || !('data' in response)) return fallback;
  const data = response.data;
  return typeof data === 'object' && data !== null && 'detail' in data && typeof data.detail === 'string'
    ? data.detail
    : fallback;
};

type LegacySubmissionResult = Awaited<ReturnType<typeof submitQuiz>>;

interface LegacyPracticeViewProps {
  workspaces: Workspace[];
  workspaceId?: string;
  documents: Document[];
  documentIds: string[];
  workspacesLoading: boolean;
  scopeLoading: boolean;
  working: boolean;
  error?: string;
  questions: QuizQuestion[];
  questionIndex: number;
  answer: string;
  result: LegacySubmissionResult | null;
  onWorkspaceChange: (workspaceId?: string) => void;
  onDocumentChange: (documentIds: string[]) => void;
  onAnswerChange: (answer: string) => void;
  onSubmit: () => void | Promise<void>;
  onNext: () => void;
  onClearError: () => void;
}

export const LegacyPracticeView: React.FC<LegacyPracticeViewProps> = ({
  workspaces,
  workspaceId,
  documents,
  documentIds,
  workspacesLoading,
  scopeLoading,
  working,
  error,
  questions,
  questionIndex,
  answer,
  result,
  onWorkspaceChange,
  onDocumentChange,
  onAnswerChange,
  onSubmit,
  onNext,
  onClearError,
}) => {
  const currentQuestion = questions[questionIndex];
  const readyDocuments = readyPracticeDocuments(documents);
  return <div className="practice-page">
    <header className="practice-page-heading">
      <div>
        <div className="page-eyebrow">MISTAKE ARCHIVE · 兼容历史记录</div>
        <h1 className="page-title">历史错题重练</h1>
        <p className="page-lead">旧练习记录会继续保留；逐题重答，重新检验当时没掌握的内容。</p>
      </div>
      <Button href="/practice" icon={<ArrowLeftOutlined />}>返回新测验</Button>
    </header>
    <div className="practice-legacy-scope">
      <Select
        showSearch
        allowClear
        aria-label="选择知识库"
        placeholder="选择知识库"
        value={workspaceId}
        loading={workspacesLoading}
        onChange={onWorkspaceChange}
        options={workspaces.map(practiceWorkspaceOption)}
        optionFilterProp="label"
      />
      <Select
        mode="multiple"
        allowClear
        aria-label="选择练习文件"
        placeholder={scopeLoading ? '正在加载文件' : practiceDocumentPlaceholder(workspaceId, documents)}
        value={documentIds}
        loading={scopeLoading}
        disabled={!workspaceId || readyDocuments.length === 0}
        onChange={onDocumentChange}
        options={readyDocuments.map(documentSelectionOption)}
        optionFilterProp="label"
      />
    </div>
    {error ? <Alert className="practice-page-alert" type="error" showIcon message={error} closable onClose={onClearError} /> : null}
    {!currentQuestion ? <div className="paper-card empty-guide practice-legacy-empty">
      <Empty description={working ? '正在读取历史错题' : workspaceId ? '当前资料范围没有历史错题' : '请先选择知识库'} />
    </div> : <div className="practice-legacy-paper paper-card">
      <Space className="practice-legacy-meta">
        <span>第 {questionIndex + 1} 题，共 {questions.length} 题</span>
        <Tag icon={<HistoryOutlined />}>历史题目</Tag>
      </Space>
      <Progress percent={Math.round((questionIndex / questions.length) * 100)} showInfo={false} strokeColor="#167d8d" />
      <h2>{currentQuestion.prompt}</h2>
      {currentQuestion.options?.length ? <Radio.Group
        className="practice-answer-options"
        value={answer}
        onChange={event => onAnswerChange(event.target.value)}
      >
        {currentQuestion.options.map((option, index) => <Radio key={option} value={option}>
          <b>{String.fromCharCode(65 + index)}</b><span>{option}</span>
        </Radio>)}
      </Radio.Group> : <Input.TextArea
        rows={5}
        value={answer}
        onChange={event => onAnswerChange(event.target.value)}
        placeholder="重新写下你的答案"
      />}
      {result ? <Alert
        className="practice-inline-feedback"
        type={result.correct ? 'success' : 'warning'}
        showIcon
        icon={result.correct ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        message={result.correct ? '回答正确' : '再理解一下这个知识点'}
        description={<div><p><strong>参考答案：</strong>{result.reference_answer}</p><p><strong>解析：</strong>{result.explanation}</p></div>}
      /> : null}
      <div className="practice-paper-actions">
        <span />
        {!result ? <Button type="primary" loading={working} disabled={!answer.trim()} onClick={() => void onSubmit()}>提交答案</Button>
          : questionIndex < questions.length - 1 ? <Button type="primary" onClick={onNext}>下一题</Button>
            : <Button href="/practice">完成，返回新测验</Button>}
      </div>
    </div>}
  </div>;
};

const Practice: React.FC = () => {
  const { message } = App.useApp();
  const [params, setParams] = useSearchParams();
  const wrongOnly = params.get('wrong') === '1';
  const quizSetId = params.get('quiz_set')?.trim() || undefined;
  const requestedScope = requestedPracticeScope(params);
  const requestedWorkspaceId = requestedScope.workspaceId;
  const requestedKnowledgePointId = requestedScope.knowledgePointId;

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string>();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [knowledgePoints, setKnowledgePoints] = useState<KnowledgePoint[]>([]);
  const [sections, setSections] = useState<PracticeSection[]>([]);
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [knowledgePointIds, setKnowledgePointIds] = useState<string[]>([]);
  const [sectionFilters, setSectionFilters] = useState<string[]>([]);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [sessionOperation, setSessionOperation] = useState<{ token: number }>();
  const [legacyOperation, setLegacyOperation] = useState<{ token: number }>();
  const [gradingOperation, setGradingOperation] = useState<{ token: number; attemptId: string }>();
  const [session, setSession] = useState<PracticeSessionState | null>(null);
  const [pageError, setPageError] = useState<string>();

  const [legacyQuestions, setLegacyQuestions] = useState<QuizQuestion[]>([]);
  const [legacyIndex, setLegacyIndex] = useState(0);
  const [legacyAnswer, setLegacyAnswer] = useState('');
  const [legacyResult, setLegacyResult] = useState<LegacySubmissionResult | null>(null);

  const scopeRequestGuard = useRef(createPracticeRequestGuard());
  const sessionRequestGuard = useRef(createPracticeRequestGuard());
  const legacyRequestGuard = useRef(createPracticeRequestGuard());
  const legacyQuestionIdRef = useRef<string>();
  const readyDocuments = readyPracticeDocuments(documents);
  const effectiveDocumentIds = resolvePracticeDocumentIds(documents, documentIds);
  const effectiveDocumentScopeKey = effectiveDocumentIds.join('\u0000');
  const working = Boolean(sessionOperation || legacyOperation);
  const retryingAttemptId = gradingOperation?.attemptId;

  useEffect(() => {
    let active = true;
    setWorkspacesLoading(true);
    getWorkspaces()
      .then(items => {
        if (!active) return;
        setWorkspaces(items);
        setWorkspaceId(current => {
          if (requestedWorkspaceId && items.some(item => item.id === requestedWorkspaceId)) return requestedWorkspaceId;
          return resolvePracticeWorkspaceSelection(items, current);
        });
      })
      .catch(() => { if (active) setPageError('知识库加载失败，请稍后重试。'); })
      .finally(() => { if (active) setWorkspacesLoading(false); });
    return () => { active = false; };
  }, [requestedWorkspaceId]);

  useEffect(() => {
    const token = scopeRequestGuard.current.start();
    setDocumentIds(resetDocumentScope());
    setKnowledgePointIds([]);
    setSectionFilters([]);
    setDocuments([]);
    setKnowledgePoints([]);
    setSections([]);
    if (!workspaceId) {
      setScopeLoading(false);
      return;
    }

    setScopeLoading(true);
    Promise.all([getDocuments(workspaceId), getKnowledgeBaseDetail(workspaceId)])
      .then(([documentItems, detail]) => {
        if (!scopeRequestGuard.current.isCurrent(token)) return;
        setDocuments(documentItems);
        setKnowledgePoints(detail.knowledge_points);
        setSections(detail.documents.flatMap(document => (document.outline_items ?? []).map(item => ({
          documentId: document.id,
          sourceFile: document.filename,
          heading: item.heading,
          sectionPath: item.section_path,
        }))));
        const requestedPoint = (!requestedWorkspaceId || requestedWorkspaceId === workspaceId)
          ? resolveRequestedKnowledgePointId(
            detail.knowledge_points,
            requestedKnowledgePointId,
            workspaceId,
            resolvePracticeDocumentIds(documentItems, []),
          )
          : undefined;
        if (requestedPoint) setKnowledgePointIds([requestedPoint]);
      })
      .catch(() => {
        if (scopeRequestGuard.current.isCurrent(token)) setPageError('资料与知识点加载失败，请重新选择知识库。');
      })
      .finally(() => {
        if (scopeRequestGuard.current.isCurrent(token)) setScopeLoading(false);
      });
  }, [workspaceId, requestedWorkspaceId, requestedKnowledgePointId]);

  useEffect(() => {
    sessionRequestGuard.current.invalidate();
    setSessionOperation(undefined);
    setGradingOperation(undefined);
    setSession(current => (
      !wrongOnly && quizSetId && current?.run.quiz_set_id === quizSetId ? current : null
    ));
    if (wrongOnly || !quizSetId) {
      return () => { sessionRequestGuard.current.invalidate(); };
    }
    const token = sessionRequestGuard.current.start();
    setSessionOperation({ token });
    setPageError(undefined);
    restoreGuardedPracticeRun({
      token,
      isCurrent: sessionRequestGuard.current.isCurrent,
      loadQuizSet: () => getQuizSet(quizSetId),
      existingRun: quizSet => {
        if (quizSet.status === 'failed') throw new Error(quizSet.generation_error || '测验生成失败');
        return asRunView(quizSet);
      },
      createRun: quizSet => createQuizRun(quizSet.id, { answer_mode: quizSet.answer_mode, resume_unsubmitted: true }),
      startRun: run => startQuizRun(run.id),
    })
      .then(run => {
        if (!run || !sessionRequestGuard.current.isCurrent(token)) return;
        const restored = createPracticeSession(run, run.quiz_set.questions, Date.now(), loadPracticeSessionDraft(run.id));
        setWorkspaceId(run.quiz_set.workspace_id);
        setSession(restored);
        savePracticeSessionDraft(restored);
      })
      .catch(error => {
        if (sessionRequestGuard.current.isCurrent(token)) {
          setPageError(errorDetail(error, error instanceof Error ? error.message : '测验恢复失败，请重新生成。'));
        }
      })
      .finally(() => {
        setSessionOperation(current => finishMatchingPracticeOperation(current, token));
      });
    return () => { sessionRequestGuard.current.invalidate(); };
  }, [wrongOnly, quizSetId]);

  useEffect(() => {
    legacyRequestGuard.current.invalidate();
    setLegacyOperation(undefined);
    setLegacyQuestions([]);
    setLegacyIndex(0);
    setLegacyAnswer('');
    setLegacyResult(null);
    if (!wrongOnly || !workspaceId || scopeLoading || effectiveDocumentIds.length === 0) {
      return () => { legacyRequestGuard.current.invalidate(); };
    }
    const token = legacyRequestGuard.current.start();
    setLegacyOperation({ token });
    getQuizzes(true, workspaceId, effectiveDocumentIds)
      .then(items => {
        if (legacyRequestGuard.current.isCurrent(token)) setLegacyQuestions(items);
      })
      .catch(() => {
        if (legacyRequestGuard.current.isCurrent(token)) setPageError('历史错题加载失败，请稍后重试。');
      })
      .finally(() => {
        setLegacyOperation(current => finishMatchingPracticeOperation(current, token));
      });
    return () => { legacyRequestGuard.current.invalidate(); };
  }, [wrongOnly, workspaceId, scopeLoading, effectiveDocumentScopeKey]);

  useEffect(() => () => {
    scopeRequestGuard.current.invalidate();
    sessionRequestGuard.current.invalidate();
    legacyRequestGuard.current.invalidate();
  }, []);

  const changeWorkspace = (nextWorkspaceId?: string) => {
    scopeRequestGuard.current.invalidate();
    sessionRequestGuard.current.invalidate();
    legacyRequestGuard.current.invalidate();
    setSessionOperation(undefined);
    setLegacyOperation(undefined);
    setGradingOperation(undefined);
    setWorkspaceId(nextWorkspaceId);
    setDocumentIds(resetDocumentScope());
    setKnowledgePointIds([]);
    setSectionFilters([]);
    setSession(null);
    setPageError(undefined);
    setParams(current => {
      const next = new URLSearchParams(current);
      next.delete('quiz_set');
      next.delete('workspace_id');
      next.delete('knowledge_point_id');
      if (nextWorkspaceId) next.set('workspace', nextWorkspaceId);
      else next.delete('workspace');
      return next;
    }, { replace: true });
  };

  const changeDocuments = (nextDocumentIds: string[]) => {
    sessionRequestGuard.current.invalidate();
    legacyRequestGuard.current.invalidate();
    setSessionOperation(undefined);
    setLegacyOperation(undefined);
    setGradingOperation(undefined);
    setDocumentIds(nextDocumentIds);
    setSectionFilters([]);
    const nextEffectiveDocumentIds = resolvePracticeDocumentIds(documents, nextDocumentIds);
    setKnowledgePointIds(current => current.filter(pointId => {
      const point = knowledgePoints.find(item => item.id === pointId);
      return !point?.document_id || nextEffectiveDocumentIds.includes(point.document_id);
    }));
    setSession(null);
    setPageError(undefined);
  };

  const changeKnowledgePoints = (nextKnowledgePointIds: string[]) => {
    sessionRequestGuard.current.invalidate();
    setSessionOperation(undefined);
    setGradingOperation(undefined);
    setKnowledgePointIds(nextKnowledgePointIds);
    setPageError(undefined);
  };

  const changeSections = (nextSectionFilters: string[]) => {
    sessionRequestGuard.current.invalidate();
    setSessionOperation(undefined);
    setGradingOperation(undefined);
    setSectionFilters(nextSectionFilters);
    setPageError(undefined);
  };

  const generate = async (request: QuizSetGenerateRequest) => {
    const token = sessionRequestGuard.current.start();
    setSessionOperation({ token });
    setGradingOperation(undefined);
    setPageError(undefined);
    try {
      const quizSet = await generateQuizSet(request);
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      if (quizSet.status !== 'ready') throw new Error(quizSet.generation_error || '测验暂未生成完成');
      const createdRun = await createQuizRun(quizSet.id, { answer_mode: request.answer_mode, resume_unsubmitted: false });
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      const startedRun = await startQuizRun(createdRun.id);
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      clearPracticeSessionDraft();
      const nextSession = createPracticeSession(startedRun, startedRun.quiz_set.questions, Date.now());
      setSession(nextSession);
      setParams(current => {
        const next = new URLSearchParams(current);
        next.delete('wrong');
        next.set('workspace', request.workspace_id);
        next.set('quiz_set', quizSet.id);
        return next;
      }, { replace: true });
      message.success('测验已生成，可以开始作答');
    } catch (error) {
      if (sessionRequestGuard.current.isCurrent(token)) setPageError(errorDetail(error, error instanceof Error ? error.message : '测验生成失败，请稍后重试。'));
    } finally {
      setSessionOperation(current => finishMatchingPracticeOperation(current, token));
    }
  };

  const answerQuestion = (questionId: string, answer: PracticeAnswer) => {
    setSession(current => {
      if (!current) return current;
      const next = setSessionAnswer(current, questionId, answer);
      savePracticeSessionDraft(next);
      return next;
    });
  };

  const submitQuestion = async (questionId: string, answer: PracticeAnswer) => {
    if (!session) return;
    const token = sessionRequestGuard.current.start();
    setSessionOperation({ token });
    setGradingOperation(undefined);
    setPageError(undefined);
    try {
      const result = await submitQuizQuestion(session.run.id, questionId, {
        answer,
        duration_seconds: Math.max(0, Math.floor((Date.now() - session.createdAt) / 1_000)),
      });
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      const draft = { version: 1 as const, runId: result.run.id, answers: session.answers };
      const next = createPracticeSession(result.run, result.run.quiz_set.questions, session.createdAt, draft);
      setSession(next);
      savePracticeSessionDraft(next);
    } catch (error) {
      if (sessionRequestGuard.current.isCurrent(token)) setPageError(errorDetail(error, '答案提交失败，你的草稿仍保存在本机。'));
    } finally {
      setSessionOperation(current => finishMatchingPracticeOperation(current, token));
    }
  };

  const submitPaper = async () => {
    if (!session) return;
    const token = sessionRequestGuard.current.start();
    setSessionOperation({ token });
    setGradingOperation(undefined);
    setPageError(undefined);
    try {
      const run = await submitQuizPaper(session.run.id, {
        answers: session.answers,
        duration_seconds: Math.max(0, Math.floor((Date.now() - session.createdAt) / 1_000)),
      });
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      const next = createPracticeSession(run, run.quiz_set.questions, session.createdAt);
      setSession(next);
      savePracticeSessionDraft(next);
    } catch (error) {
      if (sessionRequestGuard.current.isCurrent(token)) setPageError(errorDetail(error, '交卷失败，你的答案仍保存在本机。'));
    } finally {
      setSessionOperation(current => finishMatchingPracticeOperation(current, token));
    }
  };

  const retryRun = async () => {
    if (!session) return;
    const token = sessionRequestGuard.current.start();
    setSessionOperation({ token });
    setGradingOperation(undefined);
    setPageError(undefined);
    try {
      const created = await retryQuizRun(session.run.id);
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      const started = await startQuizRun(created.id);
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      clearPracticeSessionDraft();
      setSession(createPracticeSession(started, started.quiz_set.questions, Date.now()));
      message.success('新一轮已经开始');
    } catch (error) {
      if (sessionRequestGuard.current.isCurrent(token)) setPageError(errorDetail(error, '无法开始新一轮，请稍后重试。'));
    } finally {
      setSessionOperation(current => finishMatchingPracticeOperation(current, token));
    }
  };

  const retryGrading = async (attemptId: string) => {
    if (!session || retryingAttemptId) return;
    const token = sessionRequestGuard.current.start();
    setSessionOperation(undefined);
    setGradingOperation({ token, attemptId });
    setPageError(undefined);
    try {
      const result = await retryAttemptGrading(attemptId);
      if (!sessionRequestGuard.current.isCurrent(token)) return;
      const draft = { version: 1 as const, runId: result.run.id, answers: session.answers };
      const next = createPracticeSession(result.run, result.run.quiz_set.questions, session.createdAt, draft);
      setSession(next);
      savePracticeSessionDraft(next);
    } catch (error) {
      if (sessionRequestGuard.current.isCurrent(token)) setPageError(errorDetail(error, '评分重试失败，答案仍已保存。'));
    } finally {
      setGradingOperation(current => finishMatchingPracticeOperation(current, token));
    }
  };

  const currentLegacyQuestion = legacyQuestions[legacyIndex];
  legacyQuestionIdRef.current = currentLegacyQuestion?.id;
  const submitLegacyAnswer = async () => {
    if (!currentLegacyQuestion || !legacyAnswer.trim()) return;
    const token = legacyRequestGuard.current.start();
    const questionId = currentLegacyQuestion.id;
    const answer = legacyAnswer;
    setLegacyOperation({ token });
    try {
      const result = await submitGuardedLegacyAnswer({
        token,
        questionId,
        isCurrent: legacyRequestGuard.current.isCurrent,
        currentQuestionId: () => legacyQuestionIdRef.current,
        submit: () => submitQuiz(questionId, answer),
      });
      if (result) setLegacyResult(result);
    } catch (error) {
      if (legacyRequestGuard.current.isCurrent(token) && legacyQuestionIdRef.current === questionId) {
        setPageError(errorDetail(error, '答案提交失败，请稍后重试。'));
      }
    } finally {
      setLegacyOperation(current => finishMatchingPracticeOperation(current, token));
    }
  };

  const nextLegacyQuestion = () => {
    setLegacyIndex(index => index + 1);
    setLegacyAnswer('');
    setLegacyResult(null);
  };

  if (wrongOnly) {
    return <LegacyPracticeView
      workspaces={workspaces}
      workspaceId={workspaceId}
      documents={documents}
      documentIds={documentIds}
      workspacesLoading={workspacesLoading}
      scopeLoading={scopeLoading}
      working={working}
      error={pageError}
      questions={legacyQuestions}
      questionIndex={legacyIndex}
      answer={legacyAnswer}
      result={legacyResult}
      onWorkspaceChange={changeWorkspace}
      onDocumentChange={changeDocuments}
      onAnswerChange={setLegacyAnswer}
      onSubmit={submitLegacyAnswer}
      onNext={nextLegacyQuestion}
      onClearError={() => setPageError(undefined)}
    />;
  }

  return <div className="practice-page">
    <header className="practice-page-heading">
      <div>
        <div className="page-eyebrow">PRACTICE · 用主动回忆检验理解</div>
        <h1 className="page-title">练习与测验</h1>
        <p className="page-lead">像批阅一份学习手稿那样，找到“以为会了”和“真的会了”之间的距离。</p>
      </div>
      {session ? <Button onClick={() => {
        sessionRequestGuard.current.invalidate();
        setSessionOperation(undefined);
        setGradingOperation(undefined);
        setSession(null);
        setParams(current => {
          const next = new URLSearchParams(current);
          next.delete('quiz_set');
          return next;
        }, { replace: true });
      }}>重新配置</Button> : null}
    </header>
    {pageError ? <Alert className="practice-page-alert" type="error" showIcon message={pageError} closable onClose={() => setPageError(undefined)} /> : null}
    {session ? <QuizRunner
      session={session}
      submitting={working}
      retrying={working}
      retryingAttemptId={retryingAttemptId}
      onAnswer={answerQuestion}
      onSubmitQuestion={submitQuestion}
      onSubmitPaper={submitPaper}
      onRetry={retryRun}
      onRetryGrading={retryGrading}
    /> : <PracticeBuilder
      workspaces={workspaces}
      documents={documents}
      knowledgePoints={knowledgePoints}
      sections={sections}
      workspaceId={workspaceId}
      selectedDocumentIds={documentIds}
      selectedKnowledgePointIds={knowledgePointIds}
      selectedSectionFilters={sectionFilters}
      workspacesLoading={workspacesLoading}
      scopeLoading={scopeLoading}
      generating={working}
      onWorkspaceChange={changeWorkspace}
      onDocumentChange={changeDocuments}
      onKnowledgePointChange={changeKnowledgePoints}
      onSectionChange={changeSections}
      onGenerate={generate}
    />}
  </div>;
};

export default Practice;

import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { App, Alert, Button, Card, Col, Empty, Input, Progress, Radio, Row, Select, Space, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, ThunderboltOutlined } from '@ant-design/icons';

import {
  Document,
  generateQuiz,
  getDocuments,
  getQuizzes,
  getWorkspaces,
  QuizQuestion,
  submitQuiz,
  Workspace,
} from '../services/api';
import { documentSelectionOption, resetDocumentScope } from './documentScope';
import {
  createPracticeRequestGuard,
  practiceDocumentPlaceholder,
  practiceWorkspaceOption,
  readyPracticeDocuments,
  resolvePracticeDocumentIds,
  resolvePracticeWorkspaceSelection,
} from './practiceScope';


const { Title, Text, Paragraph } = Typography;


const Practice: React.FC = () => {
  const { message } = App.useApp();
  const [params] = useSearchParams();
  const wrongOnly = params.get('wrong') === '1';
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);
  const [workspace, setWorkspace] = useState<string>();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const quizRequestGuard = useRef(createPracticeRequestGuard());
  const readyDocuments = readyPracticeDocuments(documents);
  const effectiveDocumentIds = resolvePracticeDocumentIds(documents, documentIds);
  const effectiveDocumentScopeKey = effectiveDocumentIds.join('\u0000');

  useEffect(() => {
    let active = true;
    setWorkspacesLoading(true);
    getWorkspaces()
      .then((items) => {
        if (!active) return;
        setWorkspaces(items);
        setWorkspace(current => resolvePracticeWorkspaceSelection(items, current));
      })
      .catch(() => message.error('知识库加载失败，请稍后重试'))
      .finally(() => { if (active) setWorkspacesLoading(false); });
    return () => { active = false; };
  }, [message]);

  useEffect(() => {
    quizRequestGuard.current.invalidate();
    setLoading(false);
  }, [wrongOnly]);

  useEffect(() => () => quizRequestGuard.current.invalidate(), []);

  useEffect(() => {
    setDocumentIds(resetDocumentScope());
    setDocuments([]);
    if (!workspace) {
      setDocumentsLoading(false);
      return;
    }

    let active = true;
    setDocumentsLoading(true);
    getDocuments(workspace)
      .then((items) => { if (active) setDocuments(items); })
      .catch(() => { if (active) message.error('资料列表加载失败'); })
      .finally(() => { if (active) setDocumentsLoading(false); });
    return () => { active = false; };
  }, [workspace, message]);

  useEffect(() => {
    let active = true;
    setQuestions([]);
    setIndex(0);
    setResult(null);
    setAnswer('');
    if (!workspace || documentsLoading || effectiveDocumentIds.length === 0) {
      return () => { active = false; };
    }
    const requestToken = quizRequestGuard.current.start();

    getQuizzes(wrongOnly, workspace, effectiveDocumentIds)
      .then((items) => {
        if (!active || !quizRequestGuard.current.isCurrent(requestToken)) return;
        setQuestions(items);
      })
      .catch(() => {
        if (active && quizRequestGuard.current.isCurrent(requestToken)) {
          message.error('练习题加载失败，请稍后重试');
        }
      });
    return () => { active = false; };
  }, [workspace, wrongOnly, documentsLoading, effectiveDocumentScopeKey, message]);

  const scopeUnavailable = !workspace || documentsLoading || effectiveDocumentIds.length === 0;
  const current = questions[index];

  const changeWorkspace = (value?: string) => {
    quizRequestGuard.current.invalidate();
    setLoading(false);
    setWorkspace(value);
    setDocumentIds(resetDocumentScope());
    setDocuments([]);
    setQuestions([]);
    setIndex(0);
    setResult(null);
    setAnswer('');
  };

  const changeDocuments = (values: string[]) => {
    quizRequestGuard.current.invalidate();
    setLoading(false);
    setDocumentIds(values);
    setQuestions([]);
    setIndex(0);
    setResult(null);
    setAnswer('');
  };

  const generate = async () => {
    if (!workspace || effectiveDocumentIds.length === 0) return;
    const requestToken = quizRequestGuard.current.start();
    setLoading(true);
    try {
      const generated = await generateQuiz(workspace, 5, documentIds);
      if (!quizRequestGuard.current.isCurrent(requestToken)) return;
      setQuestions(generated);
      setIndex(0);
      setResult(null);
      setAnswer('');
      message.success('新练习已经准备好');
    } catch (error: any) {
      if (!quizRequestGuard.current.isCurrent(requestToken)) return;
      message.error(error?.response?.data?.detail || '请先在知识库中生成知识点');
    } finally {
      if (quizRequestGuard.current.isCurrent(requestToken)) setLoading(false);
    }
  };

  const submit = async () => {
    if (!answer.trim() || !current) return;
    setResult(await submitQuiz(current.id, answer));
  };

  const next = () => {
    setIndex(value => value + 1);
    setAnswer('');
    setResult(null);
  };

  return <div>
    <Row align="bottom" justify="space-between" gutter={[16, 16]}>
      <Col>
        <div className="page-eyebrow">Practice · 用主动回忆检验理解</div>
        <Title className="page-title" level={1}>{wrongOnly ? '错题重练' : '练习与错题'}</Title>
        <p className="page-lead">答题不是为了分数，而是为了发现“以为会了”和“真的会了”之间的距离。</p>
      </Col>
      <Col className="practice-scope-column">
        <Space wrap className="practice-scope-controls">
          <Select
            showSearch
            allowClear
            aria-label="选择知识库"
            placeholder="选择知识库"
            value={workspace}
            onChange={changeWorkspace}
            loading={workspacesLoading}
            notFoundContent="暂无知识库"
            style={{ minWidth: 220 }}
            optionFilterProp="label"
            options={workspaces.map(practiceWorkspaceOption)}
          />
          <Select
            mode="multiple"
            showSearch
            allowClear
            aria-label="选择练习文件"
            maxTagCount="responsive"
            placeholder={documentsLoading ? '正在加载文件' : practiceDocumentPlaceholder(workspace, documents)}
            value={documentIds}
            onChange={changeDocuments}
            loading={documentsLoading}
            disabled={scopeUnavailable}
            notFoundContent="没有匹配的已解析文件"
            style={{ minWidth: 280, maxWidth: 420 }}
            options={readyDocuments.map(documentSelectionOption)}
            optionFilterProp="label"
          />
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={loading}
            disabled={scopeUnavailable}
            onClick={generate}
          >
            生成一组新题
          </Button>
        </Space>
      </Col>
    </Row>

    {!current ? <div className="paper-card empty-guide" style={{ marginTop: 32 }}>
      <Empty description={wrongOnly ? '当前没有待重练的错题' : workspace ? '当前资料范围还没有练习题' : '请先选择有文件的知识库'} />
      <Button type="primary" disabled={scopeUnavailable} onClick={generate}>根据当前资料范围生成练习</Button>
    </div> : <div style={{ maxWidth: 850, margin: '30px auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Text type="secondary">第 {index + 1} 题，共 {questions.length} 题</Text>
        <Tag>{current.question_type === 'short' ? '简答题' : current.question_type === 'choice' ? '选择题' : '判断题'}</Tag>
      </Space>
      <Progress percent={Math.round((index / questions.length) * 100)} showInfo={false} strokeColor="#167d8d" />
      <Card className="paper-card" style={{ marginTop: 18 }} styles={{ body: { padding: 'clamp(24px,5vw,50px)' } }}>
        <Title level={3} style={{ lineHeight: 1.6 }}>{current.prompt}</Title>
        {current.options?.length ? <Radio.Group
          value={answer}
          onChange={event => setAnswer(event.target.value)}
          style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 24 }}
        >
          {current.options.map((option, optionIndex) => <Radio.Button key={option} value={option} style={{ height: 'auto', padding: '11px 16px', borderRadius: 10 }}>
            {String.fromCharCode(65 + optionIndex)}. {option}
          </Radio.Button>)}
        </Radio.Group> : <Input.TextArea
          value={answer}
          onChange={event => setAnswer(event.target.value)}
          rows={5}
          placeholder="先用自己的话回答，不必追求和资料一字不差"
          style={{ marginTop: 20 }}
        />}
        {result ? <Alert
          style={{ marginTop: 24 }}
          type={result.correct ? 'success' : 'warning'}
          showIcon
          icon={result.correct ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
          message={result.correct ? '回答正确' : '再理解一下这个知识点'}
          description={<div>
            <Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 10 }}><strong>参考答案：</strong>{result.reference_answer}</Paragraph>
            {result.explanation ? <Paragraph><strong>解析：</strong>{result.explanation}</Paragraph> : null}
            {result.source_label ? <Tag>{result.source_label}</Tag> : null}
          </div>}
        /> : null}
        <Space style={{ marginTop: 26 }}>
          {!result
            ? <Button size="large" type="primary" disabled={!answer.trim()} onClick={submit}>提交答案</Button>
            : <Button size="large" type="primary" onClick={next}>{index + 1 >= questions.length ? '查看完成情况' : '下一题'}</Button>}
        </Space>
      </Card>
    </div>}
  </div>;
};


export default Practice;

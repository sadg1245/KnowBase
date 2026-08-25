import React, { useEffect, useState, useRef } from 'react';
import {
  Typography, Input, Select, Button, Card, Space, Spin, message, Divider, Statistic, Row, Col,
} from 'antd';
import {
  SearchOutlined, SendOutlined,
} from '@ant-design/icons';
import {
  Workspace, getWorkspaces, searchKnowledge, streamChat, normalizeChatSources, SearchResult,
} from '../services/api';
import SourceCard from '../components/SourceCard';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const SearchTest: React.FC = () => {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | undefined>(undefined);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [streamingAnswer, setStreamingAnswer] = useState('');
  const [mode, setMode] = useState<'search' | 'chat'>('search');
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const fetchWs = async () => {
      try {
        const data = await getWorkspaces();
        setWorkspaces(data);
      } catch {
        // 忽略错误
      }
    };
    fetchWs();
  }, []);

  const handleSearch = async () => {
    if (!question.trim()) {
      message.warning('请输入问题');
      return;
    }

    setLoading(true);
    setResult(null);
    setStreamingAnswer('');

    if (mode === 'search') {
      try {
        const data = await searchKnowledge(question, selectedWorkspace);
        setResult(data);
      } catch {
        message.error('检索失败，请检查后端服务');
      } finally {
        setLoading(false);
      }
    } else {
      // SSE 流式对话模式
      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;

      let fullAnswer = '';
      let sources = result?.sources || [];

      try {
        await streamChat(question, selectedWorkspace, (data) => {
          if ('token' in data) {
            fullAnswer += data.token;
            setStreamingAnswer(fullAnswer);
          } else if ('sources' in data) {
            sources = normalizeChatSources(data.sources || []);
            setResult({
              answer: fullAnswer,
              sources,
              timing: { retrieval_ms: 0, generation_ms: 0, total_ms: 0 },
            });
          } else if ('error' in data) {
            throw new Error(data.error);
          } else if ('done' in data && !data.full_text) {
            setLoading(false);
            setResult({
              answer: fullAnswer,
              sources,
              timing: { retrieval_ms: 0, generation_ms: 0, total_ms: 0 },
            });
          }
        }, controller.signal);
      } catch (error) {
        if (!controller.signal.aborted) {
          message.error(error instanceof Error ? error.message : '连接中断');
        }
      } finally {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const displayAnswer = result?.answer || streamingAnswer;

  return (
    <div>
      <Title level={3}>检索测试</Title>

      <Card style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Space wrap>
            <Text strong>模式：</Text>
            <Select
              value={mode}
              onChange={(v) => setMode(v)}
              style={{ width: 150 }}
              options={[
                { label: '知识检索', value: 'search' },
                { label: '对话问答', value: 'chat' },
              ]}
            />
            <Text strong style={{ marginLeft: 16 }}>工作区：</Text>
            <Select
              allowClear
              placeholder="全部工作区"
              style={{ width: 200 }}
              value={selectedWorkspace}
              onChange={(v) => setSelectedWorkspace(v)}
              options={workspaces.map((ws) => ({
                label: ws.name,
                value: ws.id,
              }))}
            />
          </Space>

          <TextArea
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="输入你的问题，例如：项目的主要技术架构是什么？"
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                handleSearch();
              }
            }}
          />

          <Button
            type="primary"
            icon={mode === 'search' ? <SearchOutlined /> : <SendOutlined />}
            onClick={handleSearch}
            loading={loading}
            size="large"
          >
            {mode === 'search' ? '开始检索' : '发送提问'}
          </Button>
        </Space>
      </Card>

      {loading && !streamingAnswer && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>
            <Text type="secondary">正在检索并生成回答...</Text>
          </div>
        </div>
      )}

      {displayAnswer && (
        <Card title="回答" style={{ marginTop: 16 }}>
          <Paragraph style={{ whiteSpace: 'pre-wrap', fontSize: 15 }}>
            {displayAnswer}
          </Paragraph>
          {loading && <Spin size="small" style={{ marginLeft: 4 }} />}
        </Card>
      )}

      {result && result.sources.length > 0 && (
        <>
          <Divider />
          <Title level={5}>参考来源（{result.sources.length} 条）</Title>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {result.sources.map((source, idx) => (
              <SourceCard key={idx} source={source} index={idx + 1} />
            ))}
          </div>
        </>
      )}

      {result?.timing && (
        <Card style={{ marginTop: 16 }} size="small">
          <Row gutter={24}>
            <Col span={8}>
              <Statistic
                title="检索耗时"
                value={result.timing.retrieval_ms}
                suffix="ms"
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="生成耗时"
                value={result.timing.generation_ms}
                suffix="ms"
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="总耗时"
                value={result.timing.total_ms}
                suffix="ms"
              />
            </Col>
          </Row>
        </Card>
      )}
    </div>
  );
};

export default SearchTest;

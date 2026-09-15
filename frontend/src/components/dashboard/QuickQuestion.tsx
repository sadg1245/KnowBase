import React, { useState } from 'react';
import { Button, Input, Select, Typography } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';

const { Text } = Typography;

export type QuickQuestionWorkspace = { id: string; name: string };

export const QuickQuestion: React.FC<{
  workspaces: QuickQuestionWorkspace[];
  onAsk: (question: string, workspaceId?: string) => void;
}> = ({ workspaces, onAsk }) => {
  const [question, setQuestion] = useState('');
  const [workspaceId, setWorkspaceId] = useState<string>();
  const submit = () => {
    const value = question.trim();
    if (value) onAsk(value, workspaceId);
  };
  return <section className="dashboard-question" aria-labelledby="quick-question-title">
    <div className="dashboard-question-copy">
      <Text className="dashboard-kicker">快速提问</Text>
      <h2 id="quick-question-title">此刻最想弄懂什么？</h2>
      <p>先写下你的问题，可以在进入学习会话后再确认发送。</p>
    </div>
    <div className="dashboard-question-form">
      <Select aria-label="选择知识库" allowClear placeholder="选择知识库（可选）" value={workspaceId}
        onChange={setWorkspaceId} options={workspaces.map(item => ({ value: item.id, label: item.name }))} />
      <span className="sr-only">可选知识库：{workspaces.map(item => item.name).join('、') || '暂无'}</span>
      <Input.TextArea aria-label="学习问题" autoSize={{ minRows: 2, maxRows: 4 }} value={question}
        onChange={event => setQuestion(event.target.value)} onPressEnter={event => {
          if (!event.shiftKey) { event.preventDefault(); submit(); }
        }} placeholder="例如：为什么梯度下降能逐步找到更优解？" />
      <Button type="primary" icon={<ArrowRightOutlined />} disabled={!question.trim()} onClick={submit}>带着问题去学习</Button>
    </div>
  </section>;
};

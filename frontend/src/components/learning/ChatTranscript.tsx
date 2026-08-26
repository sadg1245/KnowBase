import React from 'react';
import { Avatar, Button, Empty, Space, Tag, Typography } from 'antd';
import { BookOutlined, BulbOutlined } from '@ant-design/icons';

import type { SourceItem } from '../../services/api';
import type { DisplayMessage } from '../../features/learning/types';
import { evidenceStatusLabel } from '../../features/learning/learningConversationState';
import { FollowUpSuggestions } from './FollowUpSuggestions';
import { LearningMessageContent } from './LearningMessageContent';
import { MessageActions } from './MessageActions';
import 'katex/dist/katex.min.css';


const { Text, Title } = Typography;

interface Props {
  messages: DisplayMessage[];
  endRef: React.RefObject<HTMLDivElement>;
  onSource: (source: SourceItem) => void;
  onSuggestion: (value: string) => void;
  onCard: (message: DisplayMessage) => void;
  onNote: (message: DisplayMessage) => void;
  onMistake: (message: DisplayMessage) => void;
  onFeedback: (message: DisplayMessage, helpful: boolean) => void;
}


export const ChatTranscript: React.FC<Props> = ({ messages, endRef, onSource, onSuggestion, onCard, onNote, onMistake, onFeedback }) => <div className="learning-transcript" aria-live="polite">
  {!messages.length ? <div className="learning-empty-state">
    <span><BulbOutlined /></span>
    <Title level={2}>今天想弄懂什么？</Title>
    <Text>选择右侧的资料和学习方式，然后从一个真实问题开始。</Text>
  </div> : messages.map((item) => <article key={item.id} className={`learning-message learning-message-${item.role}`}>
    <Avatar className="learning-avatar">{item.role === 'user' ? '我' : <BulbOutlined />}</Avatar>
    <div className="learning-message-body">
      {item.role === 'assistant' && item.evidenceStatus ? <Tag className="learning-evidence-tag" color={item.evidenceStatus === 'supported' ? 'success' : item.evidenceStatus === 'error' ? 'error' : 'warning'}>{evidenceStatusLabel(item.evidenceStatus)}</Tag> : null}
      <div className="learning-message-content">{item.content
        ? <LearningMessageContent content={item.content} sources={item.sources} onSource={onSource} />
        : <Text type="secondary">正在检索并整理证据…</Text>}
      </div>
      {item.role === 'assistant' && item.content ? <>
        {item.sources.length ? <Space wrap size={[2, 4]} className="learning-source-links">
          {item.sources.map((source, index) => <Button key={`${source.document_id || source.filename}-${index}`} type="link" size="small" icon={<BookOutlined />} onClick={() => onSource(source)}>
            [{index + 1}] {source.filename}{source.page_number ? ` · 第${source.page_number}页` : ''}
          </Button>)}
        </Space> : null}
        {item.status !== 'streaming' && item.id ? <MessageActions
          onCard={() => onCard(item)}
          onNote={() => onNote(item)}
          onMistake={() => onMistake(item)}
          onCopy={() => navigator.clipboard.writeText(item.content)}
          onFeedback={(helpful) => onFeedback(item, helpful)}
        /> : null}
        <FollowUpSuggestions items={item.suggestions} onSelect={onSuggestion} />
      </> : null}
    </div>
  </article>)}
  <div ref={endRef} />
</div>;

import React, { useMemo, useState } from 'react';
import { Button, Empty, Input, Select, Skeleton, Tag, Typography } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import type { Flashcard } from '../../services/api';

const { Paragraph, Text, Title } = Typography;

export interface CardLibraryFilters {
  sourceType?: Flashcard['source_type'];
  query?: string;
}

interface CardLibraryProps {
  cards: Flashcard[];
  loading: boolean;
  onCreate: () => void;
  onEdit: (card: Flashcard) => void;
  onDelete: (card: Flashcard) => void;
  onFiltersChange: (filters: CardLibraryFilters) => void;
}

const sourceLabels: Record<Flashcard['source_type'], string> = {
  manual: '手动创建', knowledge_point: '知识点生成', answer: 'AI 回答', selection: '原文选段',
};

const masteryLabels: Record<Flashcard['mastery_status'], string> = {
  not_started: '未开始', learning: '学习中', mastered: '已掌握',
};

export const CardLibrary: React.FC<CardLibraryProps> = ({ cards, loading, onCreate, onEdit, onDelete, onFiltersChange }) => {
  const [query, setQuery] = useState('');
  const [sourceType, setSourceType] = useState<Flashcard['source_type']>();
  const filters = useMemo(() => ({ query: query.trim() || undefined, sourceType }), [query, sourceType]);

  return <div className="review-library">
    <div className="review-page-heading">
      <div><div className="page-eyebrow">Cards · 记忆素材</div><Title className="page-title" level={1}>卡片库</Title><p className="page-lead">整理问题、答案和来源，让每张卡片保持清楚、可追溯。</p></div>
      <Button type="primary" size="large" icon={<PlusOutlined />} onClick={onCreate}>新建卡片</Button>
    </div>
    <div className="review-library-toolbar paper-card">
      <Input.Search allowClear aria-label="搜索卡片" placeholder="搜索卡片" value={query} onChange={event => setQuery(event.target.value)} onSearch={() => onFiltersChange(filters)} />
      <Select
        aria-label="卡片来源" placeholder="全部来源" allowClear value={sourceType}
        options={Object.entries(sourceLabels).map(([value, label]) => ({ value, label }))}
        onChange={value => {
          const nextSource = value as Flashcard['source_type'] | undefined;
          setSourceType(nextSource);
          onFiltersChange({ query: query.trim() || undefined, sourceType: nextSource });
        }}
      />
    </div>
    {loading ? <div className="paper-card review-library-loading"><Skeleton active paragraph={{ rows: 6 }} /></div>
      : cards.length ? <div className="review-card-list">
        {cards.map(card => <article className="review-card-row paper-card" key={card.id}>
          <div className="review-card-copy">
            <div className="review-card-tags"><Tag color="cyan">{sourceLabels[card.source_type]}</Tag><Tag>{masteryLabels[card.mastery_status]} · {Math.round(card.mastery * 100)}%</Tag>{card.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}</div>
            <Title level={4}>{card.front}</Title>
            <Paragraph ellipsis={{ rows: 2 }}>{card.back}</Paragraph>
            <Text type="secondary">{card.source_label || '未填写来源'} · 难度 {card.difficulty} / 5</Text>
          </div>
          <div className="review-card-actions">
            <Button icon={<EditOutlined />} onClick={() => onEdit(card)}>编辑</Button>
            <Button danger icon={<DeleteOutlined />} onClick={() => onDelete(card)}>删除</Button>
          </div>
        </article>)}
      </div> : <div className="paper-card review-library-empty"><Empty description="还没有符合条件的卡片"><Button type="primary" onClick={onCreate}>创建第一张卡片</Button></Empty></div>}
  </div>;
};


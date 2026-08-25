import React from 'react';
import { Button, Space } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';


export const FollowUpSuggestions: React.FC<{ items: string[]; onSelect: (value: string) => void }> = ({ items, onSelect }) => items.length ? <Space wrap className="learning-follow-ups">
  {items.slice(0, 3).map((item) => <Button key={item} onClick={() => onSelect(item)}>{item}<ArrowRightOutlined /></Button>)}
</Space> : null;

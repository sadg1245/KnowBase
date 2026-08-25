import React from 'react';
import { Button, Input } from 'antd';
import { SendOutlined, StopOutlined } from '@ant-design/icons';


const { TextArea } = Input;

interface Props {
  value: string;
  disabled: boolean;
  loading: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  onCancel: () => void;
}


export const ChatComposer: React.FC<Props> = ({ value, disabled, loading, onChange, onSend, onCancel }) => <div className="learning-composer">
  <TextArea
    value={value}
    onChange={(event) => onChange(event.target.value)}
    autoSize={{ minRows: 1, maxRows: 5 }}
    placeholder={disabled ? '先选择一个知识库' : '输入问题，Enter 发送，Shift + Enter 换行'}
    disabled={disabled}
    onPressEnter={(event) => {
      if (!event.shiftKey) {
        event.preventDefault();
        onSend();
      }
    }}
  />
  <Button
    type="primary"
    shape="circle"
    aria-label={loading ? '停止生成' : '发送问题'}
    icon={loading ? <StopOutlined /> : <SendOutlined />}
    onClick={loading ? onCancel : onSend}
    disabled={disabled || (!loading && !value.trim())}
  />
</div>;

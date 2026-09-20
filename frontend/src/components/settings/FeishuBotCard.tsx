import React, { useEffect } from 'react';
import { Alert, Button, Card, Form, Input, Space, Tag, Typography } from 'antd';
import { SaveOutlined, SyncOutlined } from '@ant-design/icons';

import type { FeishuBotStatus, FeishuSettings } from '../../services/api';

const { Text, Paragraph, Link } = Typography;

export interface FeishuSettingsValues {
  app_id?: string;
  app_secret?: string;
}

/** 状态标签：过期状态一律按“未确认”展示，避免把十分钟前的“已连接”当成现状。 */
export const feishuStatusLabel = (
  status: FeishuBotStatus | null | undefined,
): { text: string; color: string } => {
  if (!status || status.state === 'unknown') return { text: '机器人状态未知', color: 'default' };
  if (status.stale) return { text: '机器人状态未更新', color: 'default' };
  switch (status.state) {
    case 'connected':
      return { text: '机器人已连接', color: 'green' };
    case 'connecting':
      return { text: '机器人连接中', color: 'processing' };
    case 'pending':
      return { text: '等待填写凭证', color: 'orange' };
    case 'restart_required':
      return { text: '需要重启机器人', color: 'gold' };
    case 'error':
      return { text: '机器人连接失败', color: 'red' };
    default:
      return { text: '机器人状态未知', color: 'default' };
  }
};

/** 只有用户真的填了内容才提交；清除配置走单独按钮，避免误清。 */
export const buildFeishuSettingsPayload = (
  values: FeishuSettingsValues,
): FeishuSettingsValues => {
  const payload: FeishuSettingsValues = {};
  const appId = (values.app_id || '').trim();
  const appSecret = (values.app_secret || '').trim();
  if (appId) payload.app_id = appId;
  if (appSecret) payload.app_secret = appSecret;
  return payload;
};

export const emptyFeishuPayload: FeishuSettingsValues = { app_id: '', app_secret: '' };

export const feishuSourceLabel = (settings: FeishuSettings | null): string => {
  if (!settings?.configured) return '还没有配置';
  return settings.source === 'env' ? '凭据来自 .env 文件' : '凭据来自本页设置';
};

interface Props {
  settings: FeishuSettings | null;
  loading?: boolean;
  saving?: boolean;
  onSave: (values: FeishuSettingsValues) => void | Promise<void>;
  onClear: () => void | Promise<void>;
}

export const FeishuBotCard: React.FC<Props> = ({
  settings,
  loading = false,
  saving = false,
  onSave,
  onClear,
}) => {
  const [form] = Form.useForm<FeishuSettingsValues>();
  const status = feishuStatusLabel(settings?.bot);

  useEffect(() => {
    form.setFieldsValue({ app_id: settings?.app_id || '', app_secret: '' });
  }, [form, settings?.app_id]);

  const submit = async () => {
    const values = await form.validateFields();
    await onSave(buildFeishuSettingsPayload(values));
    form.setFieldsValue({ app_secret: '' });
  };

  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <Card
      title="飞书机器人"
      loading={loading}
      extra={<Tag color={status.color}>{status.text}</Tag>}
    >
      <Paragraph type="secondary">
        在这里填一次 App ID 与 App Secret 就能用飞书机器人提问和复习，不需要改任何配置文件。
        机器人每 60 秒读取一次这里的配置，填好以后会自动上线。
      </Paragraph>
      <Space direction="vertical" size={4}>
        <Text strong>{feishuSourceLabel(settings)}</Text>
        {settings?.app_id ? <Text type="secondary">App ID：{settings.app_id}</Text> : null}
        {settings?.app_secret_masked ? (
          <Text type="secondary">App Secret：{settings.app_secret_masked}（已保存，留空表示不改）</Text>
        ) : null}
        {settings?.bot?.detail ? <Text type="secondary">{settings.bot.detail}</Text> : null}
      </Space>

      <Form form={form} layout="vertical" style={{ maxWidth: 480, marginTop: 16 }}>
        <Form.Item name="app_id" label="App ID" rules={[{ required: true, message: '请填写飞书应用的 App ID' }]}>
          <Input placeholder="cli_xxxxxxxxxxxx" autoComplete="off" />
        </Form.Item>
        <Form.Item name="app_secret" label="App Secret">
          <Input.Password placeholder="从飞书开放平台复制" autoComplete="new-password" />
        </Form.Item>
        <Space wrap>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={submit}>
            保存飞书配置
          </Button>
          <Button icon={<SyncOutlined />} onClick={() => void onClear()} disabled={!settings?.configured}>
            清除配置
          </Button>
        </Space>
      </Form>
    </Card>

    <Card title="三步接上飞书" size="small">
      <ol className="settings-steps">
        <li>
          打开 <Link href="https://open.feishu.cn/" target="_blank" rel="noreferrer">飞书开放平台</Link>，
          创建「自建应用」，在「应用功能」里启用「机器人」。
        </li>
        <li>
          在「事件与回调」中选择「使用长连接接收事件」，订阅 <Text code>im.message.receive_v1</Text>；
          权限至少给 <Text code>im:message</Text>、<Text code>im:message:send_as_bot</Text>、<Text code>im:chat</Text>、<Text code>im:resource</Text>。
        </li>
        <li>
          把应用凭证页的 App ID 与 App Secret 填到上面并保存，发布应用版本后在飞书里搜索机器人开始对话。
        </li>
      </ol>
      <Alert
        type="info"
        showIcon
        message="改完凭证后如果机器人已经连着，需要重启一次机器人容器才会换用新凭证。"
      />
    </Card>
  </Space>;
};

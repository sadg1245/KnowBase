import React, { useState } from 'react';
import { App, Button, Form, Input, Select, Space, Typography } from 'antd';
import { updateLLMSettings } from '../../services/api';
import { defaultModelFor, MODELS, PROVIDERS, providerNeedsKey } from './llmProviders';

const { Text } = Typography;

/**
 * 首次使用向导：让用户填自己的模型 API Key。
 * 用户可以跳过，之后在"偏好设置"里随时补上。
 */
export const ModelSetupWizard = ({
  finish,
}: {
  finish: (result: { configured: boolean }) => void;
}) => {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [provider, setProvider] = useState('deepseek');
  const [saving, setSaving] = useState(false);
  const needsKey = providerNeedsKey(provider);

  const submit = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      await updateLLMSettings({
        provider: values.provider,
        model: values.model,
        api_key: values.api_key || undefined,
        base_url: values.base_url || undefined,
      });
      message.success('AI 配置已保存');
      finish({ configured: true });
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存失败，请检查你的 API Key 是否正确');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="vault-screen">
      <div className="vault-card" style={{ maxWidth: 460 }}>
        <Typography.Title className="page-title" level={2}>
          配置你的 AI
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          拾光用你自己的模型来阅读和讲解资料。API Key 只保存在这台设备上，不会上传到我们的服务器。
        </Typography.Paragraph>
        <Form
          form={form}
          layout="vertical"
          initialValues={{ provider: 'deepseek', model: defaultModelFor('deepseek') }}
          onValuesChange={changed => {
            if (changed.provider) {
              setProvider(changed.provider);
              form.setFieldValue('model', defaultModelFor(changed.provider));
            }
          }}
        >
          <Form.Item name="provider" label="用哪个 AI" rules={[{ required: true }]}>
            <Select options={PROVIDERS} />
          </Form.Item>
          <Form.Item name="model" label="模型" rules={[{ required: true }]}>
            <Select options={MODELS[provider] || []} />
          </Form.Item>
          {needsKey ? (
            <Form.Item
              name="api_key"
              label="API Key"
              rules={[{ required: true, message: '请填写你的 API Key' }]}
              extra="在模型服务商的官网申请，填在这里只会保存到本机。"
            >
              <Input.Password placeholder="sk-..." autoComplete="off" />
            </Form.Item>
          ) : (
            <Form.Item name="base_url" label="Ollama 地址" extra="例如 http://localhost:11434">
              <Input placeholder="http://localhost:11434" />
            </Form.Item>
          )}
        </Form>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Button type="text" onClick={() => finish({ configured: false })}>稍后配置</Button>
          <Button type="primary" size="large" loading={saving} onClick={submit}>保存并开始</Button>
        </Space>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 14 }}>
          之后可以在"偏好设置 → LLM 设置"里修改。
        </Text>
      </div>
    </div>
  );
};

export default ModelSetupWizard;

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  App, Typography, Tabs, Form, Input, Select, Button, Space, Card, Spin, Descriptions, Tag, Divider, Avatar, Upload,
} from 'antd';
import {
  SaveOutlined, ApiOutlined, InfoCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, DownloadOutlined, UploadOutlined, UserOutlined,
} from '@ant-design/icons';
import {
  CurrentUser, LLMSettings, SystemInfo,
  clearAvatar, getMe, updateMe, uploadAvatar,
  getLLMSettings, updateLLMSettings, testLLM, getSystemInfo,
  getEmbeddingSettings, updateEmbeddingSettings, exportLearningData, getLearningProfile, updateLearningProfile,
} from '../services/api';
import { EMBEDDING_MODELS, MODELS, PROVIDERS } from '../features/account/llmProviders';

const { Title, Text } = Typography;

const Settings: React.FC = () => {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [llmForm] = Form.useForm();
  const [embedForm] = Form.useForm();
  const [learningForm] = Form.useForm();
  const [profileForm] = Form.useForm();
  const [profile, setProfile] = useState<CurrentUser | null>(null);
  const [avatarUrl, setAvatarUrl] = useState('');
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [selectedProvider, setSelectedProvider] = useState('openai');
  const [selectedEmbedProvider, setSelectedEmbedProvider] = useState('local');

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [settings, embedding, info, learningProfile, account] = await Promise.all([
          getLLMSettings(),
          getEmbeddingSettings(),
          getSystemInfo(),
          getLearningProfile(),
          getMe(),
        ]);
        llmForm.setFieldsValue(settings);
        setSelectedProvider(settings.provider || 'openai');
        embedForm.setFieldsValue({
          embedding_provider: 'local',
          embedding_model: embedding.model,
        });
        setSelectedEmbedProvider('local');
        setSystemInfo(info);
        learningForm.setFieldsValue(learningProfile);
        setProfile(account);
        profileForm.setFieldsValue({ display_name: account.display_name });
        setAvatarUrl(account.avatar_url || '');
      } catch {
        message.error('加载设置失败');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleSaveLLM = async () => {
    try {
      const values = await llmForm.validateFields();
      setSaving(true);
      await updateLLMSettings(values as LLMSettings);
      message.success('LLM 设置已保存');
    } catch {
      // 表单校验错误
    } finally {
      setSaving(false);
    }
  };

  const handleSaveEmbedding = async () => {
    try {
      const values = await embedForm.validateFields();
      setSaving(true);
      await updateEmbeddingSettings(values.embedding_model);
      message.success('Embedding 设置已保存；已有文档需要重新索引');
    } catch {
      message.error('保存 Embedding 设置失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    try {
      const values = await llmForm.validateFields();
      setTesting(true);
      setTestResult(null);
      // 先保存再测试
      await updateLLMSettings(values as LLMSettings);
      const result = await testLLM(values.provider, values.model);
      setTestResult(result);
      if (result.success) {
        message.success('连接测试成功');
      } else {
        message.error(result.message || '连接测试失败');
      }
    } catch {
      message.error('测试失败');
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <Title level={3}>系统设置</Title>

      <Tabs
        defaultActiveKey="llm"
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'learning',
            label: '学习偏好',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Card title="个人资料">
                <Space align="start" size={20} wrap>
                  <Avatar size={72} src={avatarUrl || undefined} icon={<UserOutlined />} style={{ background: '#dff4f1', color: '#126a76' }} />
                  <Space direction="vertical" size={10}>
                    <Form form={profileForm} layout="vertical" style={{ maxWidth: 420 }}>
                      <Form.Item name="display_name" label="昵称" rules={[{ required: true, message: '请输入昵称' }]}>
                        <Input />
                      </Form.Item>
                      <Form.Item label="头像外链（https）">
                        <Input
                          placeholder="https://example.com/avatar.png"
                          value={avatarUrl.startsWith('data:') ? '' : avatarUrl}
                          onChange={event => setAvatarUrl(event.target.value)}
                        />
                      </Form.Item>
                    </Form>
                    <Space wrap>
                      <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={async () => {
                        try {
                          const values = await profileForm.validateFields();
                          setSaving(true);
                          const updated = await updateMe({ display_name: values.display_name, avatar_url: avatarUrl || undefined });
                          setProfile(updated);
                          setAvatarUrl(updated.avatar_url || '');
                          message.success('个人资料已保存');
                        } catch (error: any) {
                          if (!error?.errorFields) message.error(error?.response?.data?.detail || '保存个人资料失败');
                        } finally {
                          setSaving(false);
                        }
                      }}>保存资料</Button>
                      <Upload
                        accept="image/png,image/jpeg,image/webp,image/gif"
                        showUploadList={false}
                        beforeUpload={async file => {
                          setUploadingAvatar(true);
                          try {
                            const updated = await uploadAvatar(file as File);
                            setProfile(updated);
                            setAvatarUrl(updated.avatar_url || '');
                            message.success('头像已更新');
                          } catch (error: any) {
                            message.error(error?.response?.data?.detail || '头像上传失败');
                          } finally {
                            setUploadingAvatar(false);
                          }
                          return false;
                        }}
                      >
                        <Button icon={<UploadOutlined />} loading={uploadingAvatar}>上传头像</Button>
                      </Upload>
                      <Button onClick={async () => {
                        try {
                          const updated = await clearAvatar();
                          setProfile(updated);
                          setAvatarUrl('');
                          message.success('头像已清除');
                        } catch {
                          message.error('清除头像失败');
                        }
                      }}>清除头像</Button>
                    </Space>
                    <Text type="secondary">账号：{profile?.username || '-'}（本部署只允许一个账号，创建后只能登录与退出）</Text>
                  </Space>
                </Space>
              </Card>
              <Card>
                <Form form={learningForm} layout="vertical" style={{ maxWidth: 600 }}>
                  <Form.Item name="display_name" label="怎么称呼你" rules={[{ required: true }]}><Input /></Form.Item>
                  <Form.Item name="daily_goal_minutes" label="每天计划学习多久"><Select options={[10,15,25,30,45,60,90].map(v => ({ label: `${v} 分钟`, value: v }))} /></Form.Item>
                  <Form.Item name="daily_review_target" label="每天计划复习多少张卡片"><Select options={[5,10,15,20,30,50].map(v => ({ label: `${v} 张`, value: v }))} /></Form.Item>
                  <Form.Item name="weekly_goal_days" label="每周计划学习多少天"><Select options={[1,2,3,4,5,6,7].map(v => ({ label: `${v} 天`, value: v }))} /></Form.Item>
                  <Form.Item name="timezone_name" label="学习报告时区" rules={[{ required: true, message: '请输入 IANA 时区' }]}><Input placeholder="Asia/Shanghai" /></Form.Item>
                  <Form.Item name="preferred_mode" label="默认学习方式"><Select options={[{label:'通俗讲解',value:'simple'},{label:'深入学习',value:'deep'},{label:'引导思考',value:'socratic'},{label:'费曼复述',value:'feynman'},{label:'直接回答',value:'direct'}]} /></Form.Item>
                  <Form.Item name="reminder_time" label="飞书每日复习提醒时间"><Input type="time" /></Form.Item>
                  <Space wrap><Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={async () => { try { setSaving(true); await updateLearningProfile(await learningForm.validateFields()); message.success('学习偏好已保存'); } finally { setSaving(false); } }}>保存学习偏好</Button>
                    <Button onClick={() => navigate('/report')}>设置完整学习目标</Button></Space>
                </Form>
              </Card>
              </Space>
            ),
          },
          {
            key: 'llm',
            label: 'LLM 设置',
            children: (
              <Card>
                <Form form={llmForm} layout="vertical" style={{ maxWidth: 600 }}>
                  <Form.Item
                    name="provider"
                    label="模型提供商"
                    rules={[{ required: true, message: '请选择提供商' }]}
                  >
                    <Select
                      options={PROVIDERS}
                      onChange={(val) => setSelectedProvider(val)}
                      placeholder="请选择"
                    />
                  </Form.Item>

                  <Form.Item
                    name="model"
                    label="模型"
                    rules={[{ required: true, message: '请选择模型' }]}
                  >
                    <Select
                      options={MODELS[selectedProvider] || []}
                      placeholder="请选择模型"
                      showSearch
                    />
                  </Form.Item>

                  <Form.Item
                    name="api_key"
                    label="API Key"
                    rules={[{ required: selectedProvider !== 'ollama', message: '请输入 API Key' }]}
                  >
                    <Input.Password
                      placeholder={
                        selectedProvider === 'ollama'
                          ? '本地模型无需 API Key'
                          : '输入你的 API Key'
                      }
                    />
                  </Form.Item>

                  {selectedProvider === 'ollama' && (
                    <Form.Item name="base_url" label="Ollama 地址">
                      <Input placeholder="http://localhost:11434" />
                    </Form.Item>
                  )}

                  <Form.Item>
                    <Space>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={handleSaveLLM}
                        loading={saving}
                      >
                        保存设置
                      </Button>
                      <Button
                        icon={<ApiOutlined />}
                        onClick={handleTest}
                        loading={testing}
                      >
                        测试连接
                      </Button>
                    </Space>
                  </Form.Item>

                  {testResult && (
                    <div
                      style={{
                        padding: 12,
                        borderRadius: 6,
                        background: testResult.success ? '#f6ffed' : '#fff2f0',
                        border: `1px solid ${testResult.success ? '#b7eb8f' : '#ffccc7'}`,
                      }}
                    >
                      <Space>
                        {testResult.success ? (
                          <CheckCircleOutlined style={{ color: '#52c41a' }} />
                        ) : (
                          <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                        )}
                        <Text>{testResult.message}</Text>
                      </Space>
                    </div>
                  )}
                </Form>
              </Card>
            ),
          },
          {
            key: 'embedding',
            label: 'Embedding 设置',
            children: (
              <Card>
                <Form form={embedForm} layout="vertical" style={{ maxWidth: 600 }}>
                  <Form.Item
                    name="embedding_provider"
                    label="Embedding 提供商"
                  >
                    <Select
                      options={[
                        { label: '本地模型', value: 'local' },
                        { label: 'OpenAI', value: 'openai' },
                        { label: '阿里通义 (DashScope)', value: 'dashscope' },
                        { label: 'Ollama (本地)', value: 'ollama' },
                      ]}
                      onChange={(val) => setSelectedEmbedProvider(val)}
                      placeholder="请选择"
                    />
                  </Form.Item>

                  <Form.Item
                    name="embedding_model"
                    label="Embedding 模型"
                  >
                    <Select
                      options={EMBEDDING_MODELS[selectedEmbedProvider] || []}
                      placeholder="请选择模型"
                      showSearch
                    />
                  </Form.Item>

                  <Form.Item>
                    <Button type="primary" icon={<SaveOutlined />} onClick={handleSaveEmbedding} loading={saving}>
                      保存设置
                    </Button>
                  </Form.Item>
                </Form>
              </Card>
            ),
          },
          {
            key: 'data',
            label: '我的数据',
            children: (
              <Card title="导出私人学习数据">
                <Text type="secondary">下载知识库信息、知识点、卡片、练习和学习记录的 JSON 备份。原始文档可在各知识库中单独下载。</Text>
                <div style={{ marginTop: 20 }}>
                  <Button icon={<DownloadOutlined />} onClick={async () => {
                    const data = await exportLearningData();
                    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
                    const link = document.createElement('a'); link.href = url; link.download = `拾光学习数据-${new Date().toISOString().slice(0,10)}.json`; link.click(); URL.revokeObjectURL(url);
                  }}>导出学习数据</Button>
                </div>
              </Card>
            ),
          },
          {
            key: 'system',
            label: '系统信息',
            children: (
              <Card>
                {systemInfo ? (
                  <Descriptions bordered column={1}>
                    <Descriptions.Item label="系统版本">
                      <Tag color="blue">v{systemInfo.version}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="工作区数量">
                      {systemInfo.total_workspaces}
                    </Descriptions.Item>
                    <Descriptions.Item label="文档总数">
                      {systemInfo.total_documents}
                    </Descriptions.Item>
                    <Descriptions.Item label="知识片段总数">
                      {systemInfo.total_chunks}
                    </Descriptions.Item>
                    <Descriptions.Item label="后端运行时间">
                      {Math.floor(systemInfo.backend_uptime / 3600)}小时
                      {Math.floor((systemInfo.backend_uptime % 3600) / 60)}分钟
                    </Descriptions.Item>
                  </Descriptions>
                ) : (
                  <Text type="secondary">
                    <InfoCircleOutlined /> 无法获取系统信息
                  </Text>
                )}
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
};

export default Settings;

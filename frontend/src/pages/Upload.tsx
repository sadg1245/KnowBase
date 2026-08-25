import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  App, Typography, Select, Button, Space, Progress, List, Tag, Card,
} from 'antd';
import {
  InboxOutlined, UploadOutlined, CheckCircleOutlined, CloseCircleOutlined,
  LoadingOutlined, ArrowLeftOutlined,
} from '@ant-design/icons';
import { useDropzone } from 'react-dropzone';
import { Workspace, getWorkspaces, uploadDocument, getDocumentStatus } from '../services/api';
import { resolveUploadWorkspace } from './uploadWorkspaceSelection';

const { Title, Text } = Typography;

interface UploadFileItem {
  file: File;
  progress: number;
  status: 'idle' | 'uploading' | 'processing' | 'ready' | 'failed';
  error?: string;
}

const ACCEPTED_TYPES = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
  'text/markdown': ['.md'],
  'text/plain': ['.txt'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'text/csv': ['.csv'],
  'text/html': ['.html'],
};

const Upload: React.FC = () => {
  const { message } = App.useApp();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>(
    searchParams.get('workspace') || ''
  );
  const [files, setFiles] = useState<UploadFileItem[]>([]);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    const fetchWs = async () => {
      try {
        const data = await getWorkspaces();
        setWorkspaces(data);
        setSelectedWorkspace((current) => resolveUploadWorkspace(data, current));
      } catch {
        message.error('获取工作区列表失败');
      }
    };
    fetchWs();
  }, []);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles: UploadFileItem[] = acceptedFiles.map((file) => ({
      file,
      progress: 0,
      status: 'idle' as const,
    }));
    setFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
  });

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleUploadAll = async () => {
    if (!selectedWorkspace) {
      message.warning('请先选择工作区');
      return;
    }
    if (files.length === 0) {
      message.warning('请先选择文件');
      return;
    }

    setUploading(true);

    for (let i = 0; i < files.length; i++) {
      if (files[i].status !== 'idle') continue;

      setFiles((prev) =>
        prev.map((f, idx) => (idx === i ? { ...f, status: 'uploading' } : f))
      );

      try {
        const document = await uploadDocument(selectedWorkspace, files[i].file, (percent) => {
          setFiles((prev) =>
            prev.map((f, idx) => (idx === i ? { ...f, progress: percent } : f))
          );
        });

        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i ? { ...f, status: 'processing', progress: 100 } : f
          )
        );

        let finalStatus = document.status;
        let errorMessage = document.error_message || undefined;
        for (let attempt = 0; attempt < 120 && ['pending', 'processing'].includes(finalStatus); attempt++) {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          const status = await getDocumentStatus(document.id);
          finalStatus = status.status;
          errorMessage = status.error_message || undefined;
        }

        if (finalStatus !== 'ready' && finalStatus !== 'failed') {
          finalStatus = 'failed';
          errorMessage = '处理超时，请到文档管理页查看状态';
        }
        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i ? { ...f, status: finalStatus as 'ready' | 'failed', error: errorMessage } : f
          )
        );
        if (finalStatus === 'failed') {
          message.error(`${files[i].file.name} 处理失败`);
        }
      } catch {
        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i ? { ...f, status: 'failed', error: '上传失败' } : f
          )
        );
      }
    }

    setUploading(false);
    message.success('上传任务完成');
  };

  const getStatusIcon = (status: UploadFileItem['status']) => {
    switch (status) {
      case 'uploading':
        return <LoadingOutlined style={{ color: '#1677ff' }} />;
      case 'processing':
        return <LoadingOutlined style={{ color: '#1677ff' }} />;
      case 'ready':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'failed':
        return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      default:
        return null;
    }
  };

  const getStatusTag = (status: UploadFileItem['status']) => {
    switch (status) {
      case 'idle':
        return <Tag>等待上传</Tag>;
      case 'uploading':
        return <Tag color="blue">上传中</Tag>;
      case 'processing':
        return <Tag color="processing">处理中</Tag>;
      case 'ready':
        return <Tag color="success">已就绪</Tag>;
      case 'failed':
        return <Tag color="error">失败</Tag>;
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
            返回
          </Button>
          <Title level={3} style={{ margin: 0 }}>
            文件上传
          </Title>
        </Space>
      </div>

      <Card style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Text strong>选择工作区：</Text>
            <Select
              style={{ width: 300, marginLeft: 8 }}
              placeholder="请选择目标工作区"
              value={selectedWorkspace || undefined}
              onChange={(val) => setSelectedWorkspace(val)}
              options={workspaces.map((ws) => ({
                label: ws.name,
                value: ws.id,
              }))}
            />
          </div>

          <div
            {...getRootProps()}
            style={{
              border: '2px dashed #d9d9d9',
              borderRadius: 8,
              padding: 48,
              textAlign: 'center',
              cursor: 'pointer',
              background: isDragActive ? '#e6f4ff' : '#fafafa',
              transition: 'all 0.3s',
            }}
          >
            <input {...getInputProps()} />
            <InboxOutlined style={{ fontSize: 48, color: '#1677ff' }} />
            <div style={{ marginTop: 16 }}>
              {isDragActive ? (
                <Text>释放文件以上传...</Text>
              ) : (
                <Text>将文件拖拽到此处，或点击选择文件</Text>
              )}
            </div>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                支持格式：PDF、DOCX、PPTX、MD、TXT、XLSX、CSV、HTML
              </Text>
            </div>
          </div>
        </Space>
      </Card>

      {files.length > 0 && (
        <Card
          title={`已选择 ${files.length} 个文件`}
          style={{ marginTop: 16 }}
          extra={
            <Space>
              <Button onClick={() => setFiles([])} disabled={uploading}>
                清空列表
              </Button>
              <Button
                type="primary"
                icon={<UploadOutlined />}
                onClick={handleUploadAll}
                loading={uploading}
              >
                开始上传
              </Button>
            </Space>
          }
        >
          <List
            dataSource={files}
            renderItem={(item, index) => (
              <List.Item
                actions={[
                  item.status === 'idle' ? (
                    <Button
                      type="text"
                      danger
                      size="small"
                      onClick={() => removeFile(index)}
                    >
                      移除
                    </Button>
                  ) : null,
                ]}
              >
                <List.Item.Meta
                  avatar={getStatusIcon(item.status)}
                  title={
                    <Space>
                      <span>{item.file.name}</span>
                      {getStatusTag(item.status)}
                    </Space>
                  }
                  description={
                    <div>
                      <Text type="secondary">
                        {(item.file.size / 1024).toFixed(1)} KB
                      </Text>
                      {item.status === 'uploading' && (
                        <Progress
                          percent={item.progress}
                          size="small"
                          style={{ marginTop: 4 }}
                        />
                      )}
                      {item.error && (
                        <Text type="danger" style={{ marginLeft: 8 }}>
                          {item.error}
                        </Text>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      )}
    </div>
  );
};

export default Upload;

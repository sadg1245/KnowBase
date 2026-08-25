import React, { useCallback } from 'react';
import { Typography, Space } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { useDropzone, Accept } from 'react-dropzone';

const { Text } = Typography;

const DEFAULT_ACCEPT: Accept = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/msword': ['.doc'],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
  'application/vnd.ms-powerpoint': ['.ppt'],
  'text/markdown': ['.md'],
  'text/plain': ['.txt'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'text/csv': ['.csv'],
  'text/html': ['.html'],
};

interface FileUploaderProps {
  onFilesSelected: (files: File[]) => void;
  accept?: Accept;
  hint?: string;
}

const FileUploader: React.FC<FileUploaderProps> = ({
  onFilesSelected,
  accept = DEFAULT_ACCEPT,
  hint = '支持格式：PDF、DOCX、DOC、PPTX、PPT、MD、TXT、XLSX、CSV、HTML',
}) => {
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      onFilesSelected(acceptedFiles);
    },
    [onFilesSelected]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
  });

  return (
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
      <Space direction="vertical" size={8}>
        <InboxOutlined style={{ fontSize: 48, color: '#1677ff' }} />
        {isDragActive ? (
          <Text>释放文件以上传...</Text>
        ) : (
          <Text>将文件拖拽到此处，或点击选择文件</Text>
        )}
        <Text type="secondary" style={{ fontSize: 12 }}>
          {hint}
        </Text>
      </Space>
    </div>
  );
};

export default FileUploader;

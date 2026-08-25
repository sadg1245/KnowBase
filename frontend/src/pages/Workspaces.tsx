import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App, Button, Col, Empty, Form, Input, Modal, Progress, Row, Select, Space, Tag, Typography } from 'antd';
import { ArrowRightOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Workspace, createWorkspace, deleteWorkspace, getWorkspaces, updateKnowledgeBase } from '../services/api';
const { Title, Text } = Typography;
const colors = ['#167d8d','#6e71a8','#d9913b','#3f8f6b','#c45f72'];

type WorkspaceDeletionConfirmation = {
  title: string;
  content: string;
  okText: string;
  cancelText: string;
  centered: boolean;
  okButtonProps: { danger: boolean };
  onOk: () => Promise<void>;
};

type WorkspaceDeletionActions = {
  confirm: (confirmation: WorkspaceDeletionConfirmation) => void;
  remove: (workspaceId: string) => Promise<void>;
  onSuccess: (workspaceName: string) => void;
  onError: (error: unknown) => void;
};

export const requestWorkspaceDeletion = (
  workspace: Pick<Workspace, 'id' | 'name'>,
  actions: WorkspaceDeletionActions,
) => {
  actions.confirm({
    title: `删除知识库“${workspace.name}”？`,
    content: '相关资料和学习记录将一起删除，此操作不可撤销。',
    okText: '确定删除',
    cancelText: '取消',
    centered: true,
    okButtonProps: { danger: true },
    onOk: async () => {
      try {
        await actions.remove(workspace.id);
        actions.onSuccess(workspace.name);
      } catch (error) {
        actions.onError(error);
        throw error;
      }
    },
  });
};

const Workspaces: React.FC = () => {
  const { message, modal } = App.useApp();
  const navigate = useNavigate(); const [items,setItems]=useState<Workspace[]>([]); const [open,setOpen]=useState(false); const [loading,setLoading]=useState(true); const [form]=Form.useForm();
  const load=()=>{setLoading(true);getWorkspaces().then(setItems).catch(()=>message.error('知识库没有加载成功')).finally(()=>setLoading(false));};
  useEffect(load,[]);
  const create=async()=>{const v=await form.validateFields();try{const item=await createWorkspace(v.name,v.description||''); await updateKnowledgeBase(item.id,{learning_goal:v.learning_goal,domain:v.domain,accent_color:v.accent_color});message.success('知识库已创建');setOpen(false);form.resetFields();load();}catch{message.error('创建失败');}};
  return <div>
    <Row align="bottom" justify="space-between" gutter={[16,16]}><Col><div className="page-eyebrow">Library · 你的学习书架</div><Title className="page-title" level={1}>我的知识库</Title><p className="page-lead">按目标整理资料，而不是让文件堆在一起。每个知识库都是一段可以继续的学习旅程。</p></Col><Col><Button type="primary" size="large" icon={<PlusOutlined/>} onClick={()=>setOpen(true)}>新建知识库</Button></Col></Row>
    {!loading && !items.length ? <div className="paper-card empty-guide" style={{marginTop:32}}><Empty description="从一个真正想弄懂的主题开始"/><Button type="primary" onClick={()=>setOpen(true)}>创建第一个知识库</Button></div> : <Row gutter={[18,18]} style={{marginTop:32}}>{items.filter(i=>!i.archived).map((item,index)=><Col xs={24} md={12} xl={8} key={item.id}>
      <article className="paper-card lift" style={{padding:22,minHeight:225,borderTop:`5px solid ${item.accent_color||colors[index%colors.length]}`,display:'flex',flexDirection:'column'}}>
        <Space style={{justifyContent:'space-between'}}><Tag bordered={false}>{item.domain||'未分类'}</Tag><Button type="text" danger size="small" aria-label={`删除知识库 ${item.name}`} icon={<DeleteOutlined/>} onClick={()=>requestWorkspaceDeletion(item,{confirm:confirmation=>{modal.confirm(confirmation);},remove:deleteWorkspace,onSuccess:workspaceName=>{message.success(`知识库“${workspaceName}”已删除`);load();},onError:()=>message.error('删除失败，请稍后重试')})}/></Space>
        <Title level={3} style={{margin:'16px 0 7px'}}>{item.name}</Title><Text type="secondary" ellipsis={{tooltip:item.learning_goal||item.description}}>{item.learning_goal||item.description||'还没有写下学习目标'}</Text>
        <div style={{marginTop:'auto',paddingTop:24}}><Space style={{width:'100%',justifyContent:'space-between'}}><Text type="secondary">{item.document_count||0} 份资料</Text><Button type="link" onClick={()=>navigate(`/knowledge/${item.id}`)}>继续学习 <ArrowRightOutlined/></Button></Space></div>
      </article>
    </Col>)}</Row>}
    <Modal title="新建一个学习主题" open={open} onOk={create} onCancel={()=>setOpen(false)} okText="创建知识库" cancelText="取消" width={560}><Form form={form} layout="vertical" initialValues={{domain:'未分类',accent_color:colors[0]}} style={{marginTop:20}}><Form.Item name="name" label="知识库名称" rules={[{required:true,message:'写下你想学习的主题'}]}><Input size="large" placeholder="例如：系统学习 Python"/></Form.Item><Form.Item name="learning_goal" label="我想达到什么目标"><Input.TextArea rows={3} placeholder="例如：能独立完成一个数据分析项目"/></Form.Item><Form.Item name="description" label="简短说明"><Input placeholder="这组资料主要包含什么？"/></Form.Item><Row gutter={12}><Col span={12}><Form.Item name="domain" label="学习领域"><Select options={['编程','语言','考试','职业技能','兴趣阅读','未分类'].map(v=>({label:v,value:v}))}/></Form.Item></Col><Col span={12}><Form.Item name="accent_color" label="书脊颜色"><Select options={colors.map(c=>({label:<Space><span style={{width:12,height:12,borderRadius:4,background:c,display:'inline-block'}}/>{c}</Space>,value:c}))}/></Form.Item></Col></Row></Form></Modal>
  </div>;
};
export default Workspaces;

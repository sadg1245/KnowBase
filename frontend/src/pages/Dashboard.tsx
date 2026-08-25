import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App, Button, Col, Empty, Progress, Row, Skeleton, Space, Tag, Typography } from 'antd';
import { ArrowRightOutlined, BookOutlined, ClockCircleOutlined, FireOutlined, ReadOutlined, TrophyOutlined } from '@ant-design/icons';
import { getLearningDashboard, LearningDashboard } from '../services/api';

const { Title, Text } = Typography;

const Dashboard: React.FC = () => {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [data, setData] = useState<LearningDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => { getLearningDashboard().then(setData).catch(() => message.error('学习数据暂时没有加载成功')).finally(() => setLoading(false)); }, []);
  const greeting = useMemo(() => new Date().getHours() < 12 ? '早上好' : new Date().getHours() < 18 ? '下午好' : '晚上好', []);
  if (loading) return <Skeleton active paragraph={{ rows: 10 }} />;
  const stats = data?.stats;
  const goal = data?.profile.daily_goal_minutes || 25;
  const completion = Math.min(100, Math.round(((stats?.today_minutes || 0) / goal) * 100));

  return <div>
    <div className="page-eyebrow">Today · 你的学习现场</div>
    <Row gutter={[24, 24]} align="bottom">
      <Col flex="auto"><Title className="page-title" level={1}>{greeting}，{data?.profile.display_name || '学习者'}</Title><p className="page-lead">今天不必学很多，沿着昨天留下的线索继续走一点就好。</p></Col>
      <Col><Button type="primary" size="large" icon={<BookOutlined />} onClick={() => navigate('/learn')}>开始一次学习</Button></Col>
    </Row>

    <Row gutter={[18, 18]} style={{ marginTop: 30 }}>
      <Col xs={24} lg={14}>
        <section className="paper-card" style={{ padding: 26, height:'100%' }}>
          <Space align="start" style={{ width:'100%', justifyContent:'space-between' }}>
            <div><Text type="secondary">今日节奏</Text><Title level={2} style={{ margin:'4px 0 0' }}><span className="metric-number">{stats?.today_minutes || 0}</span> <small style={{fontSize:15,fontWeight:400}}>分钟</small></Title></div>
            <div style={{ width:72 }}><Progress type="circle" size={72} percent={completion} strokeColor="#167d8d" trailColor="#dcebea" format={() => `${completion}%`} /></div>
          </Space>
          <div className="learning-trail" style={{ marginTop:28 }}>
            {(data?.today_tasks || []).map((task, index) => <button key={task.type} onClick={() => navigate(task.path)} style={{ display:'flex',width:'100%',border:0,background:'transparent',padding:'0 0 22px',textAlign:'left',cursor:'pointer',position:'relative' }}>
              <span className="trail-dot" style={{top:4}} /><span style={{flex:1}}><Text strong>{task.title}</Text><br/><Text type="secondary">{task.count ? `还有 ${task.count} 项等待你` : '今天已经完成'}</Text></span><ArrowRightOutlined style={{color:'#78909b',marginTop:6}} />
            </button>)}
            <button onClick={() => navigate('/knowledge')} style={{ display:'flex',width:'100%',border:0,background:'transparent',padding:0,textAlign:'left',cursor:'pointer',position:'relative' }}><span className="trail-dot" style={{top:4,borderColor:'#f0a35b'}}/><span style={{flex:1}}><Text strong>继续最近的知识库</Text><br/><Text type="secondary">从上次停下的地方接着学</Text></span><ArrowRightOutlined style={{color:'#78909b',marginTop:6}} /></button>
          </div>
        </section>
      </Col>
      <Col xs={24} lg={10}>
        <section className="soft-panel" style={{ padding:26,height:'100%' }}>
          <Text type="secondary">本周一瞥</Text>
          <Row gutter={[12,22]} style={{marginTop:20}}>
            <Col span={12}><FireOutlined style={{color:'#ef7d59'}}/><div className="metric-number" style={{fontSize:30,fontWeight:700}}>{stats?.streak_days || 0}</div><Text type="secondary">连续学习天数</Text></Col>
            <Col span={12}><ClockCircleOutlined style={{color:'#167d8d'}}/><div className="metric-number" style={{fontSize:30,fontWeight:700}}>{stats?.week_minutes || 0}</div><Text type="secondary">本周学习分钟</Text></Col>
            <Col span={12}><ReadOutlined style={{color:'#6e71a8'}}/><div className="metric-number" style={{fontSize:30,fontWeight:700}}>{stats?.knowledge_point_count || 0}</div><Text type="secondary">已整理知识点</Text></Col>
            <Col span={12}><TrophyOutlined style={{color:'#d9913b'}}/><div className="metric-number" style={{fontSize:30,fontWeight:700}}>{stats?.wrong_questions || 0}</div><Text type="secondary">待攻克错题</Text></Col>
          </Row>
        </section>
      </Col>
    </Row>

    <Row gutter={[24,24]} style={{marginTop:24}}>
      <Col xs={24} xl={15}>
        <Space style={{width:'100%',justifyContent:'space-between',marginBottom:14}}><Title level={3} style={{margin:0}}>最近的知识库</Title><Button type="link" onClick={() => navigate('/knowledge')}>查看全部</Button></Space>
        {(data?.recent_workspaces || []).length ? <Row gutter={[14,14]}>{data!.recent_workspaces.map((item) => <Col xs={24} sm={12} key={item.id}><button className="paper-card lift" onClick={() => navigate(`/knowledge/${item.id}`)} style={{width:'100%',padding:20,textAlign:'left',cursor:'pointer',borderTop:`4px solid ${item.accent_color || '#167d8d'}`}}><Tag bordered={false}>{item.domain || '未分类'}</Tag><Title level={4} style={{margin:'12px 0 6px'}}>{item.name}</Title><Text type="secondary" ellipsis>{item.learning_goal || item.description || '为这个知识库写下一个学习目标'}</Text></button></Col>)}</Row> : <div className="paper-card empty-guide"><Empty description="还没有知识库"/><Button type="primary" onClick={() => navigate('/knowledge')}>创建第一个知识库</Button></div>}
      </Col>
      <Col xs={24} xl={9}>
        <Title level={3} style={{margin:'0 0 14px'}}>值得再看一眼</Title>
        <div className="paper-card" style={{padding:'8px 20px'}}>{(data?.weak_points || []).length ? data!.weak_points.map((point) => <button key={point.id} onClick={() => navigate(`/knowledge/${point.workspace_id}`)} style={{width:'100%',padding:'14px 0',display:'flex',gap:12,alignItems:'center',border:0,borderBottom:'1px solid #edf1f2',background:'transparent',textAlign:'left',cursor:'pointer'}}><Progress type="circle" size={38} percent={Math.round(point.mastery*100)} showInfo={false} strokeColor="#ef7d59"/><span style={{flex:1}}><Text strong>{point.title}</Text><br/><Text type="secondary" style={{fontSize:12}}>掌握度 {Math.round(point.mastery*100)}%</Text></span></button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="学习后会在这里发现薄弱点"/>}</div>
      </Col>
    </Row>
  </div>;
};
export default Dashboard;

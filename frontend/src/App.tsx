import React, { Suspense, lazy, useEffect, useState } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { App as AntApp, ConfigProvider, Drawer, Layout, Menu, Button, Avatar, Typography, Input } from 'antd';
import {
  BookOutlined, HomeOutlined, MessageOutlined, ReadOutlined, TrophyOutlined,
  BarChartOutlined, UploadOutlined, SettingOutlined, MenuOutlined, BulbOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import { Spin } from 'antd';
import './styles/app.css';
import { AuthStatus, getAuthStatus, unlockVault } from './services/api';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Workspaces = lazy(() => import('./pages/Workspaces'));
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase'));
const Upload = lazy(() => import('./pages/Upload'));
const LearningChat = lazy(() => import('./pages/LearningChat'));
const ReviewCenter = lazy(() => import('./pages/ReviewCenter'));
const Practice = lazy(() => import('./pages/Practice'));
const LearningReport = lazy(() => import('./pages/LearningReport'));
const Settings = lazy(() => import('./pages/Settings'));

const { Sider, Content } = Layout;
const navItems = [
  { key: '/', icon: <HomeOutlined />, label: '今天' },
  { key: '/knowledge', icon: <BookOutlined />, label: '我的知识库' },
  { key: '/learn', icon: <MessageOutlined />, label: 'AI 学习' },
  { key: '/review', icon: <ReadOutlined />, label: '复习中心' },
  { key: '/practice', icon: <TrophyOutlined />, label: '练习与错题' },
  { key: '/report', icon: <BarChartOutlined />, label: '学习报告' },
];
const utilityItems = [
  { key: '/upload', icon: <UploadOutlined />, label: '导入资料' },
  { key: '/settings', icon: <SettingOutlined />, label: '偏好设置' },
];

const Sidebar = ({ navigate }: { navigate: (path: string) => void }) => {
  const location = useLocation();
  const root = '/' + location.pathname.split('/')[1];
  const selected = location.pathname === '/' ? '/' : root === '/workspaces' ? '/knowledge' : root;
  return <div className="app-sidebar-inner">
    <button className="brand" onClick={() => navigate('/')} aria-label="返回今天">
      <span className="brand-mark"><BulbOutlined /></span>
      <span><strong>拾光</strong><small>我的 AI 学习伙伴</small></span>
    </button>
    <div className="nav-label">学习</div>
    <Menu mode="inline" selectedKeys={[selected]} items={navItems} onClick={({ key }) => navigate(key)} />
    <div className="nav-spacer" />
    <div className="nav-label">管理</div>
    <Menu mode="inline" selectedKeys={[selected]} items={utilityItems} onClick={({ key }) => navigate(key)} />
    <div className="profile-chip">
      <Avatar style={{ background: '#dff4f1', color: '#126a76' }}>我</Avatar>
      <span><strong>我的学习空间</strong><small>数据仅保存在你的知识库</small></span>
    </div>
  </div>;
};

const App: React.FC = () => {
  return <ConfigProvider locale={zhCN} theme={{ token: {
    colorPrimary: '#167d8d', colorInfo: '#167d8d', colorSuccess: '#3f8f6b',
    colorWarning: '#d9913b', colorError: '#c9564b', borderRadius: 12,
    fontFamily: '"Noto Sans SC", "Microsoft YaHei", sans-serif', colorText: '#15273b',
  }, components: { Menu: { itemBg: 'transparent', itemSelectedBg: '#e3f3f1', itemSelectedColor: '#126a76', itemBorderRadius: 10 } } }}><AntApp><AppContent /></AntApp></ConfigProvider>;
};

const AppContent: React.FC = () => {
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const [mobileNav, setMobileNav] = useState(false);
  const location = useLocation();
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [unlocking, setUnlocking] = useState(false);
  useEffect(() => setMobileNav(false), [location.pathname]);
  useEffect(() => {
    getAuthStatus().then(status => setAuth(status.enabled && !localStorage.getItem('knowbase_session') ? status : null)).catch(() => setAuth(null));
    const lock = () => { localStorage.removeItem('knowbase_session'); getAuthStatus().then(setAuth); };
    window.addEventListener('knowbase:locked', lock); return () => window.removeEventListener('knowbase:locked', lock);
  }, []);
  const submitUnlock = async () => { if(password.length<8){message.warning('密码至少需要 8 位');return;}setUnlocking(true);try{await unlockVault(password,!auth?.configured,displayName||undefined);setAuth(null);setPassword('');message.success(auth?.configured?'私人知识库已解锁':'私人知识库密码已设置');}catch(e:any){message.error(e?.response?.data?.detail||'无法解锁');}finally{setUnlocking(false);}};
  const unlockScreen = auth ? <div className="vault-screen"><div className="vault-card"><span className="brand-mark" style={{margin:'0 auto 20px'}}><BulbOutlined/></span><Typography.Title className="page-title" level={2}>{auth.configured?'解锁你的私人知识库':'设置私人知识库密码'}</Typography.Title><Typography.Paragraph type="secondary">{auth.configured?'学习资料和记录已经锁好。输入密码后继续。':'准备远程使用前，为自己的资料设置一个至少 8 位的密码。'}</Typography.Paragraph>{!auth.configured&&<Input size="large" placeholder="你的称呼" value={displayName} onChange={e=>setDisplayName(e.target.value)} style={{marginBottom:12}}/>}<Input.Password size="large" placeholder="私人空间密码" value={password} onChange={e=>setPassword(e.target.value)} onPressEnter={submitUnlock}/><Button block type="primary" size="large" loading={unlocking} onClick={submitUnlock} style={{marginTop:16}}>{auth.configured?'解锁':'设置并进入'}</Button><Typography.Text type="secondary" style={{fontSize:12,display:'block',marginTop:18}}>密码只用于保护你的私人空间，请妥善保存。</Typography.Text></div></div> : null;
  return <>{unlockScreen || <Layout className="app-shell">
      <Sider width={244} theme="light" className="desktop-sider"><Sidebar navigate={navigate} /></Sider>
      <Layout className="main-shell">
        <header className="mobile-header">
          <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNav(true)} aria-label="打开导航" />
          <Typography.Text strong>拾光 · 私人知识库</Typography.Text><span />
        </header>
        <Content className="app-content">
          <Suspense fallback={<div style={{padding:80,textAlign:'center'}}><Spin size="large" /></div>}><Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/knowledge" element={<Workspaces />} />
            <Route path="/workspaces" element={<Workspaces />} />
            <Route path="/knowledge/:id" element={<KnowledgeBase />} />
            <Route path="/workspaces/:id/documents" element={<KnowledgeBase />} />
            <Route path="/learn" element={<LearningChat />} />
            <Route path="/review" element={<ReviewCenter />} />
            <Route path="/practice" element={<Practice />} />
            <Route path="/report" element={<LearningReport />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/settings" element={<Settings />} />
          </Routes></Suspense>
        </Content>
      </Layout>
      <Drawer placement="left" width={270} open={mobileNav} onClose={() => setMobileNav(false)} styles={{ body: { padding: 0 } }}><Sidebar navigate={navigate} /></Drawer>
    </Layout>}</>;
};

export default App;

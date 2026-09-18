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
import {
  AuthStatus, CurrentUser, getAuthStatus, getLLMSettings, getMe, loginAccount, logoutAccount,
  setupAccount,
} from './services/api';
import { resolveAuthScreen } from './features/account/authScreen';
import { ModelSetupWizard } from './features/account/ModelSetupWizard';
import {
  isWizardDismissed, rememberWizardDismissed, shouldShowModelWizard,
} from './features/account/setupWizard';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Workspaces = lazy(() => import('./pages/Workspaces'));
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase'));
const DocumentDetail = lazy(() => import('./pages/DocumentDetail'));
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

const Sidebar = ({ navigate, user, onLogout }: {
  navigate: (path: string) => void;
  user: CurrentUser | null;
  onLogout: () => void;
}) => {
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
      <Avatar src={user?.avatar_url || undefined} style={{ background: '#dff4f1', color: '#126a76' }}>
        {(user?.display_name || '我').slice(0, 1)}
      </Avatar>
      <span><strong>{user?.display_name || '我的学习空间'}</strong><small>{user?.username ? `@${user.username}` : '数据仅保存在你的知识库'}</small></span>
      <Button type="text" size="small" onClick={onLogout}>退出</Button>
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
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [bootState, setBootState] = useState<'checking' | 'ready' | 'offline'>('checking');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [freshAccount, setFreshAccount] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  useEffect(() => setMobileNav(false), [location.pathname]);
  const resolveModelWizard = (accountIsFresh: boolean, configured: boolean | null) => {
    setLlmConfigured(configured);
    setFreshAccount(accountIsFresh);
    setWizardOpen(shouldShowModelWizard({
      freshAccount: accountIsFresh,
      configured,
      dismissed: isWizardDismissed(localStorage),
    }));
  };
  const enter = async (isFreshAccount: boolean) => {
    try {
      const settings = await getLLMSettings();
      resolveModelWizard(isFreshAccount, Boolean(settings.configured));
    } catch {
      resolveModelWizard(isFreshAccount, null);
    }
  };
  const bootstrap = () => {
    const hasSession = Boolean(localStorage.getItem('knowbase_session'));
    setBootState('checking');
    if (hasSession) {
      getMe()
        .then(account => { setUser(account); setAuth(null); setBootState('ready'); void enter(false); })
        .catch(() => {
          localStorage.removeItem('knowbase_session');
          getAuthStatus()
            .then(status => { setAuth(status); setBootState('ready'); })
            .catch(() => setBootState('offline'));
        });
    } else {
      getAuthStatus()
        .then(status => { setAuth(status); setBootState('ready'); })
        .catch(() => setBootState('offline'));
    }
  };
  useEffect(() => {
    bootstrap();
    const lock = () => {
      localStorage.removeItem('knowbase_session');
      setUser(null);
      setWizardOpen(false);
      getAuthStatus().then(setAuth).catch(() => setBootState('offline'));
    };
    window.addEventListener('knowbase:locked', lock);
    return () => window.removeEventListener('knowbase:locked', lock);
  }, []);
  const screen = auth ? resolveAuthScreen(auth, false) : 'app';
  const setupMode = screen === 'setup';
  const submit = async () => {
    if (!username.trim()) { message.warning('请填写用户名'); return; }
    if (setupMode && password.length < 8) { message.warning('密码至少需要 8 位'); return; }
    if (!password) { message.warning('请填写密码'); return; }
    setSubmitting(true);
    const isNewAccount = setupMode;
    try {
      const account = setupMode
        ? await setupAccount({ username: username.trim(), password, display_name: displayName.trim() || undefined })
        : await loginAccount({ username: username.trim(), password });
      setUser(account);
      setAuth(null);
      setBootState('ready');
      setPassword('');
      message.success(setupMode ? '账号已创建，欢迎回来' : '已登录');
      await enter(isNewAccount);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      if (error?.response) {
        message.error(detail || (setupMode ? '无法创建账号，请稍后重试' : '用户名或密码错误'));
      } else {
        setBootState('offline');
      }
    } finally {
      setSubmitting(false);
    }
  };
  const handleLogout = async () => {
    try { await logoutAccount(); } catch { /* 本地令牌已清除 */ }
    setUser(null);
    setWizardOpen(false);
    setPassword('');
    getAuthStatus().then(setAuth).catch(() => setAuth(null));
    navigate('/');
    message.success('已退出登录');
  };
  const finishWizard = (result: { configured: boolean }) => {
    if (!result.configured) rememberWizardDismissed(localStorage);
    setLlmConfigured(result.configured);
    setWizardOpen(false);
    if (!result.configured) message.info('已跳过。需要 AI 功能时，可在"偏好设置"里填写你的 API Key。');
  };
  const authScreen = auth ? <div className="vault-screen"><div className="vault-card"><span className="brand-mark" style={{margin:'0 auto 20px'}}><BulbOutlined/></span><Typography.Title className="page-title" level={2}>{setupMode?'创建你的账号':'登录私人知识库'}</Typography.Title><Typography.Paragraph type="secondary">{setupMode?'这个部署只允许创建唯一一个账号，创建后只能登录与退出。':'学习资料和记录只属于这个账号，登录后继续。'}</Typography.Paragraph><Input size="large" placeholder="用户名" value={username} onChange={e=>setUsername(e.target.value)} style={{marginBottom:12}}/>{setupMode&&<Input size="large" placeholder="你的称呼" value={displayName} onChange={e=>setDisplayName(e.target.value)} style={{marginBottom:12}}/>}<Input.Password size="large" placeholder={setupMode?'设置至少 8 位的密码':'密码'} value={password} onChange={e=>setPassword(e.target.value)} onPressEnter={submit}/><Button block type="primary" size="large" loading={submitting} onClick={submit} style={{marginTop:16}}>{setupMode?'创建并进入':'登录'}</Button><Typography.Text type="secondary" style={{fontSize:12,display:'block',marginTop:18}}>{setupMode?'密码使用带随机盐的强哈希保存，服务端不会保存明文。':'忘记密码需要从数据库备份中恢复。'}</Typography.Text></div></div> : null;
  const offlineScreen = bootState === 'offline'
    ? <div className="vault-screen"><div className="vault-card"><span className="brand-mark" style={{margin:'0 auto 20px'}}><BulbOutlined/></span><Typography.Title className="page-title" level={2}>暂时连接不上本地服务</Typography.Title><Typography.Paragraph type="secondary">拾光在你的电脑上运行一个本地服务来保存数据。它可能还没启动，或者正在准备数据（首次升级会先备份数据库，需要稍等一会儿）。</Typography.Paragraph><Button block type="primary" size="large" onClick={bootstrap}>重试</Button><Typography.Text type="secondary" style={{fontSize:12,display:'block',marginTop:18}}>如果一直连不上，请确认本地服务已经启动，然后再次点击重试。</Typography.Text></div></div>
    : null;
  const checkingScreen = bootState === 'checking'
    ? <div className="vault-screen"><Spin size="large" /></div>
    : null;
  const wizardScreen = wizardOpen
    ? <ModelSetupWizard finish={finishWizard} />
    : null;
  return <>{offlineScreen || checkingScreen || wizardScreen || authScreen || <Layout className="app-shell">
      <Sider width={244} theme="light" className="desktop-sider"><Sidebar navigate={navigate} user={user} onLogout={handleLogout} /></Sider>
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
            <Route path="/knowledge/:workspaceId/documents/:documentId" element={<DocumentDetail />} />
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
      <Drawer placement="left" width={270} open={mobileNav} onClose={() => setMobileNav(false)} styles={{ body: { padding: 0 } }}><Sidebar navigate={navigate} user={user} onLogout={handleLogout} /></Drawer>
    </Layout>}</>;
};

export default App;

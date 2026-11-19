import { useMemo, useState, useEffect } from 'react';
import {
  Layout,
  Menu,
  Dropdown,
  Avatar,
  Space,
  Typography,
  Badge,
  Tooltip,
  App,
  theme as antdTheme,
} from 'antd';
import type { MenuProps } from 'antd';
import {
  DashboardOutlined,
  ProjectOutlined,
  BugOutlined,
  CheckSquareOutlined,
  UserOutlined,
  LogoutOutlined,
  BellOutlined,
  KeyOutlined,
  ScheduleOutlined,
  TeamOutlined,
  HomeOutlined,
  ThunderboltOutlined,
  SettingOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  InboxOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/store/auth';
import ChangePasswordModal from '@/components/ChangePasswordModal';
import { http } from '@/api/client';
import { NUM_FONT } from '@/utils/fonts';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

// 角色标签映射
const roleLabels: Record<string, string> = {
  admin: '系统管理员',
  lead_reviewer: '首席评审',
  reviewer: '评审',
  reviewee: '被评审',
};

// 页面标题映射
const pageTitleMap: Record<string, string> = {
  '/dashboard': '综合看板',
  '/msia-plan': 'MSIA计划',
  '/projects': '项目管理',
  '/issues': '问题管理',
  '/workbench': '我的面板',
  '/checklist': '审核标准',
  '/escalation': '问题升级',
  '/archive': '项目存档',
  '/notifications': '通知中心',
  '/system/users': '用户管理',
  '/historic-score': '评分录入',
  '/system/settings': '系统设置',
};

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [pwdModalOpen, setPwdModalOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [currentTime, setCurrentTime] = useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const { message, modal } = App.useApp();
  const { token: themeToken } = antdTheme.useToken();

  // 轮询未读通知数
  useEffect(() => {
    const fetchUnread = async () => {
      try {
        const res = await http.get<{ total: number }>('/notifications', {
          params: { page: 1, page_size: 1, status: 'unread' },
        });
        setUnreadCount(res.total || 0);
      } catch {
        // 静默失败
      }
    };
    fetchUnread();
    const timer = setInterval(fetchUnread, 60000);
    return () => clearInterval(timer);
  }, []);

  // 实时时钟 (科技感数据条)
  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      const y = now.getFullYear();
      const m = String(now.getMonth() + 1).padStart(2, '0');
      const d = String(now.getDate()).padStart(2, '0');
      const h = String(now.getHours()).padStart(2, '0');
      const min = String(now.getMinutes()).padStart(2, '0');
      const s = String(now.getSeconds()).padStart(2, '0');
      setCurrentTime(`${y}-${m}-${d} ${h}:${min}:${s}`);
    };
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, []);

  // 选中当前菜单 - 兼容二级路径 (如 /system/users)
  const selectedKey = useMemo(() => {
    const parts = location.pathname.split('/');
    if (parts[1] === 'system' && parts[2]) return `/system/${parts[2]}`;
    return '/' + (parts[1] || 'dashboard');
  }, [location.pathname]);

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  const handleLogout = () => {
    modal.confirm({
      title: (
        <span style={{ color: '#e6edf7', fontWeight: 700 }}>退出登录确认</span>
      ),
      icon: (
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 42,
            height: 42,
            borderRadius: 12,
            background: 'rgba(255, 77, 79, 0.12)',
            border: '1px solid rgba(255, 77, 79, 0.35)',
            color: '#ff7875',
            fontSize: 20,
            boxShadow: '0 0 0 1px rgba(255, 77, 79, 0.08)',
          }}
        >
          <LogoutOutlined />
        </div>
      ),
      closable: true,
      maskClosable: false,
      centered: true,
      width: 500,
      style: {
        borderRadius: 16,
        overflow: 'hidden',
      },
      styles: {
        body: {
          background: 'linear-gradient(180deg, rgba(13, 20, 34, 0.98) 0%, rgba(20, 31, 48, 0.98) 100%)',
          color: '#e6edf7',
          borderRadius: 16,
          padding: '20px 20px 12px',
        },
      },
      content: (
        <div style={{ lineHeight: 1.75 }}>
          <div style={{ marginBottom: 12, fontWeight: 700, color: '#f5f7fb', fontSize: 16 }}>
            是否确认退出登录？
          </div>
          <div style={{ marginBottom: 12, color: '#b8c3d1' }}>
            当前会话即将结束。若希望在这台设备上继续使用快速登录，可保留本机自动登录状态；若选择清除，则需重新输入账号和密码。
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              padding: '12px 14px',
              borderRadius: 10,
              background: 'rgba(250, 173, 20, 0.08)',
              border: '1px solid rgba(250, 173, 20, 0.28)',
              color: '#f4d38a',
            }}
          >
            <WarningOutlined style={{ color: '#ffd666', marginTop: 2, fontSize: 15 }} />
            <span>
              风险提示：选择“清除本机登录”后，本机自动登录缓存将被清空，下次访问系统必须重新输入账号与密码。
            </span>
          </div>
        </div>
      ),
      okText: '保留本机自动登录',
      cancelText: '清除本机登录并退出',
      okButtonProps: {
        icon: <CheckCircleOutlined />,
        style: {
          background: 'linear-gradient(135deg, #2E5CE6 0%, #0FB5BA 100%)',
          border: 'none',
          color: '#fff',
          boxShadow: '0 8px 20px rgba(46, 92, 230, 0.35)',
          fontWeight: 600,
        },
      },
      cancelButtonProps: {
        danger: true,
        style: {
          background: 'rgba(255, 77, 79, 0.10)',
          borderColor: 'rgba(255, 77, 79, 0.38)',
          color: '#ff7875',
          fontWeight: 600,
        },
      },
      onOk: async () => {
        try {
          await logout(true);
          message.success('已退出登录，已保留本机自动登录');
          navigate('/login', { replace: true });
        } catch {
          message.error('退出登录失败，请稍后重试');
        }
      },
      onCancel: async () => {
        try {
          await logout(false);
          message.success('已退出登录，已清除本机自动登录缓存');
          navigate('/login', { replace: true });
        } catch {
          message.error('退出登录失败，请稍后重试');
        }
      },
    });
  };

  // 侧边菜单 (评分录入已移至"项目管理"页的补录入口, 不再单独占导航位)
  const menuItems: MenuProps['items'] = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '综合看板' },
    { key: '/msia-plan', icon: <ScheduleOutlined />, label: 'MSIA计划' },
    { key: '/projects', icon: <ProjectOutlined />, label: '项目管理' },
    { key: '/issues', icon: <BugOutlined />, label: '问题管理' },
    { key: '/workbench', icon: <HomeOutlined />, label: '我的面板' },
    { key: '/checklist', icon: <CheckSquareOutlined />, label: '审核标准' },
    { key: '/escalation', icon: <ThunderboltOutlined />, label: '问题升级' },
    { key: '/archive', icon: <InboxOutlined />, label: '项目存档' },
    { key: '/system/users', icon: <TeamOutlined />, label: '用户管理' },
    { key: '/system/settings', icon: <SettingOutlined />, label: '系统设置' },
  ];

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'user-info',
      label: (
        <div style={{ padding: '4px 0' }}>
          <div style={{ fontWeight: 600 }}>{user?.DisplayName || user?.Username}</div>
          <div style={{ fontSize: 12, color: themeToken.colorTextSecondary }}>
            {user?.Username} · {roleLabels[user?.Role || 'reviewee']}
          </div>
        </div>
      ),
      disabled: true,
    },
    { type: 'divider' },
    {
      key: 'change-password',
      icon: <KeyOutlined />,
      label: '修改密码',
      onClick: () => setPwdModalOpen(true),
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: () => handleLogout(),
    },
  ];

  const displayName = user?.DisplayName || user?.Username || '用户';
  const isAdmin = user?.Role === 'admin';
  const pageTitle = pageTitleMap[selectedKey] || 'MSIA';

  // 按角色过滤菜单:
  // - 用户管理/系统设置: 仅 admin
  // - 评分补录入口: 在"项目管理"页内, 仅 admin 可见 (路由 /historic-score 保留)
  const filteredMenuItems = menuItems.filter((item) => {
    const key = item?.key;
    if (key === '/system/users') return isAdmin;
    if (key === '/system/settings') return isAdmin;
    return true;
  });

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* ===== 侧边栏: 玻璃拟态 + 科技感渐变 (色调加深, 与内容区拉开对比) ===== */}
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        width={224}
        style={{
          borderRight: '1px solid rgba(46, 92, 230, 0.16)',
          position: 'sticky',
          top: 0,
          height: '100vh',
          overflow: 'auto',
          background:
            'linear-gradient(180deg, #EDF3FD 0%, #DDE9FA 100%)',
          backdropFilter: 'blur(16px) saturate(160%)',
          WebkitBackdropFilter: 'blur(16px) saturate(160%)',
        }}
      >
        {/* Logo 区域: Logo 与系统标题并行, 标题加大 */}
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
            borderBottom: '1px solid rgba(46, 92, 230, 0.12)',
            background: 'linear-gradient(180deg, rgba(46, 92, 230, 0.06) 0%, transparent 100%)',
            position: 'relative',
          }}
        >
          {/* Logo 下方柔光渐变线 */}
          <div
            style={{
              position: 'absolute',
              bottom: 0,
              left: '12%',
              right: '12%',
              height: 1.5,
              borderRadius: 1,
              background: 'linear-gradient(90deg, transparent, rgba(15, 181, 186, 0.55), transparent)',
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <img
              src="/黑线logo透明.png"
              alt="Logo"
              style={{
                height: collapsed ? 30 : 36,
                width: 'auto',
                objectFit: 'contain',
                transition: 'height 0.3s cubic-bezier(0.22, 1, 0.36, 1)',
                filter: 'drop-shadow(0 1px 4px rgba(46, 92, 230, 0.22))',
              }}
            />
            {!collapsed && (
              <span
                style={{
                  fontSize: 19,
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
                  letterSpacing: 1,
                  color: '#1E42B8',
                  textShadow: '0 1px 2px rgba(46, 92, 230, 0.12)',
                  lineHeight: '24px',
                }}
              >
                MSIA 审核系统
              </span>
            )}
          </div>
        </div>

        {/* 菜单 */}
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={filteredMenuItems}
          onClick={handleMenuClick}
          className="tech-sider-menu"
          style={{ borderRight: 0, paddingTop: 8, background: 'transparent' }}
        />

        {/* 侧边栏底部版本信息 */}
        {!collapsed && (
          <div
            style={{
              position: 'absolute',
              bottom: 12,
              left: 0,
              right: 0,
              textAlign: 'center',
              fontSize: 10,
              color: 'rgba(100, 116, 139, 0.5)',
              fontFamily: NUM_FONT,
              letterSpacing: 0.5,
            }}
          >
            v1.0.0 · BUILD 2026
          </div>
        )}
      </Sider>

      <Layout>
        {/* ===== Header: 玻璃拟态 + 科技数据条 ===== */}
        <Header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderBottom: '1px solid rgba(46, 92, 230, 0.08)',
            position: 'sticky',
            top: 0,
            zIndex: 10,
            backdropFilter: 'blur(18px) saturate(180%)',
            WebkitBackdropFilter: 'blur(18px) saturate(180%)',
            background: 'rgba(255, 255, 255, 0.80)',
            boxShadow: '0 1px 3px rgba(27, 46, 116, 0.04)',
          }}
        >
          {/* 左侧: 页面标题 + 状态指示器 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {/* 柔和渐变指示条 */}
            <div
              style={{
                width: 4,
                height: 18,
                borderRadius: 2,
                background: 'linear-gradient(180deg, #2E5CE6 0%, #0FB5BA 100%)',
                boxShadow: '0 2px 8px rgba(46, 92, 230, 0.35)',
              }}
            />
            <Text style={{ fontSize: 15, fontWeight: 600, letterSpacing: 0.3 }}>
              {pageTitle}
            </Text>
            {/* 系统状态徽标 */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                marginLeft: 10,
                padding: '3px 10px',
                borderRadius: 999,
                background: 'rgba(20, 184, 166, 0.07)',
                border: '1px solid rgba(20, 184, 166, 0.22)',
              }}
            >
              <div
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: '50%',
                  background: '#14B8A6',
                  boxShadow: '0 0 6px rgba(20, 184, 166, 0.55)',
                  animation: 'tech-pulse 2.4s ease-in-out infinite',
                }}
              />
              <span
                style={{
                  fontSize: 10,
                  color: '#0D9488',
                  fontWeight: 600,
                  letterSpacing: 0.5,
                  fontFamily: NUM_FONT,
                }}
              >
                ONLINE
              </span>
            </div>
          </div>

          {/* 右侧: 时钟 + 通知 + 用户 */}
          <Space size="large" style={{ alignItems: 'center' }}>
            {/* 实时时钟 */}
            <Tooltip title="系统时间">
              <Text
                style={{
                  fontSize: 12,
                  color: '#5D6B8A',
                  fontFamily: NUM_FONT,
                  letterSpacing: 0.5,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {currentTime}
              </Text>
            </Tooltip>
            {/* 通知铃铛 */}
            <Tooltip title="通知">
              <Badge count={unreadCount} size="small" offset={[-2, 2]}>
                <BellOutlined
                  style={{ fontSize: 17, color: '#5D6B8A', cursor: 'pointer' }}
                  onClick={() => navigate('/notifications')}
                />
              </Badge>
            </Tooltip>
            {/* 用户菜单 */}
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight" trigger={['click']}>
              <Space style={{ cursor: 'pointer' }}>
                <Avatar
                  size="small"
                  icon={<UserOutlined />}
                  style={{
                    backgroundColor: '#2E5CE6',
                    background: 'linear-gradient(135deg, #2E5CE6 0%, #4E7BF0 100%)',
                    boxShadow: '0 2px 8px rgba(46, 92, 230, 0.3)',
                  }}
                />
                <Text style={{ fontSize: 14 }}>{displayName}</Text>
              </Space>
            </Dropdown>
          </Space>
        </Header>

        {/* ===== Content: 柔光氛围背景 ===== */}
        <Content className="msia-content-bg" style={{ margin: 18, minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
      <ChangePasswordModal
        open={pwdModalOpen}
        userId={user?.Id ?? 0}
        onClose={() => setPwdModalOpen(false)}
      />
    </Layout>
  );
}

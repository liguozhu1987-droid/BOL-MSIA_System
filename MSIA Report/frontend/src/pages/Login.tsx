import { useEffect, useState } from 'react';
import { Alert, Card, Form, Input, Button, Typography, App, Divider, Checkbox } from 'antd';
import { UserOutlined, LockOutlined, SafetyOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getAuthConfigApi, redirectToOidcLogin, type AuthConfig } from '@/api/auth';
import { useAuthStore } from '@/store/auth';
import { BRAND } from '@/styles/shared';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text } = Typography;

interface LoginFormValues {
  username: string;
  password: string;
  rememberMe?: boolean;
}

// 登录页: 柔和科技商务风 — 玻璃拟态 + 氛围光斑 + 柔光渐变
export default function Login() {
  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);
  const autoLogin = useAuthStore((state) => state.autoLogin);
  const loadUser = useAuthStore((state) => state.loadUser);
  const token = useAuthStore((state) => state.token);
  const user = useAuthStore((state) => state.user);
  const lastLoginUsername = useAuthStore((state) => state.lastLoginUsername);
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm<LoginFormValues>();
  // 登录配置: OIDC 开关 / 本地登录开关 (拉取前默认显示本地表单, 避免闪烁)
  const [authConfig, setAuthConfig] = useState<AuthConfig>({
    oidc_enabled: false,
    local_login_enabled: true,
  });

  // 拉取登录配置; 失败按 false 处理 (不显示 OIDC 入口, 不显示本地表单)
  useEffect(() => {
    getAuthConfigApi()
      .then(setAuthConfig)
      .catch(() => setAuthConfig({ oidc_enabled: false, local_login_enabled: false }));
  }, []);

  useEffect(() => {
    // 仅在 token 且 user 信息都已就绪时进入看板;
    // 只有 token (如失效残留) 时必须先验证, 验证失败由 401 拦截器清除状态,
    // 避免凭无效 token 跳回看板形成 刷新/重定向 死循环
    if (token && user) {
      navigate('/dashboard', { replace: true });
      return;
    }
    if (token && !user) {
      loadUser().catch(() => {
        // 401 已由拦截器统一清理 token, 保留在登录页
      });
      return;
    }

    // 同一台电脑在未手动退出时，可直接恢复上次登录状态
    autoLogin().then((ok) => {
      if (ok) {
        navigate('/dashboard', { replace: true });
      }
    }).catch(() => {
      // 失败则保留在登录页，用户可手动输入
    });
  }, [autoLogin, loadUser, navigate, token, user]);

  const handleSubmit = async (values: LoginFormValues) => {
    setLoading(true);
    try {
      await login(values.username, values.password, Boolean(values.rememberMe));
      message.success('登录成功');
      navigate('/dashboard', { replace: true });
    } catch {
      // 错误已由响应拦截器统一提示
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        position: 'relative',
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundImage: 'url(/图片123.png)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundRepeat: 'no-repeat',
      }}
    >
      {/* 蒙版层 - 深湖蓝柔和渐变 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(135deg, rgba(30, 70, 192, 0.48) 0%, rgba(15, 37, 88, 0.78) 100%)',
        }}
      />

      {/* 氛围装饰: 柔和光斑 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse 40% 30% at 85% 12%, rgba(15, 181, 186, 0.14) 0%, transparent 65%),' +
            'radial-gradient(ellipse 35% 28% at 10% 85%, rgba(46, 92, 230, 0.16) 0%, transparent 65%)',
        }}
      />

      {/* 氛围装饰: 呼吸光点 */}
      <div
        style={{
          position: 'absolute',
          top: '14%',
          right: '10%',
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: 'rgba(111, 196, 232, 0.9)',
          boxShadow: '0 0 28px rgba(111, 196, 232, 0.55)',
          animation: 'tech-pulse 3.2s ease-in-out infinite',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '20%',
          left: '12%',
          width: 5,
          height: 5,
          borderRadius: '50%',
          background: 'rgba(107, 147, 240, 0.85)',
          boxShadow: '0 0 20px rgba(107, 147, 240, 0.5)',
          animation: 'tech-pulse 4.2s ease-in-out infinite 1s',
        }}
      />

      {/* 登录卡片 */}
      <div style={{ position: 'relative', width: 420, zIndex: 1, animation: 'tech-fade-up 0.6s ease-out' }}>
        {/* 卡片顶部柔光条 */}
        <div
          style={{
            position: 'absolute',
            top: -1,
            left: 24,
            right: 24,
            height: 3,
            borderRadius: '3px 3px 0 0',
            background: `linear-gradient(90deg, transparent 0%, ${BRAND.primaryLight} 30%, ${BRAND.cyan} 50%, ${BRAND.primaryLight} 70%, transparent 100%)`,
            opacity: 0.75,
            filter: 'blur(0.4px)',
          }}
        />

        <Card
          style={{
            width: '100%',
            position: 'relative',
            boxShadow: '0 8px 32px rgba(11, 26, 64, 0.22), 0 24px 64px rgba(11, 26, 64, 0.18), 0 0 0 1px rgba(255, 255, 255, 0.35)',
            backdropFilter: 'blur(18px) saturate(170%)',
            WebkitBackdropFilter: 'blur(18px) saturate(170%)',
            background: 'rgba(255, 255, 255, 0.94)',
            border: 'none',
            borderRadius: 18,
          }}
        >
        {/* Logo 区域 */}
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: 12,
              padding: '9px 22px',
              borderRadius: 12,
              background: `linear-gradient(135deg, rgba(46, 92, 230, 0.07) 0%, rgba(15, 181, 186, 0.05) 100%)`,
              border: '1px solid rgba(46, 92, 230, 0.12)',
            }}
          >
            <img
              src="/黑线logo透明.png"
              alt="MSIA Logo"
              style={{
                height: 48,
                width: 'auto',
                objectFit: 'contain',
                filter: 'drop-shadow(0 2px 6px rgba(46, 92, 230, 0.18))',
              }}
            />
          </div>
          <Title level={3} style={{ marginBottom: 4, color: '#1B2540', letterSpacing: 0.5 }}>
            MSIA 审核管理系统
          </Title>
          <Text type="secondary" style={{ fontSize: 12, letterSpacing: 1.2, fontFamily: NUM_FONT }}>
            MANUFACTURING SYSTEM IMPLEMENTATION AUDIT
          </Text>
        </div>

        {/* 统一身份登录 (OIDC): 仅后端开启时展示, 点击 302 到 Keycloak 授权页 */}
        {authConfig.oidc_enabled && (
          <Button
            type="primary"
            size="large"
            block
            icon={<SafetyOutlined />}
            onClick={redirectToOidcLogin}
            style={{
              fontWeight: 500,
              height: 44,
              borderRadius: 10,
              background: `linear-gradient(135deg, ${BRAND.primary} 0%, ${BRAND.cyan} 100%)`,
              border: 'none',
              boxShadow: '0 6px 20px rgba(46, 92, 230, 0.32)',
              letterSpacing: 4,
            }}
          >
            统一身份登录
          </Button>
        )}

        {/* 本地登录分隔提示: 双轨过渡期标注 (OIDC 开启且本地表单可见时才出现,
            避免 P4 单轨期"过渡期"标签与"已关闭"提示并存造成歧义) */}
        {authConfig.oidc_enabled && authConfig.local_login_enabled && (
          <Divider style={{ margin: '12px 0', borderColor: 'rgba(46, 92, 230, 0.10)' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              本地登录（过渡期）
            </Text>
          </Divider>
        )}

        {/* 本地登录表单: P4 单轨期 (local_login_enabled=false) 隐藏并提示走统一登录 */}
        {authConfig.local_login_enabled ? (
          <Form
            form={form}
            layout="vertical"
            onFinish={handleSubmit}
            autoComplete="off"
            requiredMark={false}
            initialValues={{ username: lastLoginUsername || '', rememberMe: true }}
          >
            <Form.Item
              name="username"
              label="用户名"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input
                prefix={<UserOutlined style={{ color: '#94A3B8' }} />}
                placeholder="请输入用户名"
                size="large"
                style={{ borderRadius: 10 }}
              />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                prefix={<LockOutlined style={{ color: '#94A3B8' }} />}
                placeholder="请输入密码"
                size="large"
                style={{ borderRadius: 10 }}
              />
            </Form.Item>
            <Form.Item name="rememberMe" valuePropName="checked" style={{ marginBottom: 12 }}>
              <Checkbox>下次在这台电脑上自动登录</Checkbox>
            </Form.Item>
            <Form.Item style={{ marginBottom: 16 }}>
              <Button
                type="primary"
                htmlType="submit"
                block
                size="large"
                loading={loading}
                style={{
                  fontWeight: 500,
                  height: 44,
                  borderRadius: 10,
                  background: `linear-gradient(135deg, ${BRAND.primary} 0%, ${BRAND.cyan} 100%)`,
                  border: 'none',
                  boxShadow: '0 6px 20px rgba(46, 92, 230, 0.32)',
                  letterSpacing: 4,
                }}
              >
                登 录
              </Button>
            </Form.Item>
          </Form>
        ) : (
          <Alert
            type="warning"
            showIcon
            message="本地登录已关闭，请使用统一身份登录"
            style={{ marginBottom: 16, borderRadius: 10 }}
          />
        )}

        <Divider style={{ margin: '12px 0', borderColor: 'rgba(46, 92, 230, 0.10)' }} />

        <div
          style={{
            textAlign: 'center',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
          }}
        >
          <SafetyOutlined style={{ color: '#94A3B8', fontSize: 12 }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            初始密码: Inalfa2026 · 请登录后及时修改
          </Text>
        </div>
        </Card>
      </div>
    </div>
  );
}

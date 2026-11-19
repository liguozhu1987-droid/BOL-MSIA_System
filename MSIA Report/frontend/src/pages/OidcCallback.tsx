import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { App, Button, Card, Result, Spin, Typography } from 'antd';
import { useAuthStore } from '@/store/auth';

const { Text } = Typography;

// OIDC 回调页: 后端 302 到此 (/oidc/callback?otk=... 一次性码 或 ?error=... 失败原因)
//   error → 展示失败原因 + 返回登录页链接
//   otk   → 一次性码换本地 JWT → 进看板 (失败给出重试入口)
//   都无  → 直接回登录页
export default function OidcCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const loginWithOtk = useAuthStore((state) => state.loginWithOtk);
  const { message } = App.useApp();
  // 取字符串值作为 effect 依赖 (searchParams 对象每次渲染都是新实例,
  // 直接作为依赖会导致 effect 重复执行 — otk 单次消费, 第二次必然失败)
  const otk = searchParams.get('otk');
  const error = searchParams.get('error');
  const [errorText, setErrorText] = useState<string | null>(null);
  const [exchanging, setExchanging] = useState(false);

  useEffect(() => {
    if (error) {
      setErrorText(error);
      return;
    }
    if (!otk) {
      navigate('/login', { replace: true });
      return;
    }

    setExchanging(true);
    loginWithOtk(otk)
      .then(() => {
        message.success('登录成功');
        navigate('/dashboard', { replace: true });
      })
      .catch(() => {
        // 具体错误已由响应拦截器统一提示, 这里补充重试入口
        setErrorText('登录凭证无效或已过期，请返回登录页重新登录');
      })
      .finally(() => setExchanging(false));
  }, [otk, error, loginWithOtk, navigate, message]);

  // 失败态: 展示原因 + 返回登录页
  if (errorText) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#F5F7FB',
        }}
      >
        <Card style={{ width: 440, borderRadius: 16, boxShadow: '0 8px 32px rgba(11, 26, 64, 0.12)' }}>
          <Result
            status="warning"
            title="统一登录失败"
            subTitle={errorText}
            extra={
              <Link to="/login">
                <Button type="primary">返回登录页</Button>
              </Link>
            }
          />
        </Card>
      </div>
    );
  }

  // 处理中:  spinner + 提示
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#F5F7FB',
      }}
    >
      <Card
        style={{
          width: 360,
          borderRadius: 16,
          textAlign: 'center',
          boxShadow: '0 8px 32px rgba(11, 26, 64, 0.12)',
        }}
      >
        <Spin size="large" style={{ marginBottom: 16 }} />
        <div>
          <Text type="secondary">正在完成统一登录，请稍候…</Text>
        </div>
      </Card>
    </div>
  );
}

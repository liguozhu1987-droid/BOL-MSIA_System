import { useEffect } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { App, Spin } from 'antd';
import { useAuthStore } from '@/store/auth';

// 受保护路由：
// - 无 token 时跳转登录页
// - token 存在但 user 为 null 时 (页面刷新), 自动调用 loadUser 恢复用户信息
// - token 失效时, 后端返回 401, 响应拦截器自动跳转登录页
export default function AuthRoute() {
  const token = useAuthStore((state) => state.token);
  const user = useAuthStore((state) => state.user);
  const loading = useAuthStore((state) => state.loading);
  const loadUser = useAuthStore((state) => state.loadUser);
  const { message } = App.useApp();

  useEffect(() => {
    if (!token) {
      message.warning('请先登录');
      return;
    }
    // token 存在但 user 为 null (页面刷新后从 localStorage 恢复 token, 但 user 未持久化)
    // 自动拉取用户信息, 实现登录保持
    if (token && !user && !loading) {
      loadUser().catch(() => {
        // 401 错误由响应拦截器统一处理 (跳转登录页)
      });
    }
  }, [token, user, loading, loadUser, message]);

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  // token 存在但 user 还在加载中, 显示全屏 Loading
  if (token && !user && loading) {
    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(240, 245, 250, 0.8)',
          backdropFilter: 'blur(4px)',
        }}
      >
        <Spin size="large" tip="正在恢复登录会话...">
          <div style={{ padding: 8 }} />
        </Spin>
      </div>
    );
  }

  return <Outlet />;
}

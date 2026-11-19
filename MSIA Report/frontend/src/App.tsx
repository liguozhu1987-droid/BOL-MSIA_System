import { useEffect } from 'react';
import { RouterProvider } from 'react-router-dom';
import { App as AntdApp } from 'antd';
import { router } from './router';
import { setAppMessage } from '@/utils/appMessage';

// 将 antd App 上下文的 message 实例同步到模块级持有者,
// 供非 React 模块 (axios 拦截器) 调用, 消除静态方法无法消费主题上下文的警告
function AppMessageBridge() {
  const { message } = AntdApp.useApp();
  useEffect(() => {
    setAppMessage(message);
  }, [message]);
  return null;
}

// 应用根组件：使用 antd App 包装, 让 message/notification/modal 等静态方法
// 能消费动态主题上下文 (消除 "Static function can not consume context" 警告)
export default function App() {
  return (
    <AntdApp>
      <AppMessageBridge />
      <RouterProvider router={router} />
    </AntdApp>
  );
}

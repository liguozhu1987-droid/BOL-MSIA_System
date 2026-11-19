import type { MessageInstance } from 'antd/es/message/interface';

// antd App 上下文 message 实例持有者
// 供非 React 模块 (如 axios 拦截器) 使用上下文版 message,
// 消除 antd "Static function can not consume context like dynamic theme" 警告
let instance: MessageInstance | null = null;

export const setAppMessage = (api: MessageInstance): void => {
  instance = api;
};

export const getAppMessage = (): MessageInstance | null => instance;

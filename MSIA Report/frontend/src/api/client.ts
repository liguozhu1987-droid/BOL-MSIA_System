import axios, { AxiosError, AxiosRequestConfig } from 'axios';
import { getAppMessage } from '@/utils/appMessage';

// 模块级 token 持有者，避免与 auth store 产生循环依赖
let authToken: string | null = null;

// 401 未授权回调（由 auth store 注册，用于清理持久化登录状态）
let onUnauthorized: (() => void) | null = null;

export const setOnUnauthorized = (cb: (() => void) | null) => {
  onUnauthorized = cb;
};

// 由 auth store 调用以同步 token
export const setAuthToken = (token: string | null) => {
  authToken = token;
};

// Axios 实例：baseURL = /api
// 默认超时 60s (HRDB 跨库查询可能较慢, 30s 在数据量大时会超时)
const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器：附加 Bearer token
client.interceptors.request.use(
  (config) => {
    if (authToken) {
      config.headers.Authorization = `Bearer ${authToken}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器：401 跳转登录，统一解包 response.data
client.interceptors.response.use(
  (response) => response.data,
  (error: AxiosError<{ message?: string }>) => {
    const status = error.response?.status;
    if (status === 401) {
      authToken = null;
      // 同步清理持久化登录状态 (token/user), 否则失效 token 会残留在
      // localStorage, 登录页据此跳回看板 → 再次 401 → 整页刷新死循环
      onUnauthorized?.();
      // 登录接口自身的 401 (自动登录密码已失效) 不提示, 由调用方静默处理
      const isLoginRequest = error.config?.url?.includes('/auth/login');
      if (!isLoginRequest) {
        getAppMessage()?.error('登录已过期，请重新登录');
      }
      // 跳转登录页并避免重复刷新 (replace 防止历史记录堆积)
      if (window.location.pathname !== '/login') {
        window.location.replace('/login');
      }
    } else {
      const data = error.response?.data as { detail?: string; message?: string } | undefined;
      const msg = data?.detail || data?.message || error.message || '请求失败';
      getAppMessage()?.error(msg);
    }
    return Promise.reject(error);
  }
);

// 类型化封装：因为响应拦截器已解包 response.data，这里做类型断言
export const http = {
  get: <T = unknown>(url: string, config?: AxiosRequestConfig) =>
    client.get(url, config) as unknown as Promise<T>,
  post: <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.post(url, data, config) as unknown as Promise<T>,
  put: <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.put(url, data, config) as unknown as Promise<T>,
  patch: <T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.patch(url, data, config) as unknown as Promise<T>,
  delete: <T = unknown>(url: string, config?: AxiosRequestConfig) =>
    client.delete(url, config) as unknown as Promise<T>,
};

export default client;

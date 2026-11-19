import { http } from './client';

// 用户信息 (与后端 UserOut 模型一致, PascalCase)
export interface User {
  Id: number;
  Username: string;
  DisplayName: string | null;
  Email: string | null;
  Phone: string | null;
  Department: string | null;
  Role: string;
  Status: number;
}

// 登录响应 (与后端 TokenResponse 一致)
export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

// 登录页配置 (后端 GET /api/auth/config, 公开)
export interface AuthConfig {
  oidc_enabled: boolean;
  local_login_enabled: boolean;
}

// 获取登录配置 (OIDC 开关 / 本地登录开关)
export function getAuthConfigApi(): Promise<AuthConfig> {
  return http.get<AuthConfig>('/auth/config');
}

// 跳转后端发起 OIDC 授权 (后端 302 到 Keycloak 登录页)
export function redirectToOidcLogin(): void {
  window.location.href = '/api/auth/oidc/login';
}

// OIDC 回调: 用一次性码 (otk) 换本地 JWT, 响应结构与本地登录一致
export function exchangeOtkApi(otk: string): Promise<LoginResponse> {
  return http.post<LoginResponse>('/auth/oidc/token', { otk });
}

// 登录
export function loginApi(username: string, password: string): Promise<LoginResponse> {
  return http.post<LoginResponse>('/auth/login', { username, password });
}

// 登出
export function logoutApi(): Promise<void> {
  return http.post<void>('/auth/logout');
}

// 获取当前登录用户
export function getMeApi(): Promise<User> {
  return http.get<User>('/auth/me');
}

// 修改自己的密码
export function changePasswordApi(userId: number, oldPassword: string, newPassword: string): Promise<void> {
  return http.put<void>(`/users/${userId}/password`, {
    old_password: oldPassword,
    new_password: newPassword,
  });
}

// 管理员重置密码
export function resetPasswordApi(userId: number, newPassword: string): Promise<void> {
  return http.post<void>(`/users/${userId}/reset-password`, {
    new_password: newPassword,
  });
}

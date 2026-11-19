import { http } from './client';

// 用户扩展信息（含同步信息和密码状态）
export interface UserExtended {
  Id: number;
  Username: string;
  DisplayName: string | null;
  Email: string | null;
  Phone: string | null;
  Department: string | null;
  Role: string;
  Status: number;
  HrSyncedAt: string | null;
  PasswordUpdatedAt: string | null;
  IsDeleted: boolean;
  CreatedAt: string | null;
  UpdatedAt: string | null;
  HasPassword: boolean;
}

// 分页响应
export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 获取用户列表
export function listUsersApi(params: {
  page?: number;
  page_size?: number;
  keyword?: string;
}): Promise<PageResponse<UserExtended>> {
  return http.get<PageResponse<UserExtended>>('/users', { params });
}

// 获取用户详情
export function getUserDetailApi(userId: number): Promise<UserExtended> {
  return http.get<UserExtended>(`/users/${userId}/detail`);
}

// 切换用户状态
export function toggleUserStatusApi(userId: number, status: number): Promise<void> {
  return http.patch<void>(`/users/${userId}/status`, { Status: status });
}

// 修改用户角色
export function updateUserRoleApi(userId: number, role: string): Promise<void> {
  return http.put<void>(`/users/${userId}/role`, { role });
}

// 管理员重置密码
export function resetPasswordApi(userId: number, newPassword: string): Promise<void> {
  return http.post<void>(`/users/${userId}/reset-password`, {
    new_password: newPassword,
  });
}

// 手动触发用户同步
export function triggerUserSyncApi(): Promise<{ message: string }> {
  return http.post<{ message: string }>('/admin/user-sync/run');
}

// 获取用户同步日志
export function getUserSyncLogsApi(params: {
  page?: number;
  page_size?: number;
}): Promise<PageResponse<Record<string, unknown>>> {
  return http.get<PageResponse<Record<string, unknown>>>('/admin/user-sync/logs', { params });
}

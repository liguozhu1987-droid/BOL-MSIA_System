// 系统设置 API
import { http } from './client';

// 通知模式响应
export interface NotificationMode {
  mode: 'test' | 'production';
  test_recipients: string;
  is_test_mode: boolean;
  description: string;
}

// 通知模式更新请求
export interface NotificationModeUpdate {
  mode: 'test' | 'production';
  test_recipients?: string;
}

// 系统设置项 (单个)
export interface SystemSettingItem {
  key: string;
  value: string | null;
  display_name: string | null;
  description: string | null;
  module: string | null;
  value_type: string | null;
  sort_order: number | null;
  updated_at: string | null;
  updated_by: number | null;
}

// 按功能模块分组的设置
export interface SettingGroup {
  module: string;
  module_name: string;
  settings: SystemSettingItem[];
}

// 批量更新单项
export interface BatchUpdateItem {
  key: string;
  value: string;
}

// 批量更新请求
export interface BatchUpdateRequest {
  items: BatchUpdateItem[];
}

// 批量更新结果
export interface BatchUpdateResult {
  updated: number;
  skipped: number;
}

// 查询当前通知模式
export function getNotificationMode(): Promise<NotificationMode> {
  return http.get<NotificationMode>('/system-settings/notification-mode');
}

// 更新通知模式
export function updateNotificationMode(payload: NotificationModeUpdate): Promise<NotificationMode> {
  return http.put<NotificationMode>('/system-settings/notification-mode', payload);
}

// 查询全部系统设置 (平铺列表)
export function listSystemSettings(): Promise<SystemSettingItem[]> {
  return http.get<SystemSettingItem[]>('/system-settings');
}

// 按功能模块分组查询系统设置
export function listSettingsGrouped(): Promise<SettingGroup[]> {
  return http.get<SettingGroup[]>('/system-settings/grouped');
}

// 批量更新系统设置
export function batchUpdateSettings(payload: BatchUpdateRequest): Promise<BatchUpdateResult> {
  return http.put<BatchUpdateResult>('/system-settings/batch', payload);
}

// 初始化默认配置 (首次部署或升级后调用)
export function initSystemSettings(): Promise<{ message: string; inserted: number }> {
  return http.post<{ message: string; inserted: number }>('/system-settings/init');
}

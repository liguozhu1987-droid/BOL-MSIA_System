import { http } from './client';

// 通知类型
export type NotificationType = 'info' | 'warning' | 'error' | 'success';

// 通知实体
export interface Notification {
  id: number;
  title: string;
  content: string;
  type: NotificationType;
  read: boolean;
  createdAt: string;
}

// 列表响应
export interface NotificationListResponse {
  list: Notification[];
  total: number;
  unread: number;
}

// 获取通知列表
export function getNotifications(params: {
  page?: number;
  pageSize?: number;
}): Promise<NotificationListResponse> {
  return http.get<NotificationListResponse>('/notifications', { params });
}

// 标记单条通知为已读
export function markNotificationRead(id: number): Promise<void> {
  return http.patch<void>(`/notifications/${id}/read`);
}

// 标记全部通知为已读
export function markAllNotificationsRead(): Promise<void> {
  return http.post<void>('/notifications/read-all');
}

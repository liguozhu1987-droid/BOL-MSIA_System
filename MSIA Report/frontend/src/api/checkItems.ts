import { http } from './client';

// 检查项评分选项 (JSON 字段反序列化后)
export interface ScoreOption {
  score: number;
  label: string;
  desc: string;
}

// 检查项实体 (与后端 CheckItem 对齐, 字段为 PascalCase)
export interface CheckItem {
  Id: number;
  PhaseCode: string;
  ItemNo: string;
  Name: string;
  Request?: string | null;
  RequestDescription?: string | null;
  IsKeyItem: boolean;
  ReviewerRoles?: string | null;
  ReferenceDocuments?: string | null;
  ScoreScaleType: string;
  ScoreOptions?: string | null; // JSON 文本
  DefaultResultText?: string | null;
  Version?: number;
  Remarks?: string | null;
  /** 启用/停用开关 (默认 true=启用); 停用后不进入项目评审打分场景 */
  IsActive?: boolean;
  IsDeleted?: boolean;
  CreatedAt?: string | null;
  UpdatedAt?: string | null;
}

// 新建/更新检查项的 payload (ScoreOptions 为数组, 后端自动转 JSON)
export interface CheckItemPayload {
  PhaseCode: string;
  ItemNo: string;
  Name: string;
  Request?: string | null;
  RequestDescription?: string | null;
  IsKeyItem: boolean;
  ReviewerRoles?: string | null;
  ReferenceDocuments?: string | null;
  ScoreScaleType: string;
  ScoreOptions: ScoreOption[];
  DefaultResultText?: string | null;
  Remarks?: string | null;
}

// 列表查询参数
export interface CheckItemListParams {
  phase_code?: string;
}

// 解析 ScoreOptions JSON
export function parseScoreOptions(raw?: string | null): ScoreOption[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed as ScoreOption[];
  } catch {
    // ignore parse error
  }
  return [];
}

// 检查项列表 (可按 PhaseCode 过滤)
export function getCheckItems(params?: CheckItemListParams): Promise<CheckItem[]> {
  return http.get<CheckItem[]>('/check-items', { params });
}

// 检查项详情
export function getCheckItem(id: number): Promise<CheckItem> {
  return http.get<CheckItem>(`/check-items/${id}`);
}

// 新建检查项
export function createCheckItem(data: CheckItemPayload): Promise<CheckItem> {
  return http.post<CheckItem>('/check-items', data);
}

// 更新检查项
export function updateCheckItem(id: number, data: Partial<CheckItemPayload>): Promise<CheckItem> {
  return http.put<CheckItem>(`/check-items/${id}`, data);
}

// 删除检查项 (软删)
export function deleteCheckItem(id: number): Promise<void> {
  return http.delete<void>(`/check-items/${id}`);
}

// 启用/停用检查项 (停用后不进入项目评审打分场景)
export function toggleCheckItemActive(id: number, isActive: boolean): Promise<CheckItem> {
  return http.patch<CheckItem>(`/check-items/${id}/active`, { IsActive: isActive });
}

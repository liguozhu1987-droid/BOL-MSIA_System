import { http } from './client';
import type { PageResponse } from './issues';

// 升级配置 (与后端 EscalationConfigOut 对齐, PascalCase)
export interface EscalationConfig {
  Id: number;
  Plant: string;
  Severity: 'H' | 'M' | 'L' | string;
  Level1Hours: number;
  Level2Hours: number;
  Level3Hours: number;
  Level1Recipients?: string | null;
  Level2Recipients?: string | null;
  Level3Recipients?: string | null;
  IsEnabled: boolean;
  Remarks?: string | null;
  CreatedBy?: number | null;
  CreatedAt?: string | null;
  UpdatedAt?: string | null;
}

export interface EscalationConfigCreatePayload {
  Plant: string;
  Severity: 'H' | 'M' | 'L';
  Level1Hours: number;
  Level2Hours: number;
  Level3Hours: number;
  Level1Recipients?: string | null;
  Level2Recipients?: string | null;
  Level3Recipients?: string | null;
  IsEnabled?: boolean;
  Remarks?: string | null;
}

export interface EscalationConfigUpdatePayload {
  Plant?: string;
  Severity?: 'H' | 'M' | 'L';
  Level1Hours?: number;
  Level2Hours?: number;
  Level3Hours?: number;
  Level1Recipients?: string | null;
  Level2Recipients?: string | null;
  Level3Recipients?: string | null;
  IsEnabled?: boolean;
  Remarks?: string | null;
}

// 升级日志 (与后端 EscalationLogOut 对齐)
export interface EscalationLog {
  Id: number;
  IssueId: number;
  ConfigId?: number | null;
  Level: 1 | 2 | 3 | number;
  RemindCount?: number | null;
  // 实际发送邮箱 (测试模式下为重定向后的测试邮箱)
  Recipients: string;
  // 原始收件人 (测试模式重定向前; 生产模式下与 Recipients 相同)
  OriginalRecipients?: string | null;
  EmailLogId?: number | null;
  SentAt: string;
  // 扩展字段
  IssueNo?: string | null;
  IssueTitle?: string | null;
  Plant?: string | null;
  Severity?: string | null;
  OwnerName?: string | null;
  ProjectName?: string | null;
}

export interface EscalationLogStats {
  total: number;
  level1_count: number;
  level2_count: number;
  level3_count: number;
  last_24h_count: number;
}

export interface EscalationConfigListParams {
  page?: number;
  page_size?: number;
  plant?: string;
  severity?: string;
  enabled?: boolean;
}

export interface EscalationLogListParams {
  page?: number;
  page_size?: number;
  issue_id?: number;
  level?: number;
  plant?: string;
  owner_name?: string;
  project_name?: string;
}

// 升级日志筛选选项 (责任人 / 项目)
export interface EscalationLogFilters {
  owners: Array<{ value: string; label: string }>;
  projects: Array<{ value: string; label: string }>;
}

// ============ 配置 CRUD ============

export const listEscalationConfigsApi = (params: EscalationConfigListParams = {}) =>
  http.get<PageResponse<EscalationConfig>>('/escalation/configs', { params });

export const listAllEscalationConfigsApi = () =>
  http.get<EscalationConfig[]>('/escalation/configs/all');

export const createEscalationConfigApi = (payload: EscalationConfigCreatePayload) =>
  http.post<EscalationConfig>('/escalation/configs', payload);

export const updateEscalationConfigApi = (id: number, payload: EscalationConfigUpdatePayload) =>
  http.put<EscalationConfig>(`/escalation/configs/${id}`, payload);

export const deleteEscalationConfigApi = (id: number) =>
  http.delete<{ message: string }>(`/escalation/configs/${id}`);

export const toggleEscalationConfigApi = (id: number) =>
  http.post<EscalationConfig>(`/escalation/configs/${id}/toggle`);

// ============ 日志查询 ============

export const listEscalationLogsApi = (params: EscalationLogListParams = {}) =>
  http.get<PageResponse<EscalationLog>>('/escalation/logs', { params });

export const getEscalationLogStatsApi = () =>
  http.get<EscalationLogStats>('/escalation/logs/stats');

export const getEscalationLogFiltersApi = () =>
  http.get<EscalationLogFilters>('/escalation/logs/filters');

// ============ 工厂列表 ============

export const listEscalationPlantsApi = () =>
  http.get<string[]>('/escalation/plants');

// ============ 手动触发扫描 ============

export const triggerEscalationScanApi = () =>
  http.post<{ ok: boolean; result: { scanned: number; sent: number; skipped: number } }>(
    '/escalation/scan'
  );

// ============ 测试邮件连通性 ============

export interface TestEmailResponse {
  ok: boolean;
  message: string;
  smtp_host: string;
  smtp_port: number;
  from_address: string;
  log_id?: number | null;
  error?: string | null;
}

export const sendTestEmailApi = (recipient: string) =>
  http.post<TestEmailResponse>('/escalation/test-email', { recipient });

// ============ 用户下拉选项（升级配置收件人选择用） ============

export interface UserOption {
  Id: number;
  Username: string;
  DisplayName: string | null;
  Email: string | null;
  Department: string | null;
}

/**
 * 获取全部用户选项（不分页，用于下拉多选）
 * @param keyword 可选搜索关键词（姓名/用户名/邮箱/部门）
 * @param includeDisabled 是否包含禁用用户（默认仅启用用户）
 */
export const listUserOptionsApi = (params?: {
  keyword?: string;
  include_disabled?: boolean;
}) =>
  http.get<UserOption[]>('/users/options/all', { params });

// ============ 工厂代码常量 (与 HRDB location 字段关联) ============

export interface PlantOption {
  code: string;
  name: string;
  fullName: string;
}

// 系统内使用的工厂代码 (与 HRDB.location 对应)
export const PLANT_OPTIONS: PlantOption[] = [
  { code: 'CC', name: '长春', fullName: '长春工厂 (Changchun)' },
  { code: 'BJ', name: '北京', fullName: '北京工厂 (Beijing)' },
  { code: 'SH', name: '上海', fullName: '上海工厂 (Shanghai)' },
  { code: 'WH', name: '武汉', fullName: '武汉工厂 (Wuhan)' },
  { code: 'CQ', name: '重庆', fullName: '重庆工厂 (Chongqing)' },
  { code: 'GZ', name: '广州', fullName: '广州工厂 (Guangzhou)' },
];

export const PLANT_CODE_MAP: Record<string, PlantOption> = PLANT_OPTIONS.reduce(
  (acc, opt) => {
    acc[opt.code] = opt;
    return acc;
  },
  {} as Record<string, PlantOption>
);

// 根据 Plant 字符串获取显示名称 (兼容旧数据的中文名与新代码)
export const getPlantDisplayName = (plant: string | null | undefined): string => {
  if (!plant) return '—';
  if (plant === '*') return '全局 (兜底)';
  const opt = PLANT_CODE_MAP[plant];
  return opt ? `${plant} ${opt.name}` : plant;
};

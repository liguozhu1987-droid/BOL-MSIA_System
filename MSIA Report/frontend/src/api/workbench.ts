// 我的工作台 API 客户端
import { http } from './client';
import type { Issue, PageResponse } from './issues';

// ============ 类型定义 ============

// 阶段评审汇总
export interface PhaseSummary {
  phase: string;        // MSIA1~MSIA5
  phase_num: number;    // 1~5
  avg_score: number | null;    // 平均分 (0~1)
  avg_percent: number | null;  // 百分比 (0~100)
  item_count: number;   // 评审项数
}

// 我的项目项
export interface MyProjectItem {
  planId: number;
  orderId: string | null;
  projectName: string | null;
  order_description: string | null;
  lineType: string | null;
  ownerName: string | null;
  leadUser: string | null;
  plantName: string | null;
  lineName: string | null;
  issueDate: string | null;
  endDate: string | null;
  phases: PhaseSummary[];
  overall_avg_score: number | null;
  overall_avg_percent: number | null;
  issue_count: number;
}

// 工作台问题更新 payload
export interface WorkbenchUpdatePayload {
  RootCause?: string | null;
  CorrectiveAction?: string | null;
  PlannedCloseDate?: string | null;
  OwnerName?: string | null;
  OwnerDepartment?: string | null;
}

// 关闭申请 payload
export interface ClosureRequestPayload {
  VerificationComments?: string | null;
}

// 关闭审批 payload
export interface ClosureApprovalPayload {
  Approved: boolean;
  VerificationComments?: string | null;
}

// ============ API 函数 ============

// 我的项目库
export function getMyProjectsApi(): Promise<MyProjectItem[]> {
  return http.get<MyProjectItem[]>('/workbench/my-projects');
}

// 我的审核问题列表
export function getMyIssuesApi(params: {
  plan_id?: string;
  phase_code?: string;
  status?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<PageResponse<Issue>> {
  return http.get<PageResponse<Issue>>('/workbench/my-issues', { params });
}

// 审核问题列表筛选选项 (项目)
export interface MyIssueFilters {
  projects: Array<{ value: string; label: string }>;
}

export function getMyIssueFiltersApi(): Promise<MyIssueFilters> {
  return http.get<MyIssueFilters>('/workbench/my-issues/filters');
}

// 待关闭审批列表 (admin/lead_reviewer)
export function getPendingClosuresApi(params: {
  phase_code?: string;
  page?: number;
  page_size?: number;
}): Promise<PageResponse<Issue>> {
  return http.get<PageResponse<Issue>>('/workbench/pending-closures', { params });
}

// 工作台更新问题
export function workbenchUpdateIssueApi(
  issueId: number,
  payload: WorkbenchUpdatePayload,
): Promise<{ ok: boolean; id: number; changed: string[] }> {
  return http.put(`/workbench/issues/${issueId}/workbench-update`, payload);
}

// 申请关闭问题
export function requestClosureApi(
  issueId: number,
  payload: ClosureRequestPayload = {},
): Promise<{ ok: boolean; id: number; status: string }> {
  return http.post(`/workbench/issues/${issueId}/request-closure`, payload);
}

// 审批关闭申请 (admin/lead_reviewer)
export function approveClosureApi(
  issueId: number,
  payload: ClosureApprovalPayload,
): Promise<{ ok: boolean; id: number; status: string; message: string }> {
  return http.post(`/workbench/issues/${issueId}/approve-closure`, payload);
}

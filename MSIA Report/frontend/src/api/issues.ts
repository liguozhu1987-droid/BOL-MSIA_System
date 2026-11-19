import { http, default as apiClient } from './client';

// 问题状态: open / in_progress / pending_verification / closed
export type IssueStatus = 'open' | 'in_progress' | 'pending_verification' | 'closed';
// 问题优先级: high / medium / low
export type IssuePriority = 'high' | 'medium' | 'low';
// 严重等级: H / M / L
export type IssueSeverity = 'H' | 'M' | 'L';

// 审核证据附件 (与后端 AttachmentOut 对齐)
export interface IssueAttachment {
  Id: number;
  OwnerType: string;
  OwnerId: number;
  FileName: string;
  FileExtension?: string | null;
  FileSize?: number | null;
  MimeType?: string | null;
  UploadedBy?: number | null;
  CreatedAt?: string | null;
}

// 问题实体 (与后端 IssueOut 对齐, 字段为 PascalCase)
export interface Issue {
  Id: number;
  ProjectId?: number | null;
  PhaseId?: number | null;
  ItemId?: number | null;
  PhaseReviewItemId?: number | null;
  PlanId?: string | null;
  PhaseCode?: string | null;
  ItemNo?: string | null;
  // 项目名称 (后端从 HRDB 注入; 无关联项目时为空字符串)
  ProjectName?: string | null;
  // 检查项名称 (后端注入, 便于定位评分条款)
  ItemName?: string | null;
  IssueNo: string;
  Title: string;
  Description?: string | null;
  OwnerUserId?: number | null;
  // 责任人英文账号 (来自 HRDB userName_in_charge, 用于与当前登录用户 Username 匹配)
  OwnerUserName?: string | null;
  OwnerName?: string | null;
  OwnerCompany?: string | null;
  OwnerDepartment?: string | null;
  Priority: IssuePriority | string;
  Severity: IssueSeverity | string;
  // 整改完成日期 (Deadline): 阶段实际审核完成日期 + 10 自然日, 逾期判定硬边界
  Deadline?: string | null;
  DeadlineIsManual?: boolean;
  Status: IssueStatus | string;
  ClosingStatus?: string | null;
  VerificationComments?: string | null;
  VerifiedBy?: number | null;
  VerifiedAt?: string | null;
  ClosedAt?: string | null;
  // 工作台扩展字段
  RootCause?: string | null;
  CorrectiveAction?: string | null;
  PlannedCloseDate?: string | null;
  ClosureRequestedAt?: string | null;
  ClosureRequestedBy?: number | null;
  // ===== 评分管控 =====
  // 整改前评分 (批准关闭时快照, 0-1)
  ScoreAtClosure?: number | null;
  // 整改后评分 (关闭后重新评分回写; 已关闭且为空 = 待更新评分)
  ScoreAfterUpdate?: number | null;
  // 整改后评分更新时间
  ScoreUpdatedAt?: string | null;
  Remarks?: string | null;
  CreatedBy?: number | null;
  CreatedAt?: string | null;
  UpdatedAt?: string | null;
  // 审核证据附件列表 (后端注入)
  Evidence?: IssueAttachment[];
  // 关闭证据附件列表 (后端注入)
  ClosureEvidence?: IssueAttachment[];
}

// 问题统计概览 (闭环管理仪表盘)
export interface IssueStats {
  total: number;
  open_count: number;
  in_progress_count: number;
  pending_verification_count: number;
  closed_count: number;
  overdue_count: number;
  high_priority_count: number;
}

// 问题评论 (与后端 IssueCommentOut 对齐)
export interface IssueComment {
  Id: number;
  IssueId: number;
  AuthorUserId?: number | null;
  AuthorName?: string | null;
  Action: string;
  Content: string;
  FromStatus?: string | null;
  ToStatus?: string | null;
  CreatedAt?: string | null;
}

// 分页响应 (与后端 PageResponse 对齐)
export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 列表查询参数
export interface IssueListParams {
  page?: number;
  page_size?: number;
  project_id?: number;
  phase_review_item_id?: number;
  plan_id?: string;
  plan_ids?: string;  // 逗号分隔的多选 PlanId
  phase_code?: string;
  phase_codes?: string;  // 逗号分隔的多选阶段代码 (MSIA1~5)
  status?: string;
  priority?: string;
  severity?: string;
  keyword?: string;
  owner_name?: string;
  owner_names?: string;  // 逗号分隔的多选责任人姓名
}

// 筛选选项 (项目 + 责任人)
export interface IssueFilterOptions {
  projects: { value: string; label: string; projectName?: string }[];
  owners: { value: string; label: string }[];
  // 项目 ↔ 责任人 映射 (级联筛选: planId -> 该项目下出现过问题的负责人列表)
  project_owner_map?: Record<string, string[]>;
}

// 创建/更新载荷
export interface IssueCreatePayload {
  ProjectId?: number | null;
  PhaseId?: number | null;
  ItemId?: number | null;
  PhaseReviewItemId?: number | null;
  PlanId?: string;
  PhaseCode?: string;
  ItemNo?: string;
  IssueNo?: string;
  Title: string;
  Description?: string;
  OwnerUserId?: number | null;
  OwnerUserName?: string;
  OwnerName?: string;
  OwnerCompany?: string;
  OwnerDepartment?: string;
  Priority?: IssuePriority;
  Severity?: IssueSeverity;
  Deadline?: string | null;
  Status?: IssueStatus;
  Remarks?: string;
}

export interface IssueUpdatePayload {
  Title?: string;
  Description?: string;
  OwnerUserId?: number | null;
  OwnerUserName?: string;
  OwnerName?: string;
  OwnerCompany?: string;
  OwnerDepartment?: string;
  Priority?: IssuePriority;
  Severity?: IssueSeverity;
  // 人工修改 Deadline (修改后系统自动回填不再覆盖)
  Deadline?: string | null;
  Status?: IssueStatus;
  Remarks?: string;
  RootCause?: string;
  CorrectiveAction?: string;
  PlannedCloseDate?: string | null;
}

export interface IssueStatusUpdatePayload {
  Status: IssueStatus | string;
  ClosingStatus?: string;
  VerificationComments?: string;
}

export interface IssueCommentCreatePayload {
  Content: string;
  Action?: 'comment' | 'status_change' | 'verify' | 'assign' | string;
}

// ============ API 函数 ============

// 问题列表 (分页)
export function getIssues(params: IssueListParams): Promise<PageResponse<Issue>> {
  return http.get<PageResponse<Issue>>('/issues', { params });
}

// 问题筛选选项 (项目 + 责任人)
export function getIssueFilterOptions(): Promise<IssueFilterOptions> {
  return http.get<IssueFilterOptions>('/issues/filter-options');
}

// 问题统计概览
export function getIssueStats(params: {
  plan_id?: string;
  plan_ids?: string;
  phase_code?: string;
  phase_codes?: string;
  owner_name?: string;
  owner_names?: string;
} = {}): Promise<IssueStats> {
  return http.get<IssueStats>('/issues/stats/summary', { params });
}

// 问题详情
export function getIssue(id: number): Promise<Issue> {
  return http.get<Issue>(`/issues/${id}`);
}

// 创建问题
export function createIssue(data: IssueCreatePayload): Promise<Issue> {
  return http.post<Issue>('/issues', data);
}

// 更新问题
export function updateIssue(id: number, data: IssueUpdatePayload): Promise<Issue> {
  return http.put<Issue>(`/issues/${id}`, data);
}

// 更新问题状态
export function updateIssueStatus(id: number, data: IssueStatusUpdatePayload): Promise<Issue> {
  return http.patch<Issue>(`/issues/${id}/status`, data);
}

// 验证问题 (lead_reviewer/admin)
export function verifyIssue(id: number, data: IssueStatusUpdatePayload): Promise<Issue> {
  return http.post<Issue>(`/issues/${id}/verify`, data);
}

// 重开已关闭问题 (admin/lead_reviewer): 清零评分管控字段, 重新走整改闭环
export function reopenIssue(id: number, reason: string): Promise<Issue> {
  return http.post<Issue>(`/issues/${id}/reopen`, { Reason: reason });
}

// 删除问题 (软删)
export function deleteIssue(id: number): Promise<void> {
  return http.delete<void>(`/issues/${id}`);
}

// 问题评论历史
export function listIssueComments(issueId: number): Promise<IssueComment[]> {
  return http.get<IssueComment[]>(`/issues/${issueId}/comments`);
}

// 新增问题评论
export function addIssueComment(issueId: number, data: IssueCommentCreatePayload): Promise<IssueComment> {
  return http.post<IssueComment>(`/issues/${issueId}/comments`, data);
}

// ============ 审核证据附件 ============

// 问题审核证据列表
export function listIssueEvidence(issueId: number): Promise<IssueAttachment[]> {
  return http.get<IssueAttachment[]>(`/issues/${issueId}/evidence`);
}

// 问题关闭证据列表 (被审核人申请关闭时上传)
export function listIssueClosureEvidence(issueId: number): Promise<IssueAttachment[]> {
  return http.get<IssueAttachment[]>(`/issues/${issueId}/closure-evidence`);
}

// 上传问题关闭证据 (multipart, owner_type=issue_closure)
export async function uploadIssueClosureEvidence(
  issueId: number,
  file: File,
): Promise<{ id: number; file_name: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const resp = await apiClient.post(
    `/attachments`,
    formData,
    {
      params: { owner_type: 'issue_closure', owner_id: issueId },
      headers: { 'Content-Type': 'multipart/form-data' },
    },
  );
  return resp as unknown as { id: number; file_name: string };
}

// 删除问题关闭证据
export function deleteIssueClosureEvidence(
  issueId: number,
  attachmentId: number,
): Promise<void> {
  return http.delete<void>(`/issues/${issueId}/closure-evidence/${attachmentId}`);
}

// 上传审核证据附件 (multipart) - 使用 axios 客户端以支持 FormData
export async function uploadIssueEvidence(
  issueId: number,
  file: File,
): Promise<{ id: number; file_name: string }> {
  const formData = new FormData();
  formData.append('file', file);
  // apiClient 已配置 baseURL=/api 与 Authorization 拦截器
  const resp = await apiClient.post(
    `/attachments`,
    formData,
    {
      params: { owner_type: 'issue', owner_id: issueId },
      headers: { 'Content-Type': 'multipart/form-data' },
    },
  );
  // apiClient 响应拦截器已解包 response.data, resp 直接就是返回对象
  return resp as unknown as { id: number; file_name: string };
}

// 删除附件
export function deleteAttachment(attachmentId: number): Promise<void> {
  return http.delete<void>(`/attachments/${attachmentId}`);
}

// 获取附件 Blob URL (用于 <img src> 显示图片)
// 注意: apiClient 响应拦截器已解包 response.data, 因此返回值直接就是 Blob
export async function fetchAttachmentBlobUrl(attachmentId: number): Promise<string> {
  const blob = await apiClient.get(`/attachments/${attachmentId}`, {
    responseType: 'blob',
  });
  return URL.createObjectURL(blob as unknown as Blob);
}

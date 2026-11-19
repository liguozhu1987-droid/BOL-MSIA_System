import { http } from './client';

// 审核记录状态: draft / submitted / confirmed
export type ReviewStatus = 'draft' | 'submitted' | 'confirmed';

// 审核记录 (与后端 ReviewOut 对齐, 字段为 PascalCase)
export interface ReviewRecord {
  Id: number;
  ProjectId: number;
  PhaseId: number;
  ItemId: number;
  PhaseReviewItemId?: number | null;
  PhaseCode?: string | null;
  ItemNo?: string | null;
  PlanId?: string | null;
  ReviewerId: number;
  Score?: number | null;
  ResultText?: string | null;
  Comments?: string | null;
  Status: ReviewStatus | string;
  SubmittedAt?: string | null;
  ConfirmedAt?: string | null;
  ConfirmedBy?: number | null;
  CreatedAt?: string | null;
  UpdatedAt?: string | null;
}

// 创建审核记录
export interface ReviewCreatePayload {
  ProjectId: number;
  PhaseId: number;
  ItemId: number;
  PhaseReviewItemId?: number | null;
  PhaseCode?: string;
  ItemNo?: string;
  PlanId?: string;
  Score?: number | null;
  ResultText?: string;
  Comments?: string;
  Status?: ReviewStatus;
}

// 更新审核记录
export interface ReviewUpdatePayload {
  Score?: number | null;
  ResultText?: string;
  Comments?: string;
  Status?: ReviewStatus;
}

// 按检查项 ID 查询评审记录
export function getItemReviews(phaseReviewItemId: number): Promise<ReviewRecord[]> {
  return http.get<ReviewRecord[]>(`/phase-review-items/${phaseReviewItemId}/reviews`);
}

// 创建审核记录
export function createReview(data: ReviewCreatePayload): Promise<ReviewRecord> {
  return http.post<ReviewRecord>('/reviews', data);
}

// 更新审核记录
export function updateReview(id: number, data: ReviewUpdatePayload): Promise<ReviewRecord> {
  return http.put<ReviewRecord>(`/reviews/${id}`, data);
}

// 删除审核记录 (admin/lead_reviewer)
export function deleteReview(id: number): Promise<void> {
  return http.delete<void>(`/reviews/${id}`);
}

// ============ MSIA Result (阶段平均分) ============

// 单阶段平均分响应
export interface PhaseResult {
  phase_code: string;
  plan_id?: string | null;
  avg_score: number | null;
  count: number;
}

// 查询单阶段评审平均分
export function getPhaseResult(phaseCode: string, planId?: string): Promise<PhaseResult> {
  return http.get<PhaseResult>('/reviews/phase-result', {
    params: { phase_code: phaseCode, plan_id: planId },
  });
}

// 批量查询 MSIA1~5 各阶段评审平均分
export function getPhaseResultsBatch(planId: string): Promise<PhaseResult[]> {
  return http.get<PhaseResult[]>('/reviews/phase-results', {
    params: { plan_id: planId },
  });
}

// ============ 阶段各检查项最新评审记录 (RESULT 列) ============

// 单条最新评审记录摘要 (用于 RESULT 列显示)
export interface ItemLatestReview {
  phase_review_item_id: number;
  review_id: number;
  score: number | null;
  status: string;
  comments: string | null;
  updated_at: string | null;
}

// 批量查询指定阶段下所有检查项的最新评审记录
export function getPhaseItemsLatest(
  phaseCode: string,
  planId?: string,
): Promise<ItemLatestReview[]> {
  return http.get<ItemLatestReview[]>('/reviews/phase-items-latest', {
    params: { phase_code: phaseCode, plan_id: planId },
  });
}

import { http } from './client';
import type { PhaseScore } from './msiaPlan';

// 归档项目列表项 (与 MsiaPlanItem 字段一致, 额外含 MSIA1/2 日期与注入字段)
export interface ArchivedProjectItem {
  seq: number;
  planId: number;
  seqId: number | null;
  orderId: string | null;
  order_description: string | null;
  projectName: string | null;
  lineType: string | null;
  projectType: string | null;
  userName_in_charge: string | null;
  name_in_charge: string | null;
  realName: string | null;
  ownerName: string | null;
  leadUser: string | null;
  sme1: string | null;
  sme2: string | null;
  msia1PlanDate: string | null;
  msia1ActualDate: string | null;
  msia2PlanDate: string | null;
  msia2ActualDate: string | null;
  msia3PlanDate: string | null;
  msia3ActualDate: string | null;
  msia4PlanDate: string | null;
  msia4ActualDate: string | null;
  msia5PlanDate: string | null;
  msia5ActualDate: string | null;
  plantName: string | null;
  lineName: string | null;
  supplerName: string | null;
  issueDate: string | null;
  endDate: string | null;
  updateDate: string | null;
  // MSIA1~5 各阶段综合评分 (未评审为 null)
  phase_scores?: Record<string, PhaseScore | null> | null;
  // 五个阶段综合评分的算术平均 (无任何评分时为 null)
  overall?: number | null;
  // 问题统计
  issue_stats?: { total: number; unclosed: number };
}

// 归档项目分页响应
export interface ArchivedProjectPageResponse {
  items: ArchivedProjectItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 查询归档项目列表 (已完成全部阶段审核的项目)
export function listArchivedProjectsApi(params: {
  order_id?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<ArchivedProjectPageResponse> {
  return http.get<ArchivedProjectPageResponse>('/archive/projects', { params });
}

// ============ 阶段审核记录明细 ============

// 单条检查项审核记录
export interface ArchivedReviewItem {
  seq: number;
  item_id: number;
  item_name: string;
  item_type: string | null;
  request: string | null;
  score: number | null;
  score_percent: number | null;
  result_text: string | null;
  comments: string | null;
  reviewer_name: string | null;
  submitted_at: string | null;
}

// 阶段审核记录响应
export interface ArchivedPhaseReviews {
  plan_id: string;
  phase_code: string;
  items: ArchivedReviewItem[];
  summary: {
    item_count: number;
    scored_count: number;
    avg_score: number | null;
    avg_percent: number | null;
  };
  // 无逐项评审记录时的历史补录阶段评分 (回退展示)
  historic_score: number | null;
}

// 查询归档项目指定阶段的审核记录明细
export function getArchivedPhaseReviewsApi(
  planId: string,
  phaseCode: string,
): Promise<ArchivedPhaseReviews> {
  return http.get<ArchivedPhaseReviews>(
    `/archive/projects/${planId}/reviews`,
    { params: { phase_code: phaseCode } },
  );
}

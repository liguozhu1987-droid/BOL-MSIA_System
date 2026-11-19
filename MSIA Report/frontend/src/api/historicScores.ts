import { http } from './client';

// 项目列表项 (来自 HRDB MSIA 计划, 含已录入历史评分标注)
export interface HistoricScoreProjectItem {
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
  // 已录入的历史评分
  entered_scores: EnteredScore[];
  entered_phase_count: number;
  entered_phases_map: Record<string, EnteredScore>;
}

// 单条已录入的历史评分
export interface EnteredScore {
  phase_code: string;
  score: number; // 0-1 小数
  score_percent: number; // 0-100 百分比
  remark: string | null;
}

// 项目列表分页响应
export interface HistoricScoreProjectPageResponse {
  items: HistoricScoreProjectItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 查询某项目已录入评分 (GET /historic-scores/{plan_id})
export interface ProjectScoreRecord {
  id: number;
  plan_id: string;
  phase_code: string;
  score: number; // 0-1 小数
  score_percent: number; // 0-100
  remark: string | null;
  created_at: string | null;
  updated_at: string | null;
}

// 查询项目列表 (含已录入历史评分标注)
export function listHistoricScoreProjectsApi(params: {
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<HistoricScoreProjectPageResponse> {
  return http.get<HistoricScoreProjectPageResponse>('/historic-scores/projects', { params });
}

// 查询某项目已录入的各阶段评分
export function getHistoricScoresApi(planId: string): Promise<ProjectScoreRecord[]> {
  return http.get<ProjectScoreRecord[]>(`/historic-scores/${planId}`);
}

// 保存某项目各阶段历史评分 (upsert)
export function saveHistoricScoresApi(
  planId: string,
  payload: {
    order_id?: string | null;
    project_name?: string | null;
    scores: Array<{ phase_code: string; score: number; remark?: string | null }>;
  }
): Promise<{ ok: boolean; plan_id: string; saved_phases: string[] }> {
  return http.post(`/historic-scores/${planId}`, payload);
}

// 删除某阶段历史评分
export function deleteHistoricScoreApi(
  planId: string,
  phaseCode: string
): Promise<{ ok: boolean; message: string }> {
  return http.delete(`/historic-scores/${planId}/${phaseCode}`);
}

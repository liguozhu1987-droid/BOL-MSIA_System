// MSIA 阶段审核报告 API (按 Report MSIA 模板格式)
import { http, default as apiClient } from './client';

// 报告头部项目关键数据
export interface AuditReportProject {
  name: string;
  no: string;
  type: string;
  cmc_ame: string;
  plant_me: string;
  plant: string;
  line: string;
  supplier: string;
}

// 里程碑日期
export interface AuditReportMilestones {
  plan_date: string;
  actual_date: string;
  ots: string;
  ppap: string;
  sop: string;
  // 报告 Milestones 面板的 5 个项目里程碑时间点 (审核员手动维护)
  inalfa_kickoff: string;
  supplier_kickoff: string;
  design_freeze: string;
  pvp: string;
  inalfa_sop: string;
}

// 检查项问题行
export interface AuditReportIssue {
  issue_no: string;
  title: string;
  severity: string;
  priority: string;
  created_by: number | null;
  created_at: string;
}

// 检查项报告行
export interface AuditReportItem {
  phase_review_item_id: number;
  seq: number;
  item_type: string;
  item_name: string;
  request: string;
  result: string;          // 评分百分比 (如 '75%'), 未评为空
  score: number | null;
  issues: AuditReportIssue[]; // Comment 列: 该检查项问题逐条
}

// 高风险问题
export interface AuditHighRiskIssue {
  issue_no: string;
  title: string;
  severity: string;
  priority: string;
  item_name: string;
  /** 合并报告模式下的来源阶段代码 (如 "MSIA1") */
  phase_code?: string;
}

// 阶段审核报告 (Report MSIA 模板格式)
export interface PhaseAuditReport {
  plan_id: string;
  phase_code: string;
  msia_no: string;
  msia_result: string;      // 阶段平均分 (如 '66.7%'), 无分数为空
  project: AuditReportProject;
  milestones: AuditReportMilestones;
  reviewers: string[];      // 提问题 + 评分用户
  review_place: string;     // 评审地点 (默认 Teams, 可维护)
  reviewees: string;        // 项目负责人
  date: string;             // 最后一次提交问题/评分时间
  high_risk_issues: AuditHighRiskIssue[];
  items: AuditReportItem[];
  /** 合并报告模式: 各阶段独立子报告 (按阶段竖直叠加展示) */
  sub_reports?: PhaseAuditReport[];
}

// 阶段评审元数据
export interface PhaseReviewMeta {
  plan_id: string;
  phase_code: string;
  review_place: string;
  cmc_ame: string;
  inalfa_kickoff: string;
  supplier_kickoff: string;
  design_freeze: string;
  pvp: string;
  inalfa_sop: string;
  updated_at: string | null;
}

// 阶段评审元数据维护载荷 (review_place 阶段级; 其余为项目级, 同步所有阶段)
export interface PhaseReviewMetaPayload {
  review_place?: string;
  cmc_ame?: string;
  inalfa_kickoff?: string;
  supplier_kickoff?: string;
  design_freeze?: string;
  pvp?: string;
  inalfa_sop?: string;
}

// 获取阶段审核报告数据
export function getPhaseAuditReport(planId: string, phaseCode: string): Promise<PhaseAuditReport> {
  return http.get<PhaseAuditReport>(`/projects/${planId}/phase-report/${phaseCode}`);
}

// 查询阶段评审元数据 (Review place)
export function getPhaseReviewMeta(planId: string, phaseCode: string): Promise<PhaseReviewMeta> {
  return http.get<PhaseReviewMeta>(`/projects/${planId}/phase-review-meta/${phaseCode}`);
}

// 维护阶段评审元数据 (仅审核员)
export function updatePhaseReviewMeta(
  planId: string,
  phaseCode: string,
  payload: PhaseReviewMetaPayload,
): Promise<PhaseReviewMeta> {
  return http.put<PhaseReviewMeta>(`/projects/${planId}/phase-review-meta/${phaseCode}`, payload);
}

// 触发浏览器下载 Blob
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// 下载阶段审核报告 PDF (模板格式)
// 注意: apiClient 响应拦截器已解包 response.data, 返回值直接就是 Blob
export async function downloadPhaseAuditReportPdf(planId: string, phaseCode: string): Promise<void> {
  try {
    const blob = await apiClient.get(
      `/projects/${planId}/phase-report/${phaseCode}/export`,
      { responseType: 'blob' },
    );
    downloadBlob(blob as unknown as Blob, `MSIA_report_${planId}_${phaseCode}.pdf`);
  } catch (error: any) {
    const status = error?.response?.status;
    if (status === 404) {
      throw new Error('该阶段暂无评审数据，无法导出 PDF');
    }
    throw error;
  }
}

// 获取合并审核报告数据 (多阶段汇总)
export function getCombinedAuditReport(planId: string, phases: string = 'MSIA1,MSIA2,MSIA3'): Promise<PhaseAuditReport> {
  return http.get<PhaseAuditReport>(`/projects/${planId}/combined-report`, { params: { phases } });
}

// 下载合并审核报告 PDF
export async function downloadCombinedReportPdf(planId: string, phases: string = 'MSIA1,MSIA2,MSIA3'): Promise<void> {
  try {
    const blob = await apiClient.get(
      `/projects/${planId}/combined-report/export`,
      { params: { phases }, responseType: 'blob' },
    );
    downloadBlob(blob as unknown as Blob, `MSIA_report_${planId}_combined.pdf`);
  } catch (error: any) {
    const status = error?.response?.status;
    if (status === 404) {
      throw new Error('暂无评审数据，无法导出 PDF');
    }
    throw error;
  }
}

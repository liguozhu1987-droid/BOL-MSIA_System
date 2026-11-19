import { http } from './client';

// 项目某阶段综合评分 (后端注入: 评审记录优先, 历史补录回退)
export interface PhaseScore {
  avg_score: number;      // 综合评分 (0~1)
  avg_percent: number;    // 百分值 (如 92.5)
  item_count: number;     // 已评分检查项数
  source: 'review' | 'historic';
}

// MSIA 计划列表项 - 结构化字段 (与后端 JOIN 查询对齐, 含四表关联)
export interface MsiaPlanItem {
  // 行号序号 (分页内连续编号)
  seq: number;
  // 计划主键 (后端返回 planId, 用于查询详情)
  planId: number;
  // 工单表序列号 (来自 orderBasicInfor.seqId)
  seqId: number | null;
  // 工单 ID
  orderId: string | null;
  // 工单描述
  order_description: string | null;
  // 项目名称
  projectName: string | null;
  // 产线类型 (来自 orderBasicInfor.lineType)
  lineType: string | null;
  // 项目类型 (来自 orderBasicInfor.projectType)
  projectType: string | null;
  // 工单负责人账号 (英文)
  userName_in_charge: string | null;
  // 工单负责人中文名 (来自 orderBasicInfor.name_in_charge)
  name_in_charge: string | null;
  // 用户表 realName (来自 fine_user.realName, 含括号中文)
  realName: string | null;
  // 项目负责人中文名 (后端解析: 优先 realName 括号中文, 回退 name_in_charge)
  ownerName: string | null;
  // MSIA 负责人 (英文账号)
  leadUser: string | null;
  // SME 成员
  sme1: string | null;
  sme2: string | null;
  // MSIA3 阶段计划/实际日期
  msia3PlanDate: string | null;
  msia3ActualDate: string | null;
  // MSIA4 阶段计划/实际日期
  msia4PlanDate: string | null;
  msia4ActualDate: string | null;
  // MSIA5 阶段计划/实际日期
  msia5PlanDate: string | null;
  msia5ActualDate: string | null;
  // 工厂/产线/供应商
  plantName: string | null;
  lineName: string | null;
  supplerName: string | null;
  // 工单下发日期 / 结束日期 / 计划更新时间
  issueDate: string | null;
  endDate: string | null;
  updateDate: string | null;
  // MSIA1~5 各阶段综合评分 (后端注入; 键名与后端一致为 snake_case, 未评审阶段为 null, 显示为空)
  phase_scores?: Record<string, PhaseScore | null> | null;
}

// MSIA 计划分页响应
export interface MsiaPlanPageResponse {
  items: MsiaPlanItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 计划详情 (含关联信息, 字段动态)
export interface MsiaPlanDetail {
  plan: Record<string, unknown> | null;
  order_basic_info: Record<string, unknown> | null;
  project_basic_info: Record<string, unknown> | null;
}

// 按 orderId 查询关联信息 (旧接口, 兼容)
export interface OrderRelatedInfo {
  order_id: string;
  order_basic_info: Record<string, unknown> | null;
  project_basic_info: Record<string, unknown> | null;
}

// 查询 MSIA 计划列表
export function listMsiaPlansApi(params: {
  order_id?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<MsiaPlanPageResponse> {
  return http.get<MsiaPlanPageResponse>('/msia-plan', { params });
}

// 查询单个计划详情
export function getMsiaPlanDetailApi(planId: string): Promise<MsiaPlanDetail> {
  return http.get<MsiaPlanDetail>(`/msia-plan/${planId}`);
}

// 按工单 ID 查询关联信息
export function getOrderRelatedInfoApi(orderId: string): Promise<OrderRelatedInfo> {
  return http.get<OrderRelatedInfo>(`/msia-plan/order/${orderId}`);
}

// ============ 待评审项目 (本月/下月) ============

// 单个待评审阶段信息
export interface PendingPhase {
  // 阶段代码, 如 'MSIA4'
  phase: string;
  // 阶段数字, 1-5
  phase_num: number;
  // 计划评审日期 (ISO 字符串)
  plan_date: string;
  // 距今天数 (负数=已逾期)
  days_until: number;
  // 是否已逾期
  is_overdue: boolean;
}

// 待评审项目项
export interface PendingReviewItem {
  // 计划主键 (用于跳转)
  planId: number;
  // 工单 ID
  orderId: string | null;
  // 项目名称
  projectName: string | null;
  // 工单描述
  order_description: string | null;
  // 产线类型
  lineType: string | null;
  // 项目负责人中文名
  ownerName: string | null;
  // MSIA 负责人
  leadUser: string | null;
  // 工厂名称
  plantName: string | null;
  // 产线名称
  lineName: string | null;
  // 待评审阶段列表
  pending_phases: PendingPhase[];
  // 最早待评审阶段日期 (用于排序)
  earliest_plan_date: string;
}

// 查询本月和下月待评审项目
export function listPendingReviewsApi(monthsAhead: number = 1): Promise<PendingReviewItem[]> {
  return http.get<PendingReviewItem[]>('/msia-plan/pending-reviews', {
    params: { months_ahead: monthsAhead },
  });
}

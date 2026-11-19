import { http, default as apiClient } from './client';

export interface PhaseReportItem {
  item_no: string | null;
  name: string | null;
  score: number | null;
  result: string | null;
  comments: string | null;
  status: string | null;
}

export interface PhaseReport {
  phase: string;
  score: number | null;
  items: PhaseReportItem[];
}

// 获取阶段报告数据 (planId 为 MSIA 计划主键)
export function getPhaseReport(planId: string, phaseCode: string): Promise<PhaseReport> {
  return http.get<PhaseReport>(`/projects/${planId}/report/${phaseCode}`);
}

// 获取项目记录条目
export function getRecordEntries(planId: string): Promise<{ project: string; records: any[] }>{
  return http.get(`/projects/${planId}/record`);
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

// 下载阶段报告 PDF (带 JWT 认证)
// 注意: apiClient 响应拦截器已解包 response.data, 返回值直接就是 Blob
export async function downloadReportPdf(planId: string, phaseCode: string): Promise<void> {
  try {
    const blob = await apiClient.get(
      `/projects/${planId}/export/report/${phaseCode}`,
      { params: { format: 'pdf' }, responseType: 'blob' },
    );
    downloadBlob(blob as unknown as Blob, `report_${planId}_${phaseCode}.pdf`);
  } catch (error: any) {
    const status = error?.response?.status;
    if (status === 404) {
      throw new Error('该阶段暂无评审数据，无法导出 PDF');
    }
    throw error;
  }
}

// 下载项目审核记录 Excel (带 JWT 认证)
// 注意: apiClient 响应拦截器已解包 response.data, 返回值直接就是 Blob
export async function downloadRecordExcel(planId: string): Promise<void> {
  try {
    const blob = await apiClient.get(
      `/projects/${planId}/export/record`,
      { params: { format: 'excel' }, responseType: 'blob' },
    );
    downloadBlob(blob as unknown as Blob, `record_${planId}.xlsx`);
  } catch (error: any) {
    const status = error?.response?.status;
    if (status === 404) {
      throw new Error('暂无评审数据，无法导出 Excel');
    }
    throw error;
  }
}

export default {};

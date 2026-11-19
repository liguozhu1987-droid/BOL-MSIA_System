import { http } from './client';

// 项目实体 (与后端 ProjectOut 对齐, 字段为 PascalCase)
export interface Project {
  Id: number;
  Name: string;
  Code: string;
  Type?: string | null;
  CmcAme?: string | null;
  PlantMe?: string | null;
  InalfaKickoff?: string | null;
  SupplierKickoff?: string | null;
  DesignFreeze?: string | null;
  Pvp?: string | null;
  InalfaSop?: string | null;
  Status: string;
  CreatedBy?: number | null;
  CreatedAt?: string | null;
  UpdatedAt?: string | null;
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
export interface ProjectListParams {
  page?: number;
  page_size?: number;
  keyword?: string;
  status?: string;
}

// 获取项目列表
export function getProjects(params: ProjectListParams): Promise<PageResponse<Project>> {
  return http.get<PageResponse<Project>>('/projects', { params });
}

// 获取项目详情
export function getProject(id: number): Promise<Project> {
  return http.get<Project>(`/projects/${id}`);
}

// 新建项目
export function createProject(data: Partial<Project>): Promise<Project> {
  return http.post<Project>('/projects', data);
}

// 更新项目
export function updateProject(id: number, data: Partial<Project>): Promise<Project> {
  return http.put<Project>(`/projects/${id}`, data);
}

// 删除项目
export function deleteProject(id: number): Promise<void> {
  return http.delete<void>(`/projects/${id}`);
}

// 导出项目
export function exportProject(id: number): Promise<Blob> {
  return http.get<Blob>(`/projects/${id}/export`, { responseType: 'blob' });
}

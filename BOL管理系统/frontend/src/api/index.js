// API 层：统一 axios 实例 + 按模块分组的接口封装
// - baseURL '/api'，自动附带 JWT（Authorization: Bearer xxx）
// - 响应拦截器直接返回 data；错误统一 ElMessage 提示
// - 401 时清除登录态并跳转登录页（登录/注册等公开接口除外）
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { authState, clearAuthState } from '../composables/authState'

// 公开端点（401 时不应触发登出跳转）
const PUBLIC_AUTH_URLS = [
  '/auth/login/',
  '/auth/register/',
  '/auth/forgot-password/',
  '/auth/reset-password/',
  '/auth/config/',
  '/auth/oidc/',
]

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：附带令牌
http.interceptors.request.use((config) => {
  if (authState.token) {
    config.headers.Authorization = `Token ${authState.token}`
  }
  return config
})

// 响应拦截器：直接返回 data；统一错误提示
http.interceptors.response.use(
  (response) => {
    // blob 下载场景（模板下载等）直接返回 Blob
    if (response.config.responseType === 'blob') {
      return response.data
    }
    return response.data
  },
  (error) => {
    const status = error.response?.status
    const config = error.config || {}
    const isPublic = PUBLIC_AUTH_URLS.some((u) => (config.url || '').includes(u))

    if (status === 401 && !isPublic) {
      // 令牌无效/过期：清除登录态并回到登录页
      clearAuthState()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    // 统一错误提示：优先展示后端 detail / error 字段
    let msg = ''
    const data = error.response?.data
    if (data instanceof Blob) {
      msg = '请求失败'
    } else if (typeof data === 'string') {
      msg = data
    } else if (data) {
      msg = data.detail || data.error || data.message || ''
      if (!msg && typeof data === 'object') {
        const first = Object.values(data)[0]
        msg = Array.isArray(first) ? String(first[0]) : String(first || '')
      }
    }
    if (!msg) msg = status === 403 ? '没有操作权限' : error.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export default http

// ---------------- 认证 ----------------
export const authApi = {
  login: (data) => http.post('/auth/login/', data),
  guestLogin: () => http.post('/auth/guest-login/'),
  register: (data) => http.post('/auth/register/', data),
  logout: () => http.post('/auth/logout/'),
  me: () => http.get('/auth/me/'),
  changePassword: (data) => http.post('/auth/change-password/', data),
  updateProfile: (data) => http.patch('/auth/me/', data),
  forgotPassword: (data) => http.post('/auth/forgot-password/', data),
  resetPassword: (data) => http.post('/auth/reset-password/', data),
  // 登录页功能开关 (OIDC/本地登录/自助注册/密码自助, 公开端点)
  config: () => http.get('/auth/config/'),
  // 统一身份登录: 跳转后端发起 OIDC 授权 (后端 302 到 Keycloak 登录页)
  oidcLogin: () => {
    window.location.href = '/api/auth/oidc/login/'
  },
  // OIDC 回调: 用一次性码 (otk) 换本地令牌, 响应结构与本地登录一致
  oidcToken: (otk) => http.post('/auth/oidc/token/', { otk }),
}

// ---------------- 人员管理 ----------------
export const userApi = {
  list: (params) => http.get('/users/employees/', { params }),
  active: () => http.get('/users/employees/active/'),
  create: (data) => http.post('/users/employees/', data),
  update: (id, data) => http.patch(`/users/employees/${id}/`, data),
  remove: (id) => http.delete(`/users/employees/${id}/`),
  activate: (id) => http.post(`/users/employees/${id}/activate/`),
  deactivate: (id) => http.post(`/users/employees/${id}/deactivate/`),
}

// ---------------- 系统管理 · 报告中心（季度/年度分析报告） ----------------
export const reportApi = {
  // list 支持 report_type / year / search（标题关键词）筛选
  list: (params) => http.get('/reports/', { params }),
  retrieve: (id) => http.get(`/reports/${id}/`),
  // 手动生成耗时较长（跨库取数 + 渲染 HTML），放宽超时
  generate: (data) => http.post('/reports/generate/', data, { timeout: 300000 }),
  remove: (id) => http.delete(`/reports/${id}/delete/`),
  // 邮件推送（仅管理员，报告 HTML 以附件发送）
  email: (id, data) => http.post(`/reports/${id}/email/`, data, { timeout: 60000 })
}

// ---------------- 高 BOL 跟踪 ----------------
export const trackingApi = {
  list: (params) => http.get('/tracking/high-bol-tracking/', { params }),
  searchPrograms: (params) => http.get('/tracking/high-bol-tracking/search-programs/', { params }),
  retrieve: (id) => http.get(`/tracking/high-bol-tracking/${id}/`),
  create: (data) => http.post('/tracking/high-bol-tracking/', data),
  update: (id, data) => http.patch(`/tracking/high-bol-tracking/${id}/`, data),
  remove: (id) => http.delete(`/tracking/high-bol-tracking/${id}/`),
  assign: (id, data) => http.post(`/tracking/high-bol-tracking/${id}/assign/`, data),
  start: (id, data) => http.post(`/tracking/high-bol-tracking/${id}/start/`, data),
  achieve: (id, data) => http.post(`/tracking/high-bol-tracking/${id}/achieve/`, data),
  verify: (id, data) => http.post(`/tracking/high-bol-tracking/${id}/verify/`, data),
  close: (id, data) => http.post(`/tracking/high-bol-tracking/${id}/close/`, data),
  reopen: (id, data) => http.post(`/tracking/high-bol-tracking/${id}/reopen/`, data),
  timeline: (id) => http.get(`/tracking/high-bol-tracking/${id}/timeline/`),
  addLog: (id, data) => http.post(`/tracking/high-bol-tracking/${id}/add-log/`, data),
}

// ---------------- 实测 CT ----------------
export const actualCtApi = {
  cascadeFilters: (params) => http.get('/actual-ct/cascade-filters/', { params }),
  search: (params) => http.get('/actual-ct/search/', { params }),
  sctVsAct: (params) => http.get('/actual-ct/sct-vs-act/', { params }),
  ctTrendTop: (params) => http.get('/actual-ct/ct-trend-top/', { params }),
  actStdDeviation: (params) => http.get('/actual-ct/act-std-deviation/', { params }),
  stationDetail: (params) => http.get('/actual-ct/station-detail/', { params }),
  lineBalance: (params) => http.get('/actual-ct/line-balance/', { params }),
  boxPlot: (params) => http.get('/actual-ct/box-plot/', { params }),
  analysisSummary: (params) => http.get('/actual-ct/analysis/summary/', { params }),
  analysisFilterOptions: (params) => http.get('/actual-ct/analysis/filter_options/', { params }),
  bottleneckCt: (params) => http.get('/actual-ct/bottleneck-ct/', { params }),
  realCt: (params) => http.get('/actual-ct/real-ct/', { params }),
  realCtPerDay: (params) => http.get('/actual-ct/real-ct-per-day/', { params }),
}

// ---------------- 动态 BOL（审批历史多维分析） ----------------
export const dynamicBolApi = {
  overview: (params) => http.get('/dynamic-bol/overview/', { params }),
  approvalOverviewStats: (params) => http.get('/dynamic-bol/approval-overview-stats/', { params }),
  byProcess: (params) => http.get('/dynamic-bol/by-process/', { params }),
  topCompare: (params) => http.get('/dynamic-bol/top-compare/', { params }),
  approvalTrendFilterOptions: (params) => http.get('/dynamic-bol/approval-trend-filter-options/', { params }),
  approvalTrend: (params) => http.get('/dynamic-bol/approval-trend/', { params }),
  lowLbAnalysis: (params) => http.get('/dynamic-bol/low-lb-analysis/', { params }),
}

// ---------------- 预算 BOL（Budget/Achievable/Target 三类同构） ----------------
export const budgetBolApi = {
  filterOptions: () => http.get('/budget-bol/budget-bol/filter-options/'),
  list: (params) => http.get('/budget-bol/budget-bol/', { params }),
  projectInfo: (params) => http.get('/budget-bol/budget-bol/project-info/', { params }),
  // 模板下载（blob）：type = budget | achievable | target
  downloadTemplate: (type) => http.get('/budget-bol/budget-bol/import-template/', {
    params: { type },
    responseType: 'blob',
  }),
  // Excel 导入：同财年同类型先清空后全量替换
  importExcel: (file, fiscalYear, bolType, createdBy) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('fiscal_year', fiscalYear)
    fd.append('bol_type', bolType)
    if (createdBy) fd.append('created_by', createdBy)
    return http.post('/budget-bol/budget-bol/import-excel/', fd, { timeout: 300000 })
  },
  // 查询 Excel 导入履历（支持 fiscal_year / bol_type / limit 筛选）
  importLogs: (params) => http.get('/budget-bol/budget-bol/import-logs/', { params }),
  // 一键清空（管理员，confirm 必须为 CONFIRM_CLEAR）
  clearAll: (data) => http.post('/budget-bol/budget-bol/clear-all/', data),
}

// ---------------- 分析中心 ----------------
export const analyticsApi = {
  dashboard: (params) => http.get('/analytics/dashboard/', { params }),
  comparison: (params) => http.get('/analytics/comparison/', { params }),
  improveTargetCompare: (params) => http.get('/analytics/improve-target-compare/', { params }),
  achievableYoy: (params) => http.get('/analytics/achievable-yoy/', { params }),
  budgetBolComparison: (params) => http.get('/analytics/budget-bol-comparison/', { params }),
  multiDimAnalysis: (params) => http.get('/analytics/multi-dim-analysis/', { params }),
  multiDimTrend: (params) => http.get('/analytics/multi-dim-trend/', { params }),
  bolLifecycleAll: (params) => http.get('/analytics/bol-lifecycle-all/', { params }),
}

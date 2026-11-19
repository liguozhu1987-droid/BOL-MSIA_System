// 全局路由：BOL 管理分析平台
// 结构：门户首页（HomeView，模块卡片导航）+ 各功能页平铺路由
// 权限标记：
//   meta.guestAllowed  游客（GUEST 角色）可访问
//   meta.requiresAdmin 仅管理员可访问
import { createRouter, createWebHistory } from 'vue-router'
import { authState } from '@/composables/useAuth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { public: true },
  },
  {
    path: '/forgot-password',
    name: 'ForgotPassword',
    component: () => import('@/views/ForgotPasswordView.vue'),
    meta: { public: true },
  },
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('@/views/ResetPasswordView.vue'),
    meta: { public: true },
  },
  {
    // OIDC 统一登录回调: 后端 302 到此 (?otk= 一次性码 / ?error= 失败原因)
    // 必须 public: 此时本地尚未有登录态, 守卫不得跳登录页
    path: '/oidc/callback',
    name: 'OidcCallback',
    component: () => import('@/views/OidcCallback.vue'),
    meta: { public: true },
  },
  {
    // 门户首页：模块卡片导航
    // guestAllowed 必须为 true：HomeView 自带游客锁定卡片逻辑（isModuleAccessible），
    // 且守卫对游客访问受限页会 return '/' —— 若 / 自身不允许游客，
    // 将形成 "/ → /" 无限重定向循环，标签页假死（无法进入系统）
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue'),
    meta: { guestAllowed: true },
  },
  {
    // 综合看板
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: '综合看板', guestAllowed: true },
  },
  {
    // 高 BOL 跟踪（改善闭环）
    path: '/tracking',
    name: 'Tracking',
    component: () => import('@/views/TrackingView.vue'),
    meta: { title: '高 BOL 跟踪' },
  },
  {
    // 预算 BOL（Budget/Achievable/Target 三类同构）
    path: '/budget-bol',
    name: 'BudgetBol',
    component: () => import('@/views/BudgetBolView.vue'),
    meta: { title: '预算 BOL' },
  },
  {
    // 预算 BOL 使用帮助
    path: '/budget-bol/help',
    name: 'BudgetBolHelp',
    component: () => import('@/views/BudgetBolHelpView.vue'),
    meta: { title: '预算 BOL 帮助' },
  },
  {
    // BOL 审批（动态 BOL 多维分析）
    path: '/dynamic-bol',
    name: 'DynamicBol',
    component: () => import('@/views/DynamicBolView.vue'),
    meta: { title: 'BOL 审批', guestAllowed: true },
  },
  {
    // 实测 CT
    path: '/actual-ct',
    name: 'ActualCT',
    component: () => import('@/views/ActualCtView.vue'),
    meta: { title: '实测 CT', guestAllowed: true },
  },
  {
    // 分析中心 · 多维对比分析
    path: '/analytics/comparison',
    name: 'AnalyticsComparison',
    component: () => import('@/views/analytics/ComparisonView.vue'),
    meta: { title: '对比分析', guestAllowed: true },
  },
  {
    // 系统管理 · 报告中心
    path: '/reports',
    name: 'Reports',
    component: () => import('@/views/ReportsView.vue'),
    meta: { title: '报告中心', guestAllowed: true },
  },
  {
    // 系统管理 · 人员管理（仅管理员）
    path: '/users',
    name: 'Users',
    component: () => import('@/views/UserView.vue'),
    meta: { title: '人员管理', requiresAdmin: true },
  },
  {
    // 账号设置（当前登录用户）
    path: '/account',
    name: 'Account',
    component: () => import('@/views/AccountView.vue'),
    meta: { title: '账号设置' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局前置守卫：登录态与权限校验
router.beforeEach((to) => {
  const { token, user } = authState

  if (token && user?.must_change_password && to.path !== '/account') {
    return { path: '/account', query: { force_password_change: '1' } }
  }

  // 公开页：已登录访问登录页时回首页
  if (to.meta.public) {
    if (token && to.path === '/login') return '/'
    return true
  }

  // 未登录：跳转登录页并带回跳地址
  if (!token) {
    return { path: '/login', query: { redirect: encodeURIComponent(to.fullPath) } }
  }

  // 游客访问受限模块：回门户首页（卡片上已作锁定提示）
  if (user?.role === 'GUEST' && !to.meta.guestAllowed) {
    return '/'
  }

  // 管理员专属模块：非管理员回门户首页
  if (to.meta.requiresAdmin && user?.role !== 'ADMIN') {
    return '/'
  }

  return true
})

export default router

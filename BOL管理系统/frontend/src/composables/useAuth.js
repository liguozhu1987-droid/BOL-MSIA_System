import { computed, readonly } from 'vue'
import { authApi } from '../api'
import { authState, clearAuthState, persistAuth, setAuthPayload } from './authState'

const ROLE_LABELS = {
  ADMIN: '系统管理员',
  IE: 'IE 工程师',
  MGR: '部门经理',
  ENGINEER: '工程师',
  VIEWER: '只读用户',
  GUEST: '游客',
}

export function useAuth() {
  const isAuthenticated = computed(() => !!authState.token && !!authState.user)
  const isAdmin = computed(() => authState.user?.role === 'ADMIN')
  const isGuest = computed(() => authState.user?.role === 'GUEST')
  const roleLabel = computed(() => ROLE_LABELS[authState.user?.role] || authState.user?.role || '')
  const userInitials = computed(() => {
    const name = authState.user?.name || ''
    return name.slice(0, 2) || 'U'
  })

  async function login(credentials) {
    authState.loading = true
    try {
      const data = await authApi.login(credentials)
      setAuthPayload(data)
      return data
    } finally {
      authState.loading = false
    }
  }

  async function guestLogin() {
    authState.loading = true
    try {
      const data = await authApi.guestLogin()
      setAuthPayload(data)
      return data
    } finally {
      authState.loading = false
    }
  }

  // OIDC 统一身份登录回调: 一次性码 (otk) 换本地令牌
  // 响应结构与本地登录一致 ({token, expires_at, user}), 直接走 setAuthPayload
  async function loginWithOtk(otk) {
    authState.loading = true
    try {
      const data = await authApi.oidcToken(otk)
      setAuthPayload(data)
      return data
    } finally {
      authState.loading = false
    }
  }

  async function register(formData) {
    authState.loading = true
    try {
      const data = await authApi.register(formData)
      setAuthPayload(data)
      return data
    } finally {
      authState.loading = false
    }
  }

  async function logout() {
    try {
      if (authState.token) {
        await authApi.logout()
      }
    } catch {
      // 忽略退出时的网络错误
    } finally {
      clearAuthState()
    }
  }

  async function fetchMe() {
    if (!authState.token) return null
    authState.loading = true
    try {
      const user = await authApi.me()
      authState.user = user
      persistAuth()
      return user
    } catch (err) {
      // 仅在后端明确返回 401（令牌无效/过期）时清除登录状态；
      // 网络错误/超时/后端重启等临时故障不应清除本地令牌，
      // 否则会导致"保持登录"失效，用户被迫重新输入密码。
      const status = err?.response?.status
      if (status === 401) {
        clearAuthState()
      }
      return null
    } finally {
      authState.loading = false
    }
  }

  async function changePassword(data) {
    const result = await authApi.changePassword(data)
    await fetchMe()
    return result
  }

  async function updateProfile(data) {
    const user = await authApi.updateProfile(data)
    authState.user = user
    persistAuth()
    return user
  }

  function hasRole(...roles) {
    return roles.includes(authState.user?.role)
  }

  return {
    state: readonly(authState),
    isAuthenticated,
    isAdmin,
    isGuest,
    roleLabel,
    userInitials,
    login,
    guestLogin,
    loginWithOtk,
    register,
    logout,
    fetchMe,
    changePassword,
    updateProfile,
    hasRole,
    getToken: () => authState.token,
    clearAuth: clearAuthState,
  }
}

export { authState }

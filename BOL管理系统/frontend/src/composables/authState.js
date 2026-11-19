import { reactive } from 'vue'

const STORAGE_KEY = 'bol_auth'
const REMEMBERED_USER_KEY = 'bol_remembered_user'

function loadStoredAuth() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

const stored = loadStoredAuth()

function isExpired(expiresAt) {
  if (!expiresAt) return false
  return new Date(expiresAt) <= new Date()
}

function normalizeStoredAuth(data) {
  if (!data?.token || !data?.user) return null
  if (isExpired(data.expiresAt)) return null
  return data
}

const initialAuth = normalizeStoredAuth(stored)

export const authState = reactive({
  token: initialAuth?.token || '',
  expiresAt: initialAuth?.expiresAt || '',
  user: initialAuth?.user || null,
  loading: false,
  // 记住的用户名（用于预填登录表单）
  rememberedUsername: localStorage.getItem(REMEMBERED_USER_KEY) || '',
})

if (stored && !initialAuth) {
  localStorage.removeItem(STORAGE_KEY)
}

export function isAuthExpired() {
  return isExpired(authState.expiresAt)
}

export function persistAuth() {
  if (authState.token && authState.user) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      token: authState.token,
      expiresAt: authState.expiresAt,
      user: authState.user,
    }))
  } else {
    localStorage.removeItem(STORAGE_KEY)
  }
}

export function rememberUsername(username) {
  authState.rememberedUsername = username
  localStorage.setItem(REMEMBERED_USER_KEY, username)
}

export function clearRememberedUsername() {
  authState.rememberedUsername = ''
  localStorage.removeItem(REMEMBERED_USER_KEY)
}

export function setAuthPayload(payload) {
  authState.token = payload.token
  authState.expiresAt = payload.expires_at
  authState.user = payload.user
  persistAuth()
  // 登录成功后记住用户名，方便下次登录预填
  if (payload.user?.username) {
    rememberUsername(payload.user.username)
  }
}

export function clearAuthState() {
  authState.token = ''
  authState.expiresAt = ''
  authState.user = null
  persistAuth()
  // 仅清除令牌，保留用户名供下次登录预填
}

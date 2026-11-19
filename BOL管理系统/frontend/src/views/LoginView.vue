<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '../composables/useAuth'
import { authState } from '@/composables/authState'
import { authApi } from '@/api'

const router = useRouter()
const route = useRoute()
const { login, guestLogin, state } = useAuth()

const formRef = ref()
const form = reactive({
  username: authState.rememberedUsername || '',
  password: '',
  remember: true,
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// 登录页功能开关 (后端 GET /api/auth/config/, 公开端点)
// 拉取失败时保持全 false: 不显示 OIDC 入口与本地表单, 仅游客通道可用
const features = reactive({
  oidc_enabled: false,
  local_auth_enabled: false,
  self_registration_enabled: false,
  password_self_service_enabled: false,
})

// 本地登录折叠面板: OIDC 启用时默认收起 (过渡期保留), 未启用时默认展开
const localCollapse = ref([])

onMounted(async () => {
  document.title = '登录 · BOL管理分析平台'
  try {
    const cfg = await authApi.config()
    features.oidc_enabled = !!cfg.oidc_enabled
    features.local_auth_enabled = !!cfg.local_auth_enabled
    features.self_registration_enabled = !!cfg.self_registration_enabled
    features.password_self_service_enabled = !!cfg.password_self_service_enabled
  } catch {
    // 配置拉取失败: 保持默认 (全 false), 由游客通道兜底
  }
  localCollapse.value = features.oidc_enabled ? [] : ['local']
})

// 统一身份登录: 跳转后端发起 OIDC 授权 (后端 302 到 Keycloak 登录页)
function handleOidcLogin() {
  authApi.oidcLogin()
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  try {
    await login({ username: form.username, password: form.password, remember: form.remember })
    ElMessage.success('登录成功')
    const redirect = route.query.redirect
    router.push(typeof redirect === 'string' ? decodeURIComponent(redirect) : '/')
  } catch {
    // 错误已由 axios 拦截器提示
  }
}

async function handleGuestLogin() {
  try {
    await guestLogin()
    ElMessage.success('已以游客身份进入系统')
    router.push('/')
  } catch {
    // 错误已由 axios 拦截器提示
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-bg"></div>
    <div class="auth-glow"></div>
    <div class="auth-container">
      <el-card class="auth-card" shadow="never">
        <div class="auth-brand">
          <div class="brand-logo">
            <img src="/login-logo.png" alt="Inalfa" />
          </div>
          <h1>BOL 管理分析平台</h1>
          <p class="brand-caption">BILL OF LABOR · MANAGEMENT &amp; ANALYSIS</p>
        </div>

        <p class="auth-subtitle">
          {{ features.oidc_enabled ? '使用公司统一身份账号登录系统' : '使用用户名和密码登录系统' }}
        </p>

        <!-- 统一身份登录 (OIDC/Keycloak): 主入口 -->
        <template v-if="features.oidc_enabled">
          <el-button
            type="primary"
            size="large"
            class="submit-btn oidc-btn"
            @click="handleOidcLogin"
          >
            <el-icon><Key /></el-icon>
            <span>统一身份登录</span>
          </el-button>

          <!-- 本地登录 (过渡期保留): 折叠展示 -->
          <el-collapse v-if="features.local_auth_enabled" v-model="localCollapse" class="local-collapse">
            <el-collapse-item name="local">
              <template #title>
                <span class="local-collapse-title">本地登录（过渡期）</span>
              </template>
              <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
                <el-form-item label="用户名" prop="username">
                  <el-input v-model="form.username" placeholder="请输入用户名" size="large" prefix-icon="User" />
                </el-form-item>
                <el-form-item label="密码" prop="password">
                  <el-input
                    v-model="form.password"
                    type="password"
                    placeholder="请输入密码"
                    size="large"
                    prefix-icon="Lock"
                    show-password
                    @keyup.enter="handleLogin"
                  />
                </el-form-item>
                <el-form-item>
                  <div class="form-row">
                    <el-checkbox v-model="form.remember">保持登录</el-checkbox>
                    <router-link v-if="features.password_self_service_enabled" to="/forgot-password" class="link">忘记密码？</router-link>
                  </div>
                </el-form-item>
                <el-button type="primary" size="large" class="submit-btn" :loading="state.loading" @click="handleLogin">
                  登录
                </el-button>
              </el-form>
            </el-collapse-item>
          </el-collapse>

          <div class="auth-divider"><span>或</span></div>
        </template>

        <!-- 未启用 OIDC 时: 本地登录表单直接展示 (改造前行为) -->
        <el-form v-else-if="features.local_auth_enabled" ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="请输入用户名" size="large" prefix-icon="User" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              prefix-icon="Lock"
              show-password
              @keyup.enter="handleLogin"
            />
          </el-form-item>
          <el-form-item>
            <div class="form-row">
              <el-checkbox v-model="form.remember">保持登录</el-checkbox>
              <router-link v-if="features.password_self_service_enabled" to="/forgot-password" class="link">忘记密码？</router-link>
            </div>
          </el-form-item>
          <el-button type="primary" size="large" class="submit-btn" :loading="state.loading" @click="handleLogin">
            登录
          </el-button>
        </el-form>

        <el-button size="large" class="guest-btn" :loading="state.loading" @click="handleGuestLogin">
          <el-icon><UserFilled /></el-icon>
          游客访问
        </el-button>
      </el-card>

      <div class="auth-footer">
        <span v-if="features.self_registration_enabled">还没有账号？</span>
        <router-link v-if="features.self_registration_enabled" to="/register" class="link">立即注册</router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 32px 20px;
}

.auth-bg {
  position: fixed;
  inset: 0;
  background: url('/login-bg.png') center / cover no-repeat;
  z-index: 0;
}

.auth-bg::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(30, 70, 192, 0.48) 0%, rgba(15, 37, 88, 0.78) 100%);
}

.auth-glow {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 40% 30% at 85% 12%, rgba(15, 181, 186, 0.14) 0%, transparent 65%),
    radial-gradient(ellipse 35% 28% at 10% 85%, rgba(46, 92, 230, 0.16) 0%, transparent 65%);
}

.auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 440px;
  animation: auth-fade-up 0.6s ease-out;
}

.auth-brand {
  margin-bottom: 24px;
  text-align: center;
}

.brand-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  padding: 9px 22px;
  border: 1px solid rgba(46, 92, 230, 0.12);
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(46, 92, 230, 0.07), rgba(15, 181, 186, 0.05));
}

.brand-logo img {
  display: block;
  width: auto;
  height: 48px;
  object-fit: contain;
  filter: drop-shadow(0 2px 6px rgba(46, 92, 230, 0.18));
}

.auth-brand h1 {
  margin: 0;
  color: #1b2540;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.brand-caption {
  margin: 5px 0 0;
  color: #5d6b8a;
  font-family: var(--font-display);
  font-size: 10px;
  letter-spacing: 1.2px;
}

.auth-card {
  position: relative;
  overflow: hidden;
  border: none;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow:
    0 8px 32px rgba(11, 26, 64, 0.22),
    0 24px 64px rgba(11, 26, 64, 0.18),
    0 0 0 1px rgba(255, 255, 255, 0.35);
  backdrop-filter: blur(18px) saturate(170%);
  -webkit-backdrop-filter: blur(18px) saturate(170%);
}

.auth-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 24px;
  right: 24px;
  z-index: 1;
  height: 3px;
  border-radius: 0 0 3px 3px;
  background: linear-gradient(90deg, transparent, #6b93f0 30%, #0fb5ba 50%, #6b93f0 70%, transparent);
  opacity: 0.75;
}

.auth-card :deep(.el-card__body) {
  padding: 32px;
}

.auth-subtitle {
  margin: 0 0 22px;
  color: #5d6b8a;
  font-size: 14px;
  text-align: center;
}

.form-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  font-weight: 600;
}

/* 统一身份登录主按钮: 与本地登录按钮视觉分层 (主色实底) */
.oidc-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 50px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #2e5ce6 0%, #0fb5ba 100%);
  box-shadow: 0 6px 20px rgba(46, 92, 230, 0.32);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 3px;
}

/* 本地登录 (过渡期) 折叠区 */
.local-collapse {
  margin-top: 12px;
  border: none;
}

.local-collapse :deep(.el-collapse-item__header) {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 13px;
  height: 32px;
  line-height: 32px;
  padding: 0 4px;
}

.local-collapse :deep(.el-collapse-item__wrap) {
  border: none;
  background: none;
}

.local-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

.local-collapse-title {
  font-weight: 500;
}

/* "或" 分隔线 */
.auth-divider {
  display: flex;
  align-items: center;
  margin: 20px 0 4px;
  color: var(--color-text-muted);
  font-size: 12px;
}

.auth-divider::before,
.auth-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border);
}

.auth-divider span {
  padding: 0 12px;
}

.guest-btn {
  width: 100%;
  margin-top: 10px;
  margin-left: 0;
  height: 40px;
  color: #5d6b8a;
  border-color: rgba(46, 92, 230, 0.14);
  border-radius: 10px;
}

.guest-btn:hover {
  color: #2e5ce6;
  border-color: #2e5ce6;
}

.auth-footer {
  margin-top: 24px;
  text-align: center;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.82);
}

.link {
  color: #2e5ce6;
  text-decoration: none;
  font-weight: 500;
  margin-left: 4px;
}

.link:hover {
  text-decoration: underline;
}

.auth-footer .link {
  color: #fff;
}

@keyframes auth-fade-up {
  from {
    opacity: 0;
    transform: translateY(16px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 480px) {
  .auth-card :deep(.el-card__body) {
    padding: 28px 22px;
  }

  .auth-brand h1 {
    font-size: 20px;
  }

  .brand-caption {
    font-size: 9px;
  }
}
</style>

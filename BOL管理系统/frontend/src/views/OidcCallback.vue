<script setup>
// OIDC 统一登录回调页
// 后端 302 到此 (/oidc/callback?otk=... 一次性码 或 ?error=... 失败原因):
//   error → 展示失败原因 + 返回登录页链接
//   otk   → 一次性码换本地令牌 (POST /api/auth/oidc/token/) → 进系统
//   都无  → 直接回登录页
// 注意: otk 60s 单次消费, 刷新页面会消费失败 → 提示返回登录页重登
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '../composables/useAuth'

const route = useRoute()
const router = useRouter()
const { loginWithOtk } = useAuth()

const errorText = ref('')
const exchanging = ref(false)
// 组件实例级防重入: otk 单次消费, 避免任何重复触发导致二次兑换失败
let handled = false

onMounted(async () => {
  document.title = '正在登录 · BOL管理分析平台'
  if (handled) return
  handled = true

  const otk = route.query.otk
  const error = route.query.error

  if (error) {
    errorText.value = typeof error === 'string' ? error : '统一登录失败，请重试'
    return
  }
  if (!otk || typeof otk !== 'string') {
    router.replace('/login')
    return
  }

  exchanging.value = true
  try {
    await loginWithOtk(otk)
    ElMessage.success('登录成功')
    const redirect = route.query.redirect
    router.replace(typeof redirect === 'string' ? decodeURIComponent(redirect) : '/')
  } catch {
    // 具体错误已由响应拦截器统一提示, 这里补充重试入口
    errorText.value = '登录凭证无效或已过期，请返回登录页重新登录'
  } finally {
    exchanging.value = false
  }
})
</script>

<template>
  <div class="auth-page">
    <div class="auth-bg"></div>
    <div class="auth-container">
      <div class="auth-brand">
        <div class="brand-mark">B</div>
        <div>
          <h1>BOL 管理分析平台</h1>
          <p>Bill of Labor · 统一身份登录</p>
        </div>
      </div>

      <el-card class="auth-card" shadow="never">
        <!-- 失败态: 展示原因 + 返回登录页 -->
        <div v-if="errorText" class="oidc-result">
          <el-icon class="result-icon result-warning"><WarningFilled /></el-icon>
          <h2 class="auth-title">统一登录失败</h2>
          <p class="auth-subtitle">{{ errorText }}</p>
          <el-button type="primary" size="large" class="submit-btn" @click="router.replace('/login')">
            返回登录页
          </el-button>
        </div>

        <!-- 处理中:  spinner + 提示 -->
        <div v-else class="oidc-result">
          <el-icon class="is-loading result-icon"><Loading /></el-icon>
          <h2 class="auth-title">{{ exchanging ? '正在完成统一登录' : '正在跳转' }}</h2>
          <p class="auth-subtitle">请稍候…</p>
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  padding: 24px;
}

.auth-bg {
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse at 20% 20%, rgba(37, 99, 235, 0.12) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(139, 92, 246, 0.08) 0%, transparent 50%),
    var(--color-bg);
  z-index: 0;
}

.auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
}

.brand-mark {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--gradient-primary);
  color: #fff;
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.3);
}

.auth-brand h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.auth-brand p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

.auth-card {
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
}

.auth-card :deep(.el-card__body) {
  padding: 32px;
}

.oidc-result {
  text-align: center;
  padding: 12px 0;
}

.result-icon {
  font-size: 40px;
  margin-bottom: 16px;
}

.result-warning {
  color: var(--el-color-warning, #e6a23c);
}

.oidc-result .result-icon.is-loading {
  color: var(--color-primary);
}

.auth-title {
  margin: 0 0 6px;
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
}

.auth-subtitle {
  margin: 0 0 24px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  font-weight: 600;
}
</style>

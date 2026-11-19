<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '../api'

const router = useRouter()
const formRef = ref()
const loading = ref(false)
const resetInfo = ref(null)

// 密码自助服务开关 (R14): PASSWORD_SELF_SERVICE_ENABLED=false 时展示关闭提示 (后端接口返回 403)
const passwordServiceOpen = ref(true)
const configLoaded = ref(false)

const form = reactive({
  username: '',
  email: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入注册邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const data = await authApi.forgotPassword(form)
    resetInfo.value = data
    ElMessage.success(data.detail || '请求已提交')
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function goReset() {
  if (resetInfo.value?.reset_token) {
    router.push(`/reset-password?token=${resetInfo.value.reset_token}`)
  } else {
    router.push('/reset-password')
  }
}

onMounted(async () => {
  // 拉取功能开关 (失败按关闭处理, 与登录页口径一致)
  try {
    const cfg = await authApi.config()
    passwordServiceOpen.value = !!cfg.password_self_service_enabled
  } catch {
    passwordServiceOpen.value = false
  } finally {
    configLoaded.value = true
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
          <h1>忘记密码</h1>
          <p>验证用户名与注册邮箱以重置密码</p>
        </div>
      </div>

      <el-card class="auth-card" shadow="never">
        <template v-if="configLoaded && !passwordServiceOpen">
          <h2 class="auth-title">密码自助服务已关闭</h2>
          <p class="auth-subtitle">请在统一身份平台自助修改或重置密码。</p>
          <el-button type="primary" size="large" class="submit-btn" @click="router.push('/login')">
            返回登录
          </el-button>
        </template>

        <template v-else-if="!resetInfo">
          <h2 class="auth-title">找回密码</h2>
          <p class="auth-subtitle">请输入注册时使用的用户名和邮箱</p>

          <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleSubmit">
            <el-form-item label="用户名" prop="username">
              <el-input v-model="form.username" placeholder="请输入用户名" size="large" />
            </el-form-item>
            <el-form-item label="邮箱" prop="email">
              <el-input v-model="form.email" placeholder="注册邮箱" size="large" />
            </el-form-item>
            <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="handleSubmit">
              发送重置请求
            </el-button>
          </el-form>
        </template>

        <template v-else>
          <el-result icon="success" :title="resetInfo.detail">
            <template #sub-title>
              <p v-if="resetInfo.expires_at">链接有效期至 {{ new Date(resetInfo.expires_at).toLocaleString('zh-CN') }}</p>
              <p v-if="resetInfo.reset_token" class="dev-hint">
                开发模式：已生成重置令牌，点击下方按钮继续
              </p>
            </template>
            <template #extra>
              <el-button type="primary" @click="goReset">前往重置密码</el-button>
              <el-button @click="router.push('/login')">返回登录</el-button>
            </template>
          </el-result>
        </template>

        <div v-if="!resetInfo" class="auth-footer">
          <router-link to="/login" class="link">← 返回登录</router-link>
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
  padding: 24px;
  position: relative;
}

.auth-bg {
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse at 30% 30%, rgba(245, 158, 11, 0.1) 0%, transparent 50%),
    var(--color-bg);
  z-index: 0;
}

.auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 440px;
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
  background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%);
  color: #fff;
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.auth-brand h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
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

.auth-title {
  margin: 0 0 6px;
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
}

.auth-subtitle {
  margin: 0 0 24px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.submit-btn {
  width: 100%;
  font-weight: 600;
}

.auth-footer {
  margin-top: 20px;
  text-align: center;
}

.link {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}

.dev-hint {
  color: var(--color-warning);
  font-size: 13px;
  margin-top: 8px;
}
</style>

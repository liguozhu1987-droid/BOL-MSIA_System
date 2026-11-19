<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '../composables/useAuth'
import { authApi } from '../api'

const router = useRouter()
const { register, state } = useAuth()

// 自助注册开关 (R7): SELF_REGISTRATION_ENABLED=false 时展示关闭提示 (后端注册接口返回 403)
const registrationOpen = ref(true)
const configLoaded = ref(false)

const formRef = ref()
const form = reactive({
  username: '',
  name: '',
  email: '',
  phone: '',
  department: '',
  title: '',
  password: '',
  password_confirm: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
  password_confirm: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== form.password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function handleRegister() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  try {
    await register({ ...form })
    ElMessage.success('注册成功，已自动登录')
    router.push('/')
  } catch {
    // 错误已由拦截器处理
  }
}

onMounted(async () => {
  // 拉取功能开关 (失败按关闭处理, 与登录页口径一致)
  try {
    const cfg = await authApi.config()
    registrationOpen.value = !!cfg.self_registration_enabled
  } catch {
    registrationOpen.value = false
  } finally {
    configLoaded.value = true
  }
})
</script>

<template>
  <div class="auth-page">
    <div class="auth-bg"></div>
    <div class="auth-container wide">
      <div class="auth-brand">
        <div class="brand-mark">B</div>
        <div>
          <h1>BOL 管理分析平台</h1>
          <p>创建您的账号</p>
        </div>
      </div>

      <el-card class="auth-card" shadow="never">
        <h2 class="auth-title">用户注册</h2>
        <p class="auth-subtitle">注册后默认为只读用户，管理员可调整权限</p>

        <el-alert
          v-if="configLoaded && !registrationOpen"
          title="自助注册已关闭"
          description="账号请联系管理员开通，或使用统一身份登录。"
          type="info"
          :closable="false"
          show-icon
          class="closed-alert"
        />
        <el-form v-else ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleRegister">
          <div class="form-grid">
            <el-form-item label="用户名" prop="username">
              <el-input v-model="form.username" placeholder="登录用户名" />
            </el-form-item>
            <el-form-item label="姓名" prop="name">
              <el-input v-model="form.name" placeholder="真实姓名" />
            </el-form-item>
            <el-form-item label="邮箱" prop="email">
              <el-input v-model="form.email" placeholder="用于找回密码" />
            </el-form-item>
            <el-form-item label="电话" prop="phone">
              <el-input v-model="form.phone" placeholder="选填" />
            </el-form-item>
            <el-form-item label="部门" prop="department">
              <el-input v-model="form.department" placeholder="选填" />
            </el-form-item>
            <el-form-item label="职位" prop="title">
              <el-input v-model="form.title" placeholder="选填" />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="form.password" type="password" show-password placeholder="至少 8 位" />
            </el-form-item>
            <el-form-item label="确认密码" prop="password_confirm">
              <el-input v-model="form.password_confirm" type="password" show-password placeholder="再次输入密码" />
            </el-form-item>
          </div>

          <el-button type="primary" size="large" class="submit-btn" :loading="state.loading" @click="handleRegister">
            注册
          </el-button>
        </el-form>

        <div class="auth-footer">
          <span>已有账号？</span>
          <router-link to="/login" class="link">返回登录</router-link>
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
    radial-gradient(ellipse at 80% 80%, rgba(16, 185, 129, 0.08) 0%, transparent 50%),
    var(--color-bg);
  z-index: 0;
}

.auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
}

.auth-container.wide {
  max-width: 560px;
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

.closed-alert {
  margin-bottom: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  font-weight: 600;
}

.auth-footer {
  margin-top: 24px;
  text-align: center;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.link {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
  margin-left: 4px;
}

@media (max-width: 600px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '../api'

const route = useRoute()
const router = useRouter()
const formRef = ref()
const loading = ref(false)

const form = reactive({
  token: '',
  new_password: '',
  new_password_confirm: '',
})

const rules = {
  token: [{ required: true, message: '请输入重置令牌', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
  new_password_confirm: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== form.new_password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

onMounted(() => {
  if (route.query.token) {
    form.token = route.query.token
  }
})

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authApi.resetPassword(form)
    ElMessage.success('密码重置成功，请登录')
    router.push('/login')
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-bg"></div>
    <div class="auth-container">
      <el-card class="auth-card" shadow="never">
        <h2 class="auth-title">重置密码</h2>
        <p class="auth-subtitle">输入邮件中的重置令牌并设置新密码</p>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleSubmit">
          <el-form-item label="重置令牌" prop="token">
            <el-input v-model="form.token" placeholder="从邮件或管理员处获取" size="large" />
          </el-form-item>
          <el-form-item label="新密码" prop="new_password">
            <el-input v-model="form.new_password" type="password" show-password size="large" />
          </el-form-item>
          <el-form-item label="确认新密码" prop="new_password_confirm">
            <el-input v-model="form.new_password_confirm" type="password" show-password size="large" />
          </el-form-item>
          <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="handleSubmit">
            确认重置
          </el-button>
        </el-form>

        <div class="auth-footer">
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
  background: var(--color-bg);
  z-index: 0;
}

.auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
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
</style>

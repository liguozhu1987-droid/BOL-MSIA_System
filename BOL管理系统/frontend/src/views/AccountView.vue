<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/PageHeader.vue'
import { useAuth } from '../composables/useAuth'
import { authApi } from '@/api'

const { state, updateProfile, changePassword, roleLabel } = useAuth()
const mustChangePassword = computed(() => !!state.user?.must_change_password)

// 密码自助服务开关 (R14): PASSWORD_SELF_SERVICE_ENABLED=false 时改密区块隐藏,
// 密码生命周期移交 Keycloak 控制台。must_change_password 用户仍展示,
// 避免被守卫锁在 /account 无任何可用操作 (提交时后端会返回 403 指引)。
const passwordServiceOpen = ref(true)
const showPasswordCard = computed(() => passwordServiceOpen.value || mustChangePassword.value)

const profileFormRef = ref()
const passwordFormRef = ref()
const profileLoading = ref(false)
const passwordLoading = ref(false)

const profileForm = reactive({
  name: '',
  email: '',
  phone: '',
  department: '',
  title: '',
})

const passwordForm = reactive({
  old_password: '',
  new_password: '',
  new_password_confirm: '',
})

const passwordRules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
  new_password_confirm: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.new_password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

onMounted(async () => {
  if (state.user) {
    Object.assign(profileForm, {
      name: state.user.name,
      email: state.user.email,
      phone: state.user.phone || '',
      department: state.user.department || '',
      title: state.user.title || '',
    })
  }
  // 拉取功能开关 (失败按关闭处理, 与登录页口径一致)
  try {
    const cfg = await authApi.config()
    passwordServiceOpen.value = !!cfg.password_self_service_enabled
  } catch {
    passwordServiceOpen.value = false
  }
})

async function saveProfile() {
  const valid = await profileFormRef.value?.validate().catch(() => false)
  if (!valid) return

  profileLoading.value = true
  try {
    await updateProfile({ ...profileForm })
    ElMessage.success('资料已更新')
  } finally {
    profileLoading.value = false
  }
}

async function savePassword() {
  const valid = await passwordFormRef.value?.validate().catch(() => false)
  if (!valid) return

  passwordLoading.value = true
  try {
    await changePassword({ ...passwordForm })
    ElMessage.success('密码修改成功')
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordForm.new_password_confirm = ''
    passwordFormRef.value?.resetFields()
  } finally {
    passwordLoading.value = false
  }
}
</script>

<template>
  <div class="account-page">
    <PageHeader
      title="账号设置"
      subtitle="管理个人资料与登录密码"
      icon="UserFilled"
      :breadcrumbs="[{ label: '主页', to: '/' }, { label: '账号设置' }]"
    />

    <div class="page-content">
      <el-alert
        v-if="mustChangePassword"
        title="请先修改初始密码"
        description="为保护账号安全，修改密码前暂时无法使用系统其他功能。"
        type="warning"
        :closable="false"
        show-icon
        class="force-password-alert"
      />
      <div class="info-card card">
        <div class="info-row">
          <span class="label">用户名</span>
          <span class="value text-mono">{{ state.user?.username }}</span>
        </div>
        <div class="info-row">
          <span class="label">角色</span>
          <el-tag type="primary" size="small">{{ roleLabel }}</el-tag>
        </div>
        <div class="info-row">
          <span class="label">状态</span>
          <el-tag :type="state.user?.status === 'ACTIVE' ? 'success' : 'info'" size="small">
            {{ state.user?.status === 'ACTIVE' ? '在职' : '停用' }}
          </el-tag>
        </div>
        <div v-if="state.user?.last_login" class="info-row">
          <span class="label">上次登录</span>
          <span class="value">{{ new Date(state.user.last_login).toLocaleString('zh-CN') }}</span>
        </div>
      </div>

      <div
        class="settings-grid"
        :class="{
          'password-required': mustChangePassword,
          'single-column': !showPasswordCard && !mustChangePassword,
        }"
      >
        <el-card v-if="!mustChangePassword" class="setting-card" shadow="never">
          <template #header>
            <span class="card-title">个人资料</span>
          </template>
          <el-form ref="profileFormRef" :model="profileForm" label-position="top">
            <el-form-item label="姓名" prop="name" :rules="[{ required: true, message: '请输入姓名' }]">
              <el-input v-model="profileForm.name" />
            </el-form-item>
            <el-form-item label="邮箱" prop="email" :rules="[{ required: true, type: 'email', message: '请输入有效邮箱' }]">
              <el-input v-model="profileForm.email" />
            </el-form-item>
            <el-form-item label="电话">
              <el-input v-model="profileForm.phone" />
            </el-form-item>
            <el-form-item label="部门">
              <el-input v-model="profileForm.department" />
            </el-form-item>
            <el-form-item label="职位">
              <el-input v-model="profileForm.title" />
            </el-form-item>
            <el-button type="primary" :loading="profileLoading" @click="saveProfile">保存资料</el-button>
          </el-form>
        </el-card>

        <el-card v-if="showPasswordCard" class="setting-card" shadow="never">
          <template #header>
            <span class="card-title">{{ mustChangePassword ? '设置新密码' : '修改密码' }}</span>
          </template>
          <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-position="top">
            <el-form-item :label="mustChangePassword ? '初始密码' : '原密码'" prop="old_password">
              <el-input v-model="passwordForm.old_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="新密码" prop="new_password">
              <el-input v-model="passwordForm.new_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="确认新密码" prop="new_password_confirm">
              <el-input v-model="passwordForm.new_password_confirm" type="password" show-password />
            </el-form-item>
            <el-button type="primary" :loading="passwordLoading" @click="savePassword">
              {{ mustChangePassword ? '确认并进入系统' : '修改密码' }}
            </el-button>
          </el-form>
        </el-card>
      </div>
    </div>
  </div>
</template>

<style scoped>
.account-page {
  min-height: 100vh;
}

.page-content {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px;
}

.force-password-alert {
  margin-bottom: 20px;
}

.info-card {
  padding: 20px 24px;
  margin-bottom: 24px;
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.info-row .label {
  font-size: 13px;
  color: var(--color-text-muted);
  min-width: 64px;
}

.info-row .value {
  font-size: 14px;
  font-weight: 500;
}

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.settings-grid.password-required {
  grid-template-columns: minmax(0, 500px);
}

/* 改密区块隐藏 (R14) 时, 资料卡片独占一行 */
.settings-grid.single-column {
  grid-template-columns: minmax(0, 500px);
}

.setting-card {
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
}

.card-title {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 15px;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>

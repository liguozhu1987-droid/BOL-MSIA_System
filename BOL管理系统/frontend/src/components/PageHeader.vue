<script setup>
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuth } from '../composables/useAuth'
import { useRealtimeClock } from '../composables/useRealtimeClock'

const props = defineProps({
  title: {
    type: String,
    required: true
  },
  // 可选副标题/描述
  subtitle: {
    type: String,
    default: ''
  },
  // 模块图标 (Element Plus 图标名)
  icon: {
    type: String,
    default: ''
  },
  // 可选右侧操作区域（slot）
  // 可选面包屑：[{ label, to }]
  breadcrumbs: {
    type: Array,
    default: () => []
  }
})

const router = useRouter()
const { state, roleLabel, logout, isAuthenticated } = useAuth()

function goHome() {
  router.push('/')
}

function goBack() {
  // 优先使用历史返回，回退到主页
  if (window.history.length > 1) {
    router.back()
  } else {
    goHome()
  }
}

// 当前时间显示（实时刷新，每分钟一次）
const { dateTimeStr } = useRealtimeClock()

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await logout()
    router.push('/login')
  } catch {
    // 用户取消
  }
}

function goAccount() {
  router.push('/account')
}
</script>

<template>
  <header class="page-header">
    <!-- 顶部一行：品牌 + 时间 + 用户 -->
    <div class="header-top">
      <div class="header-top-inner">
        <div class="brand" @click="goHome">
          <div class="brand-mark">
            <span>B</span>
          </div>
          <div class="brand-text">
            <div class="brand-title">BOL 管理分析平台</div>
            <div class="brand-sub">Bill of Labor · v0.4</div>
          </div>
        </div>

        <div class="header-right">
          <div class="time-display">
            <span class="time-dot"></span>
            <span class="text-mono">{{ dateTimeStr }}</span>
          </div>
          <span class="env-tag">
            <span class="env-dot"></span>
            <span>内网</span>
          </span>
          <template v-if="isAuthenticated">
            <el-dropdown trigger="click" @command="(cmd) => cmd === 'account' ? goAccount() : handleLogout()">
              <span class="user-chip clickable">
                <span class="user-text">{{ state.user?.name }} · {{ roleLabel }}</span>
                <el-icon class="user-chevron"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="account">
                    <el-icon><Setting /></el-icon>
                    账号设置
                  </el-dropdown-item>
                  <el-dropdown-item command="logout" divided>
                    <el-icon><SwitchButton /></el-icon>
                    退出登录
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <router-link v-else to="/login" class="login-link">登录</router-link>
        </div>
      </div>
    </div>

    <!-- 模块标题栏 -->
    <div class="header-bar">
      <div class="header-bar-inner">
        <div class="header-left">
          <button class="back-btn" @click="goHome" title="返回主页">
            <el-icon><HomeFilled /></el-icon>
            <span>主页</span>
          </button>
          <div class="divider"></div>
          <nav v-if="breadcrumbs.length" class="breadcrumbs">
            <template v-for="(crumb, idx) in breadcrumbs" :key="idx">
              <span v-if="idx > 0" class="crumb-sep">/</span>
              <router-link v-if="crumb.to" :to="crumb.to" class="crumb">{{ crumb.label }}</router-link>
              <span v-else class="crumb current">{{ crumb.label }}</span>
            </template>
          </nav>
          <h1 class="header-title">
            <div v-if="icon" class="title-icon-wrap">
              <el-icon class="title-icon"><component :is="icon" /></el-icon>
            </div>
            <span>{{ title }}</span>
          </h1>
        </div>

        <div class="header-actions">
          <slot name="actions" />
        </div>
      </div>
    </div>

    <!-- 副标题 -->
    <div v-if="subtitle" class="header-subtitle">{{ subtitle }}</div>
  </header>
</template>

<style scoped>
.page-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.82);
  border-bottom: 1px solid var(--color-border);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

/* 顶部一行：品牌 + 时间 + 用户 */
.header-top {
  background: linear-gradient(90deg, rgba(240, 247, 255, 0.80) 0%, rgba(227, 236, 245, 0.85) 50%, rgba(240, 247, 255, 0.80) 100%);
  border-bottom: 1px solid var(--color-border);
  position: relative;
}

.header-top::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--gradient-primary);
  opacity: 0.8;
}

.header-top-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 24px;
  max-width: 1600px;
  margin: 0 auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: opacity var(--transition-fast);
}

.brand:hover {
  opacity: 0.85;
}

.brand-mark {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--gradient-primary);
  color: #ffffff;
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px rgba(14, 165, 233, 0.3);
  position: relative;
}

.brand-mark::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(255,255,255,0.2) 0%, transparent 50%);
}

.brand-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: 0;
  line-height: 1.2;
}

.brand-sub {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-text-muted);
  margin-top: 2px;
  letter-spacing: 0.02em;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.time-display {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
  letter-spacing: 0;
}

.time-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.5);
}

.env-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  padding: 3px 9px;
  background: rgba(16, 185, 129, 0.1);
  color: var(--color-success);
  border-radius: 100px;
  border: 1px solid rgba(16, 185, 129, 0.25);
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.env-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-success);
}

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px;
  background: var(--color-primary-glow);
  border: 1px solid rgba(14, 165, 233, 0.18);
  border-radius: 100px;
}

.user-text {
  font-size: 12px;
  color: var(--color-primary);
  font-weight: 500;
}

.user-chip.clickable {
  cursor: pointer;
  transition: all var(--transition-fast);
}

.user-chip.clickable:hover {
  border-color: var(--color-primary);
  background: rgba(14, 165, 233, 0.08);
}

.user-chevron {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-left: 2px;
}

.login-link {
  font-size: 13px;
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
  padding: 6px 14px;
  border: 1px solid rgba(14, 165, 233, 0.25);
  border-radius: 100px;
}

/* 模块标题栏 */
.header-bar {
  background: transparent;
}

.header-bar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  gap: 16px;
  max-width: 1600px;
  margin: 0 auto;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--color-surface);
  border: 1px solid var(--color-border-bright);
  color: var(--color-text-secondary);
  padding: 7px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-body);
}

.back-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-glow);
  transform: translateX(-2px);
}

.divider {
  width: 1px;
  height: 22px;
  background: var(--color-border);
}

.breadcrumbs {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.crumb {
  color: var(--color-text-secondary);
  transition: color var(--transition-fast);
}

a.crumb:hover {
  color: var(--color-primary);
}

.crumb.current {
  color: var(--color-text);
  font-weight: 500;
}

.crumb-sep {
  color: var(--color-text-dim);
}

.header-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 12px;
  letter-spacing: -0.02em;
}

.title-icon-wrap {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--gradient-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 3px 8px rgba(37, 99, 235, 0.25);
}

.title-icon {
  font-size: 16px;
  color: #fff;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-subtitle {
  padding: 0 24px 14px;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  max-width: 1600px;
  margin: 0 auto;
}

/* 响应式：窄屏 */
@media (max-width: 768px) {
  .header-top-inner,
  .header-bar-inner {
    padding-left: 16px;
    padding-right: 16px;
  }

  .brand-text {
    display: none;
  }

  .header-bar-inner {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .header-left {
    flex-wrap: wrap;
  }

  .time-display,
  .user-text {
    display: none;
  }
}
</style>

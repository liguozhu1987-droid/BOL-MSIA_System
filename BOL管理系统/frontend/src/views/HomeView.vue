<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuth } from '../composables/useAuth'
import { useRealtimeClock } from '../composables/useRealtimeClock'

const router = useRouter()
const { state, roleLabel, logout, isAdmin, isGuest } = useAuth()

// 时间（实时刷新，每分钟一次）
const { dateTimeStr: currentTime } = useRealtimeClock()

// ---- 模块定义 ----
// 分为「核心模块」（大卡片）和「工具模块」（小卡片），形成视觉层级
// 每个模块有专属色系 + 渐变 + 阴影（引用 main.css 设计令牌，禁止硬编码色值）
// guestAllowed: 游客是否可访问
const featuredModules = [
  {
    key: 'dashboard',
    title: '综合看板',
    desc: '跨数据源汇总，按工艺维度分析 BOL 分布与跟踪状态',
    icon: 'Odometer',
    color: 'var(--color-blue-deep)',
    gradient: 'var(--gradient-blue-deep)',
    shadow: 'var(--shadow-blue-strong)',
    badge: '核心',
    route: '/dashboard',
    guestAllowed: true
  },
  {
    key: 'tracking',
    title: '高 BOL 跟踪',
    desc: '问题识别 → 改善任务分配 → 验证关闭，形成管理闭环',
    icon: 'Aim',
    color: 'var(--color-rose)',
    gradient: 'var(--gradient-danger)',
    shadow: 'var(--shadow-rose-strong)',
    badge: '闭环',
    route: '/tracking',
    alert: true,
    guestAllowed: false
  }
]

const toolModules = [
  {
    key: 'budget-bol',
    title: '预算 BOL',
    desc: '年度预算管理，Excel 模板批量导入',
    icon: 'Coin',
    color: 'var(--color-amber)',
    gradient: 'var(--gradient-accent)',
    route: '/budget-bol',
    guestAllowed: false
  },
  {
    key: 'dynamic-bol',
    title: 'BOL 审批',
    desc: '审批变更历史，按工艺/地点/Roof Type 多维分析',
    icon: 'DataLine',
    color: 'var(--color-blue-mid)',
    gradient: 'var(--gradient-blue-mid)',
    route: '/dynamic-bol',
    guestAllowed: true
  },
  {
    key: 'actual-ct',
    title: '实测 CT',
    desc: '传感器采集 cycle time 原始数据',
    icon: 'Cpu',
    color: 'var(--color-cyan)',
    gradient: 'var(--gradient-cyan)',
    route: '/actual-ct',
    guestAllowed: true
  },
  {
    key: 'analytics',
    title: '分析中心',
    desc: '综合多维度 BOL 分析（工艺×RoofType×工厂×财年）',
    icon: 'DataAnalysis',
    color: 'var(--color-violet)',
    gradient: 'var(--gradient-violet)',
    route: '/analytics/comparison',
    guestAllowed: true
  },
  {
    key: 'users',
    title: '系统管理',
    desc: '人员名册管理、权限设置 · 季度/年度 BOL 分析报告中心',
    icon: 'Setting',
    color: 'var(--color-emerald)',
    gradient: 'var(--gradient-success)',
    route: '/reports',
    guestAllowed: true
  }
]

// 判断模块对当前用户是否可访问
function isModuleAccessible(mod) {
  if (!isGuest.value) return true
  return !!mod.guestAllowed
}

async function enterModule(mod) {
  if (isGuest.value && !mod.guestAllowed) {
    try {
      await ElMessageBox.confirm(
        '该模块需要注册登录后才能访问，是否前往登录？',
        '游客权限受限',
        {
          confirmButtonText: '前往登录',
          cancelButtonText: '继续浏览',
          type: 'warning',
        }
      )
      await logout()
      router.push('/login')
    } catch {
      // 用户选择继续浏览
    }
    return
  }
  router.push(mod.route)
}

const visibleToolModules = computed(() => toolModules)

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
</script>

<template>
  <div class="home">
    <!-- Hero：品牌标识 - 带渐变背景与玻璃质感 -->
    <section class="hero">
      <div class="hero-bg"></div>
      <div class="hero-inner">
        <div class="hero-brand">
          <div class="brand-head">
            <div class="brand-titles">
              <div class="brand-tag">
                <span class="brand-tag-dot"></span>
                <span>BOL · Bill of Labor</span>
              </div>
              <h1 class="brand-title">BOL 管理分析平台</h1>
              <p class="brand-sub">人力工时预算多维管理与改善闭环 · 双库路由 · IE 工业工程数字中枢</p>
              <div class="brand-meta">
                <div class="brand-formula">
                  <span class="formula-label">公式</span>
                  <span class="formula-text">BOL = CT × HC × (1+1/15) / OEE / 60</span>
                </div>
                <div class="brand-time">
                  <span class="time-dot"></span>
                  {{ currentTime }}
                </div>
                <el-dropdown trigger="click" @command="(cmd) => cmd === 'account' ? router.push('/account') : handleLogout()">
                  <div class="home-user-chip">
                    <span>{{ state.user?.name }} · {{ roleLabel }}</span>
                    <el-icon><ArrowDown /></el-icon>
                  </div>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="account">账号设置</el-dropdown-item>
                      <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </div>
            <div class="brand-logo-wrap">
              <img src="/logo.png" alt="IRS Europe" class="brand-logo" />
              <div class="logo-glow"></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 模块导航 -->
    <section class="modules">
      <!-- 区段标题 -->
      <div class="section-title">
        <div class="section-title-bar"></div>
        <div class="section-title-text">
          <h2>核心模块</h2>
          <span>每日高频使用的关键能力</span>
        </div>
      </div>

      <!-- 核心模块：2 张大卡片 -->
      <div class="featured-row">
        <article
          v-for="(mod, idx) in featuredModules"
          :key="mod.key"
          class="featured-card"
          :class="[
            `anim-fade-up delay-${idx + 1}`,
            { 'card-locked': isGuest && !mod.guestAllowed }
          ]"
          :style="{
            '--card-color': mod.color,
            '--card-gradient': mod.gradient,
            '--card-shadow': mod.shadow
          }"
          @click="enterModule(mod)"
        >
          <div class="fcard-bg"></div>
          <div class="fcard-content">
            <div class="fcard-head">
              <div class="fcard-icon">
                <el-icon :size="24"><component :is="mod.icon" /></el-icon>
              </div>
              <span class="fcard-badge" :class="{ 'badge-alert': mod.alert }">{{ mod.badge }}</span>
            </div>
            <div class="fcard-body">
              <h2 class="fcard-title">
                {{ mod.title }}
                <el-icon v-if="isGuest && !mod.guestAllowed" class="lock-icon"><Lock /></el-icon>
              </h2>
              <p class="fcard-desc">{{ mod.desc }}</p>
            </div>
            <div class="fcard-footer">
              <span class="fcard-enter">
                {{ isGuest && !mod.guestAllowed ? '需登录' : '进入模块' }}
                <el-icon><ArrowRight /></el-icon>
              </span>
              <span class="fcard-arrow-line"></span>
            </div>
          </div>
        </article>
      </div>

      <!-- 区段标题 -->
      <div class="section-title">
        <div class="section-title-bar amber"></div>
        <div class="section-title-text">
          <h2>工具模块</h2>
          <span>数据管理与分析辅助</span>
        </div>
      </div>

      <!-- 工具模块：小卡片 -->
      <div class="tool-row">
        <article
          v-for="(mod, idx) in visibleToolModules"
          :key="mod.key"
          class="tool-card"
          :class="[
            `anim-fade-up delay-${(idx % 5) + 2}`,
            { 'card-locked': isGuest && !mod.guestAllowed }
          ]"
          :style="{
            '--card-color': mod.color,
            '--card-gradient': mod.gradient
          }"
          @click="enterModule(mod)"
        >
          <div class="tcard-accent"></div>
          <div class="tcard-top">
            <div class="tcard-icon-wrap">
              <el-icon class="tcard-icon" :size="20"><component :is="mod.icon" /></el-icon>
            </div>
            <el-icon v-if="isGuest && !mod.guestAllowed" class="lock-icon-small"><Lock /></el-icon>
            <el-icon v-else class="tcard-arrow"><ArrowRight /></el-icon>
          </div>
          <h3 class="tcard-title">{{ mod.title }}</h3>
          <p class="tcard-desc">{{ mod.desc }}</p>
          <div class="tcard-bottom-line"></div>
        </article>
      </div>
    </section>

    <!-- 底部 -->
    <footer class="home-footer">
      <div class="footer-inner">
        <span class="footer-brand">BOL · v0.4</span>
        <span class="footer-sep">·</span>
        <span class="footer-text">HRDB 只读 + CMC 读写 · 双库路由 · 改善闭环 · Refined Industrial Dashboard</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.home {
  min-height: 100%;
  background: transparent;
}

/* ============================================================
   Hero - 渐变背景 + 玻璃质感
   ============================================================ */
.hero {
  position: relative;
  padding: 0;
  overflow: hidden;
  border-bottom: 1px solid var(--color-border);
}

.hero-bg {
  position: absolute;
  inset: 0;
  background: var(--gradient-hero-glow);
  backdrop-filter: blur(2px);
}

.hero-bg::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.04 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  opacity: 0.6;
  mix-blend-mode: multiply;
}

.hero-inner {
  position: relative;
  max-width: 1400px;
  margin: 0 auto;
}

.hero-brand {
  padding: 48px 40px 40px;
}

.brand-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 32px;
}

.brand-titles {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.brand-tag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  background: var(--color-primary-glow);
  border: 1px solid var(--color-blue-deep-soft);
  border-radius: 100px;
  width: fit-content;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-primary);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.brand-tag-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-blue-deep-glow);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--color-blue-deep-glow); }
  50% { box-shadow: 0 0 0 6px var(--color-blue-deep-faint); }
}

.brand-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 36px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: -0.03em;
  line-height: 1.1;
  background: var(--gradient-brand-text);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.brand-sub {
  margin: 0;
  font-size: 14px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  font-weight: 500;
  max-width: 540px;
}

.brand-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.brand-formula {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 100px;
  box-shadow: var(--shadow-sm);
}

.formula-label {
  font-size: 10px;
  color: var(--color-text-muted);
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 2px 6px;
  background: var(--color-accent-glow);
  color: var(--color-accent);
  border-radius: 4px;
}

.formula-text {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-text);
  font-weight: 500;
  letter-spacing: 0.02em;
}

.brand-time {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.time-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 8px var(--color-success-glow);
}

.brand-logo-wrap {
  position: relative;
  flex-shrink: 0;
}

.brand-logo {
  max-width: 220px;
  max-height: 160px;
  width: auto;
  height: auto;
  object-fit: contain;
  position: relative;
  z-index: 2;
}

.logo-glow {
  position: absolute;
  inset: -20px;
  background: radial-gradient(circle, var(--color-blue-deep-soft) 0%, transparent 70%);
  filter: blur(20px);
  z-index: 1;
}

/* ============================================================
   Modules
   ============================================================ */
.modules {
  padding: 36px 40px 40px;
  max-width: 1400px;
  margin: 0 auto;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
  margin-top: 12px;
}

.section-title:first-child {
  margin-top: 0;
}

.section-title-bar {
  width: 4px;
  height: 22px;
  background: var(--gradient-primary);
  border-radius: 2px;
}

.section-title-bar.amber {
  background: var(--gradient-accent);
}

.section-title-text {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.section-title-text h2 {
  /* 对齐三层标题规范 H2（.title-h2 同款口径） */
  margin: 0;
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.section-title-text span {
  font-size: 12px;
  color: var(--color-text-muted);
}

.featured-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 32px;
}

.featured-card {
  position: relative;
  padding: 28px 32px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition) var(--ease-out);
  overflow: hidden;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow);
}

.featured-card:hover {
  border-color: var(--card-color);
  box-shadow: var(--card-shadow);
  transform: translateY(-3px);
}

/* 游客锁定卡片样式 */
.card-locked {
  opacity: 0.6;
  filter: grayscale(0.4);
}

.card-locked:hover {
  transform: none;
  box-shadow: var(--shadow);
}

.lock-icon {
  font-size: 16px;
  color: var(--color-text-muted);
  margin-left: 6px;
  vertical-align: middle;
}

.lock-icon-small {
  font-size: 18px;
  color: var(--color-text-muted);
  margin-left: auto;
}

.fcard-bg {
  position: absolute;
  top: -40px;
  right: -40px;
  width: 200px;
  height: 200px;
  background: var(--card-gradient);
  opacity: 0.08;
  border-radius: 50%;
  filter: blur(40px);
  transition: all var(--transition-slow);
}

.featured-card:hover .fcard-bg {
  opacity: 0.18;
  transform: scale(1.2);
}

.fcard-content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  height: 100%;
  justify-content: space-between;
  flex: 1;
}

.fcard-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.fcard-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: var(--card-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-inverse);
  flex-shrink: 0;
  box-shadow: var(--shadow-icon);
  transition: all var(--transition);
}

.featured-card:hover .fcard-icon {
  transform: scale(1.08) rotate(-4deg);
  box-shadow: var(--shadow-icon-hover);
}

.fcard-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  background: var(--card-color);
  color: var(--color-text-inverse);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  border-radius: 100px;
  opacity: 0.85;
}

.fcard-badge.badge-alert {
  animation: badgePulse 2.4s infinite;
}

@keyframes badgePulse {
  0%, 100% { opacity: 0.85; }
  50% { opacity: 1; box-shadow: 0 0 0 6px var(--color-rose-soft); }
}

.fcard-body {
  flex: 1;
}

.fcard-title {
  margin: 0 0 8px;
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: -0.02em;
}

.fcard-desc {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.65;
  max-width: 380px;
}

.fcard-footer {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.fcard-enter {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--card-color);
  transition: all var(--transition);
}

.featured-card:hover .fcard-enter {
  gap: 10px;
}

.fcard-arrow-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, var(--color-border) 50%, transparent 100%);
  margin-left: 16px;
}

.tool-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.tool-card {
  position: relative;
  padding: 22px 22px 20px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--transition) var(--ease-out);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.tool-card:hover {
  border-color: var(--card-color);
  box-shadow: var(--shadow-lg);
  transform: translateY(-3px);
}

.tool-card:hover .tcard-accent {
  transform: scaleX(1);
}

.tool-card:hover .tcard-icon-wrap {
  background: var(--card-gradient);
  color: var(--color-text-inverse);
  transform: scale(1.06);
}

.tool-card:hover .tcard-arrow {
  opacity: 1;
  transform: translateX(0);
}

.tool-card:hover .tcard-bottom-line {
  background: var(--card-gradient);
}

.tcard-accent {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--card-gradient);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--transition-slow) var(--ease-out);
}

.tcard-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.tcard-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--color-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--card-color);
  transition: all var(--transition);
}

.tcard-icon {
  transition: color var(--transition);
}

.tcard-arrow {
  font-size: 14px;
  color: var(--card-color);
  opacity: 0;
  transform: translateX(-4px);
  transition: all var(--transition);
}

.tcard-title {
  margin: 0 0 6px;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.tcard-desc {
  margin: 0 0 14px;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.tcard-bottom-line {
  height: 2px;
  background: var(--color-border);
  border-radius: 1px;
  transition: background var(--transition);
}

/* ============================================================
   Footer
   ============================================================ */
.home-footer {
  padding: 18px 40px;
  border-top: 1px solid var(--color-border);
  background: var(--gradient-footer-veil);
}

.footer-inner {
  display: flex;
  align-items: center;
  max-width: 1400px;
  margin: 0 auto;
}

.footer-brand {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  color: var(--color-primary);
  letter-spacing: 0.02em;
}

.footer-sep {
  margin: 0 10px;
  color: var(--color-text-dim);
}

.footer-text {
  font-size: 11px;
  color: var(--color-text-muted);
  letter-spacing: 0.02em;
}

/* ============================================================
   Responsive
   ============================================================ */
@media (max-width: 1280px) {
  .tool-row {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .hero-brand {
    padding: 28px 20px;
  }
  .brand-head {
    gap: 16px;
    flex-direction: column;
    align-items: flex-start;
  }
  .brand-logo {
    max-width: 140px;
    max-height: 90px;
  }
  .brand-title {
    font-size: 26px;
  }
  .modules {
    padding: 24px 16px;
  }
  .featured-row {
    grid-template-columns: 1fr;
    gap: 14px;
    margin-bottom: 24px;
  }
  .tool-row {
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .home-footer {
    padding: 14px 20px;
  }
}
</style>

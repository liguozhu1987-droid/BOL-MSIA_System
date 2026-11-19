<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter, useRoute } from 'vue-router'
import { reportApi } from '@/api'
import { formatDateTime } from '@/utils/format'
import { useAuth } from '@/composables/useAuth'
import PageHeader from '@/components/PageHeader.vue'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'

const router = useRouter()
const route = useRoute()
const { isAdmin } = useAuth()

// --- 子模块导航（系统管理 · Tab） ---
const sysTabs = [
  { key: 'reports', label: '报告中心', icon: 'Document', route: '/reports' },
  { key: 'users', label: '人员管理', icon: 'User', route: '/users', adminOnly: true },
  { key: 'account', label: '账号设置', icon: 'UserFilled', route: '/account' }
]
const activeTab = ref('reports')
watch(() => route.path, (p) => {
  if (p.startsWith('/reports')) activeTab.value = 'reports'
  else if (p.startsWith('/users')) activeTab.value = 'users'
  else if (p.startsWith('/account')) activeTab.value = 'account'
}, { immediate: true })

function switchTab(tab) {
  if (tab.adminOnly && !isAdmin.value) {
    ElMessage.warning('该子模块仅管理员可访问')
    return
  }
  router.push(tab.route)
}

// ---- 列表数据 ----
const tableData = ref([])
const loading = ref(false)

// 筛选条件
const filters = reactive({
  report_type: '',
  year: '',
  search: ''
})

const typeOptions = [
  { label: '季度报告', value: 'QUARTERLY' },
  { label: '年度报告', value: 'ANNUAL' }
]

// 年份选项：当前年份 ~ 2024（系统上线年份）倒序
const currentYear = new Date().getFullYear()
const yearOptions = []
for (let y = currentYear; y >= 2024; y--) yearOptions.push(y)

// 统计卡片
const stats = computed(() => {
  const total = tableData.value.length
  const quarterly = tableData.value.filter((r) => r.report_type === 'QUARTERLY').length
  const annual = tableData.value.filter((r) => r.report_type === 'ANNUAL').length
  const latest = tableData.value.reduce((acc, r) => {
    const t = r.updated_at || r.created_at
    return !acc || (t && t > acc) ? t : acc
  }, '')
  return { total, quarterly, annual, latest }
})

async function loadList() {
  loading.value = true
  try {
    const params = {}
    if (filters.report_type) params.report_type = filters.report_type
    if (filters.year) params.year = filters.year
    if (filters.search) params.search = filters.search.trim()
    const res = await reportApi.list(params)
    tableData.value = res.results || []
  } catch (e) {
    // 错误已由拦截器统一提示
  } finally {
    loading.value = false
  }
}

function handleReset() {
  filters.report_type = ''
  filters.year = ''
  filters.search = ''
  loadList()
}

// ---- 查阅（对话框内 iframe 渲染完整 HTML 快照） ----
const viewVisible = ref(false)
const viewLoading = ref(false)
const exportingPdf = ref(false)
const viewTitle = ref('')
const viewHtml = ref('')
const viewRowId = ref(null)
const iframeRef = ref(null)

async function openView(row) {
  viewTitle.value = row.title
  viewRowId.value = row.id
  viewVisible.value = true
  viewLoading.value = true
  viewHtml.value = ''
  try {
    const detail = await reportApi.retrieve(row.id)
    viewHtml.value = detail.html || ''
  } catch (e) {
    // ignore
  } finally {
    viewLoading.value = false
  }
  // 让 iframe 引用在下一轮渲染后可用
  await nextTick()
}

// ---- 将 iframe 中已渲染的内容 → A4 分页 PDF ----
// 逐页渲染，避免长年度报告超过浏览器单张 canvas 的尺寸上限。
async function exportViewPdf() {
  if (!viewHtml.value || !iframeRef.value) {
    ElMessage.warning('报告内容尚未加载完成，请稍候再试')
    return
  }
  const doc = iframeRef.value.contentDocument || iframeRef.value.contentWindow?.document
  if (!doc || !doc.body || doc.body.childElementCount === 0) {
    ElMessage.warning('报告尚未渲染完成，请稍候再试')
    return
  }
  exportingPdf.value = true
  try {
    // A4 尺寸：210mm × 297mm → jsPDF 默认 pt 单位（1pt = 1/72 inch ≈ 0.353mm）
    const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' })
    const pageW = pdf.internal.pageSize.getWidth()   // ≈ 210
    const pageH = pdf.internal.pageSize.getHeight()  // ≈ 297
    const root = doc.documentElement
    const pageWidth = Math.max(root.scrollWidth, doc.body.scrollWidth, root.clientWidth)
    const pageHeight = Math.max(root.scrollHeight, doc.body.scrollHeight)
    const pageHeightCss = pageH * pageWidth / pageW
    const breakpoints = Array.from(doc.querySelectorAll(
      '.report-header, .chart-box, .chart-legend-hint, .table-wrap tr, .insight-box, .warn-box, .empty-box, li, .report-footer'
    ))
      .map((element) => element.getBoundingClientRect().bottom + root.scrollTop)
      .filter((bottom) => bottom > 0 && bottom < pageHeight)
      .sort((a, b) => a - b)

    let y = 0
    let pageIndex = 0
    while (y < pageHeight) {
      const maxY = Math.min(y + pageHeightCss, pageHeight)
      let endY = maxY
      if (maxY < pageHeight) {
        const minY = y + pageHeightCss * 0.55
        for (const breakpoint of breakpoints) {
          if (breakpoint > minY && breakpoint <= maxY) endY = breakpoint
          if (breakpoint > maxY) break
        }
      }
      const height = endY - y
      // html2canvas only allocates this page's canvas instead of one canvas for the full report.
      const canvas = await html2canvas(root, {
        scale: 1.5,
        useCORS: true,
        allowTaint: true,
        backgroundColor: '#ffffff',
        logging: false,
        x: 0,
        y,
        width: pageWidth,
        height,
        windowWidth: pageWidth,
        windowHeight: pageHeight,
        scrollX: 0,
        scrollY: 0,
      })
      const pageImg = canvas.toDataURL('image/jpeg', 0.92)
      if (pageIndex > 0) pdf.addPage()
      pdf.addImage(pageImg, 'JPEG', 0, 0, pageW, (canvas.height * pageW) / canvas.width)
      y = endY
      pageIndex++
    }

    const safeName = (viewTitle.value || 'BOL分析报告').replace(/[\\/:*?"<>|]/g, '_')
    pdf.save(`${safeName}.pdf`)
    ElMessage.success(`PDF 已导出（${pageIndex} 页）`)
  } catch (e) {
    console.error(e)
    ElMessage.error('PDF 导出失败：' + (e?.message || e))
  } finally {
    exportingPdf.value = false
  }
}

// ---- 列表操作列直接导出（不打开查阅） ----
async function handleExportPdf(row) {
  // 先确保内容加载并渲染完成：复用 openView 逻辑但不显示对话框？
  // 直接用查阅对话框加载：打开 → 等 iframe 渲染 → 导出 → 关闭
  await openView(row)
  // iframe 需要时间渲染 ECharts 等内容，等待一个较长的安全窗口
  await new Promise((resolve) => setTimeout(resolve, 2500))
  await exportViewPdf()
  viewVisible.value = false
}

// ---- 浏览器打印（可选回退方案，质量更高但需手动保存） ----
async function printView() {
  if (!iframeRef.value) {
    ElMessage.warning('报告尚未加载完成')
    return
  }
  const wnd = iframeRef.value.contentWindow
  if (!wnd) {
    ElMessage.warning('无法获取报告窗口')
    return
  }
  try {
    const doc = wnd.document
    let printStyles = doc.getElementById('report-print-pagination')
    if (!printStyles) {
      printStyles = doc.createElement('style')
      printStyles.id = 'report-print-pagination'
      printStyles.textContent = `
        @media print {
          .section { break-inside: auto !important; page-break-inside: auto !important; }
          .section h2, .section h3 { break-after: avoid; page-break-after: avoid; }
          .table-wrap { overflow: visible !important; }
          thead { position: static !important; display: table-header-group; }
          tr { break-inside: avoid; page-break-inside: avoid; }
        }
      `
      doc.head.appendChild(printStyles)
    }
    wnd.focus()
    wnd.print()
  } catch (e) {
    ElMessage.error('打印失败：' + (e?.message || e))
  }
}

// ---- 下载 HTML 报告文件（完整快照，离线可查阅） ----
// 表格操作列与查阅对话框均可触发；若查阅对话框已加载同一条报告则直接复用内容
async function downloadReportHtml(row) {
  const title = row?.title || viewTitle.value
  const id = row?.id || viewRowId.value
  if (!id) return
  let html = ''
  if (viewRowId.value === id && viewHtml.value) {
    html = viewHtml.value
  } else {
    try {
      const detail = await reportApi.retrieve(id)
      html = detail.html || ''
    } catch (e) {
      return
    }
  }
  if (!html) {
    ElMessage.warning('报告内容为空，无法下载')
    return
  }
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(title || 'BOL分析报告').replace(/[\\/:*?"<>|]/g, '_')}.html`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  ElMessage.success('HTML 报告已下载')
}

// ---- 邮件推送报告（仅管理员，HTML 以附件发送） ----
const emailVisible = ref(false)
const emailSending = ref(false)
const emailRow = ref(null)
const emailForm = reactive({ recipients: '', message: '' })

function openEmail(row) {
  emailRow.value = row
  emailForm.recipients = ''
  emailForm.message = ''
  emailVisible.value = true
}

async function handleSendEmail() {
  const recipients = emailForm.recipients
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!recipients.length) {
    ElMessage.warning('请填写至少一个收件人邮箱')
    return
  }
  emailSending.value = true
  try {
    const res = await reportApi.email(emailRow.value.id, {
      recipients,
      message: emailForm.message
    })
    ElMessage.success(res.detail || '邮件已发送')
    emailVisible.value = false
  } catch (e) {
    // ignore
  } finally {
    emailSending.value = false
  }
}

// ---- 删除（仅管理员） ----
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除报告「${row.title}」吗？删除后不可恢复。`,
      '删除报告',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await reportApi.remove(row.id)
    ElMessage.success('报告已删除')
    loadList()
  } catch (e) {
    // ignore
  }
}

// ---- 手动生成（仅管理员） ----
const genVisible = ref(false)
const generating = ref(false)
const currentQuarter = Math.floor(new Date().getMonth() / 3) + 1
const genForm = reactive({
  report_type: 'QUARTERLY',
  year: currentYear,
  quarter: currentQuarter
})

function openGenerate() {
  genForm.report_type = 'QUARTERLY'
  genForm.year = currentYear
  genForm.quarter = currentQuarter
  genVisible.value = true
}

async function handleGenerate() {
  if (genForm.report_type === 'QUARTERLY' && !genForm.quarter) {
    ElMessage.warning('请选择季度')
    return
  }
  generating.value = true
  try {
    const res = await reportApi.generate({
      report_type: genForm.report_type,
      year: genForm.year,
      quarter: genForm.report_type === 'QUARTERLY' ? genForm.quarter : null
    })
    ElMessage.success(res.detail || '报告已生成')
    genVisible.value = false
    loadList()
  } catch (e) {
    // ignore
  } finally {
    generating.value = false
  }
}

function typeTagType(t) {
  return t === 'QUARTERLY' ? 'primary' : 'warning'
}

onMounted(() => {
  loadList()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="系统管理"
      icon="Setting"
      subtitle="系统模块：人员名册与权限管理、季度/年度 BOL 分析报告中心（自动生成、查阅、下载与邮件推送）。"
      :breadcrumbs="[{ label: '系统管理' }, { label: '报告中心' }]"
    >
      <template #actions>
        <el-button v-if="isAdmin" type="primary" @click="openGenerate">
          <el-icon><MagicStick /></el-icon>
          <span>手动生成</span>
        </el-button>
      </template>
    </PageHeader>

    <div class="page-container">
      <!-- 子模块导航 Tab -->
      <div class="sys-tabs">
        <button
          v-for="tab in sysTabs"
          :key="tab.key"
          class="sys-tab"
          :class="{
            'is-active': activeTab === tab.key,
            'is-locked': tab.adminOnly && !isAdmin
          }"
          @click="switchTab(tab)"
        >
          <el-icon class="tab-icon"><component :is="tab.icon" /></el-icon>
          <span>{{ tab.label }}</span>
          <el-icon v-if="tab.adminOnly && !isAdmin" class="lock-icon"><Lock /></el-icon>
        </button>
      </div>

      <!-- 统计卡片 -->
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-label">报告总数</div>
          <div class="stat-value">{{ stats.total }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">季度报告</div>
          <div class="stat-value">{{ stats.quarterly }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">年度报告</div>
          <div class="stat-value">{{ stats.annual }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">最近生成</div>
          <div class="stat-value stat-time">{{ stats.latest ? formatDateTime(stats.latest) : '—' }}</div>
        </div>
      </div>

      <!-- 自动生成说明 -->
      <el-alert
        class="schedule-alert"
        type="info"
        :closable="false"
        show-icon
      >
        <template #title>
          系统自动生成计划：季度报告于每季首日 02:00 生成上一完整季度；年度报告于每年 1 月 1 日 03:00 生成上一年度。报告为生成时点的数据快照，不随源数据变化。
        </template>
      </el-alert>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-input
          v-model="filters.search"
          placeholder="标题关键词"
          clearable
          style="width: 200px"
          @keyup.enter="loadList"
          @clear="loadList"
        />
        <el-select v-model="filters.report_type" placeholder="报告类型" clearable style="width: 150px">
          <el-option v-for="opt in typeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select v-model="filters.year" placeholder="年份" clearable style="width: 120px">
          <el-option v-for="y in yearOptions" :key="y" :label="y + ' 年'" :value="y" />
        </el-select>
        <el-button type="primary" @click="loadList">
          <el-icon><Search /></el-icon>
          <span>查询</span>
        </el-button>
        <el-button @click="handleReset">
          <el-icon><Refresh /></el-icon>
          <span>重置</span>
        </el-button>
      </div>

      <!-- 表格 -->
      <div class="table-container">
        <el-table :data="tableData" stripe border size="small" style="width: 100%">
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag :type="typeTagType(row.report_type)" size="small">{{ row.report_type_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="period_label" label="周期" width="90" />
          <el-table-column prop="title" label="报告标题" min-width="240" show-overflow-tooltip />
          <el-table-column label="数据区间" width="200">
            <template #default="{ row }">{{ row.period_start }} ~ {{ row.period_end }}</template>
          </el-table-column>
          <el-table-column prop="generated_by" label="生成人" width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ row.generated_by || '—' }}</template>
          </el-table-column>
          <el-table-column label="生成时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.updated_at || row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="大小" width="90" align="right">
            <template #default="{ row }">{{ row.html_size_kb }} KB</template>
          </el-table-column>
          <el-table-column label="操作" width="330" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openView(row)">查阅</el-button>
              <el-button link size="small" @click="downloadReportHtml(row)">下载HTML</el-button>
              <el-button type="success" link size="small" @click="handleExportPdf(row)">导出PDF</el-button>
              <el-button v-if="isAdmin" link size="small" @click="openEmail(row)">邮件推送</el-button>
              <el-button v-if="isAdmin" type="danger" link size="small" @click="handleDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !tableData.length" description="暂无报告，等待系统按周期自动生成，或由管理员手动生成" />
      </div>
    </div>

    <!-- 报告查阅对话框：iframe 渲染独立 HTML 快照（含内联 ECharts） -->
    <el-dialog
      v-model="viewVisible"
      :title="viewTitle"
      fullscreen
      destroy-on-close
      class="report-view-dialog"
    >
      <template #header="{ close }">
        <div class="report-dialog-header">
          <span class="report-dialog-title">{{ viewTitle }}</span>
          <div class="report-dialog-actions">
            <el-button size="small" @click="downloadReportHtml()">
              <el-icon><Download /></el-icon>
              <span>下载 HTML</span>
            </el-button>
            <el-button :loading="exportingPdf" type="success" size="small" @click="exportViewPdf">
              <el-icon><Download /></el-icon>
              <span>{{ exportingPdf ? '导出中…' : '导出 PDF' }}</span>
            </el-button>
            <el-button size="small" @click="printView">
              <el-icon><Printer /></el-icon>
              <span>打印</span>
            </el-button>
            <el-button size="small" @click="close">
              <el-icon><Close /></el-icon>
              <span>关闭</span>
            </el-button>
          </div>
        </div>
      </template>

      <div v-loading="viewLoading || exportingPdf" class="report-frame-wrap">
        <iframe
          v-if="viewHtml"
          ref="iframeRef"
          :srcdoc="viewHtml"
          class="report-frame"
          title="报告内容"
        />
      </div>
    </el-dialog>

    <!-- 邮件推送对话框（仅管理员） -->
    <el-dialog
      v-model="emailVisible"
      title="邮件推送报告"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form label-width="90px" size="default">
        <el-form-item label="报告">
          <span class="email-report-title">{{ emailRow?.title }}</span>
        </el-form-item>
        <el-form-item label="收件人" required>
          <el-input
            v-model="emailForm.recipients"
            type="textarea"
            :rows="3"
            placeholder="多个邮箱用逗号、分号或换行分隔，例如：zhang@company.com, li@company.com"
          />
        </el-form-item>
        <el-form-item label="附言">
          <el-input
            v-model="emailForm.message"
            type="textarea"
            :rows="2"
            placeholder="可选，将作为邮件正文附言"
          />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="报告以 HTML 附件形式发送，收件人用浏览器打开附件即可查阅图表。"
      />
      <template #footer>
        <el-button @click="emailVisible = false">取消</el-button>
        <el-button type="primary" :loading="emailSending" @click="handleSendEmail">
          {{ emailSending ? '发送中…' : '发送' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 手动生成对话框（仅管理员） -->
    <el-dialog
      v-model="genVisible"
      title="手动生成报告"
      width="460px"
      :close-on-click-modal="false"
    >
      <el-form :model="genForm" label-width="90px" size="default">
        <el-form-item label="报告类型">
          <el-radio-group v-model="genForm.report_type">
            <el-radio value="QUARTERLY">季度报告</el-radio>
            <el-radio value="ANNUAL">年度报告</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="年份">
          <el-input-number v-model="genForm.year" :min="2020" :max="2100" :step="1" step-strictly />
        </el-form-item>
        <el-form-item v-if="genForm.report_type === 'QUARTERLY'" label="季度">
          <el-select v-model="genForm.quarter" style="width: 180px">
            <el-option label="Q1（1-3月）" :value="1" />
            <el-option label="Q2（4-6月）" :value="2" />
            <el-option label="Q3（7-9月）" :value="3" />
            <el-option label="Q4（10-12月）" :value="4" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="handleGenerate">
          {{ generating ? '正在生成（跨库取数，请稍候）…' : '开始生成' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 子模块导航 Tab */
.sys-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  padding: 4px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.sys-tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: calc(var(--radius) - 2px);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-body);
}

.sys-tab:hover {
  background: var(--color-primary-glow);
  color: var(--color-primary);
}

.sys-tab.is-active {
  background: var(--color-primary);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 3px 8px rgba(14, 165, 233, 0.3);
}

.sys-tab.is-locked {
  opacity: 0.5;
  cursor: not-allowed;
}

.sys-tab.is-locked:hover {
  background: transparent;
  color: var(--color-text-secondary);
}

.tab-icon {
  font-size: 15px;
}

.lock-icon {
  font-size: 12px;
  opacity: 0.8;
}

/* 统计卡片 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

/* stat-card / stat-label / stat-value 统一由 main.css 全局规范接管 */

.stat-time {
  font-size: 16px;
  font-family: var(--font-mono);
}

/* 自动生成说明 */
.schedule-alert {
  margin-bottom: 16px;
}

/* 邮件推送对话框：报告标题 */
.email-report-title {
  font-weight: 600;
  color: var(--color-text);
}

/* 报告查阅：iframe 铺满对话框 */
.report-frame-wrap {
  height: calc(100vh - 110px);
  background: var(--color-surface);
}

.report-frame {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}

/* 查阅对话框自定义标题栏 */
.report-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 4px;
}

.report-dialog-title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.report-dialog-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .sys-tabs {
    overflow-x: auto;
  }
  .sys-tab {
    white-space: nowrap;
  }
}
</style>

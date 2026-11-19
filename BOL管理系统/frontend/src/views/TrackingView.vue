<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { trackingApi, userApi } from '@/api'
import { formatBol, formatCurrency, formatDate, formatDateTime } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import { mintGradient, dangerGradient, aggregate, buildValueLabelConfig, adaptiveBarLayout } from '@/utils/echartsTheme'

// 筛选条件
const filters = reactive({
  status: '',
  issue_type: '',
  location: '',
  owner: '',
  priority: ''
})

const statusOptions = [
  { label: '全部', value: '' },
  { label: '待处理', value: 'OPEN' },
  { label: '改善中', value: 'IN_PROGRESS' },
  { label: '已达成', value: 'ACHIEVED' },
  { label: '已验证', value: 'VERIFIED' },
  { label: '已关闭', value: 'CLOSED' },
  { label: '已重新打开', value: 'REOPENED' }
]

const issueTypeOptions = [
  { label: '全部', value: '' },
  { label: 'QWS差距', value: 'QWS_GAP' },
  { label: '预算差距', value: 'BUDGET_GAP' },
  { label: '其他', value: 'OTHER' }
]

const priorityOptions = [
  { label: '全部', value: '' },
  { label: '高', value: 'HIGH' },
  { label: '中', value: 'MEDIUM' },
  { label: '低', value: 'LOW' }
]

const improvementTypeOptions = [
  { label: '设备投资', value: 'CAPEX' },
  { label: '运营优化', value: 'OPEX' },
  { label: '工艺改进', value: 'PROCESS' },
  { label: '人员调整', value: 'STAFFING' },
  { label: '其他', value: 'OTHER' }
]

// 变更类型：ECR / 过程变更
const changeTypeOptions = [
  { label: 'ECR', value: 'ECR' },
  { label: '过程变更', value: 'PROCESS_CHANGE' }
]

// 费用承担方
const paidByOptions = [
  { label: 'customer', value: 'CUSTOMER' },
  { label: 'internal', value: 'INTERNAL' }
]

// 变更原因
const changeReasonOptions = [
  { label: 'design', value: 'DESIGN' },
  { label: 'quality', value: 'QUALITY' },
  { label: 'VAVE', value: 'VAVE' },
  { label: 'manufacturing', value: 'MANUFACTURING' },
  { label: '其他', value: 'OTHER' }
]

// 工厂（标准化短码）
const plantOptions = [
  { label: 'CJ', value: 'CJ' },
  { label: 'BJ', value: 'BJ' },
  { label: 'SH', value: 'SH' },
  { label: 'CQ', value: 'CQ' },
  { label: 'WH', value: 'WH' },
  { label: 'GZ', value: 'GZ' }
]

// 表格数据
const tableData = ref([])
const loading = ref(false)
const pagination = reactive({
  page: 1,
  pageSize: 15,
  total: 0
})

const pagedData = computed(() => {
  const start = (pagination.page - 1) * pagination.pageSize
  return tableData.value.slice(start, start + pagination.pageSize)
})

// 责任人下拉
const ownerOptions = ref([])

// 跟踪记录对话框
const trackDialogVisible = ref(false)
const trackDialogMode = ref('create')
const trackSubmitting = ref(false)
const editingTrackId = ref(null)

const defaultTrackForm = () => ({
  program_code: '',
  program_name: '',
  customer: '',
  location: '',
  process: '',
  line_nr: '',
  issue_type: 'OTHER',
  current_bol: 0,
  target_bol: 0,
  target_source: 'BUDGET',
  annual_volume: 0,
  labor_rate: 0,
  priority: 'MEDIUM',
  change_type: '',
  paid_by: '',
  change_reason: '',
  root_cause: '',
  improvement_action: '',
  improvement_plan: '',
  improvement_type: '',
  owner: '',
  owner_name: '',
  target_date: '',
  remark: ''
})
const trackForm = reactive(defaultTrackForm())

const bolVariance = computed(() => {
  return Number(trackForm.current_bol) - Number(trackForm.target_bol)
})

// 项目编号检索（来源 cbco_records，默认取当前年份的下一年）
const programSuggestions = ref([])
const programLoading = ref(false)

async function searchPrograms(queryString, cb) {
  const q = (queryString || '').trim()
  if (!q) {
    programSuggestions.value = []
    cb([])
    return
  }
  programLoading.value = true
  try {
    const res = await trackingApi.searchPrograms({ q })
    const items = (res && res.items) || []
    // el-autocomplete 需要 value 字段作为显示文本
    programSuggestions.value = items.map((it) => ({
      ...it,
      value: `${it.program_number}${it.program_description ? ' · ' + it.program_description : ''}${it.customer ? ' · ' + it.customer : ''}`
    }))
    cb(programSuggestions.value)
  } catch (e) {
    programSuggestions.value = []
    cb([])
  } finally {
    programLoading.value = false
  }
}

// 选中项目后自动回填：项目名称、客户、工厂、年产量
function handleProgramSelect(item) {
  trackForm.program_code = item.program_number || trackForm.program_code
  trackForm.program_name = item.program_description || ''
  trackForm.customer = item.customer || ''
  // 工厂使用标准化短码；若返回值不在选项中则原样保留
  trackForm.location = item.irs_location || ''
  trackForm.annual_volume = Number(item.volume || 0)
}

// 手动清空项目编号时同步清空回填字段
function handleProgramClear() {
  trackForm.program_name = ''
  trackForm.customer = ''
  trackForm.annual_volume = 0
}

// 状态流转对话框
const flowDialogVisible = ref(false)
const flowType = ref('')  // assign | start | achieve | verify | close | reopen
const flowSubmitting = ref(false)
const flowRow = ref(null)
const flowForm = reactive({
  owner: '',
  owner_name: '',
  target_date: '',
  operator_id: '',
  operator_name: '',
  bol_after: 0,
  progress: 100,
  verify_comment: '',
  reopen_reason: ''
})

const flowDialogTitle = computed(() => {
  const map = {
    assign: '分派负责人',
    start: '开始改善',
    achieve: '达成改善',
    verify: '验证通过',
    close: '关闭任务',
    reopen: '重新打开'
  }
  return map[flowType.value] || '状态流转'
})

// 闭环时间线对话框
const timelineDialogVisible = ref(false)
const timelineLoading = ref(false)
const timelineRow = ref(null)
const timelineNodes = ref([])

// 进度日志对话框
const logDialogVisible = ref(false)
const logLoading = ref(false)
const logSubmitting = ref(false)
const currentTrack = ref(null)
const logList = ref([])

const defaultLogForm = () => ({
  action: '',
  bol_after: 0,
  progress: 0,
  log_by: '',
  log_by_name: ''
})
const logForm = reactive(defaultLogForm())

async function loadTracking() {
  loading.value = true
  try {
    const params = {}
    if (filters.status) params.status = filters.status
    if (filters.issue_type) params.issue_type = filters.issue_type
    if (filters.location) params.location = filters.location
    if (filters.owner) params.owner = filters.owner
    if (filters.priority) params.priority = filters.priority
    const res = await trackingApi.list(params)
    const list = Array.isArray(res) ? res : (res.results || [])
    tableData.value = list
    pagination.total = list.length
    pagination.page = 1
  } catch (e) {
    // ignore
  } finally {
    loading.value = false
  }
}

async function loadOwners() {
  try {
    const res = await userApi.active()
    ownerOptions.value = Array.isArray(res) ? res : []
  } catch (e) {
    ownerOptions.value = []
  }
}

function handleSearch() {
  loadTracking()
}

function handleReset() {
  filters.status = ''
  filters.issue_type = ''
  filters.location = ''
  filters.owner = ''
  filters.priority = ''
  loadTracking()
}

function openCreateTrack() {
  trackDialogMode.value = 'create'
  editingTrackId.value = null
  Object.assign(trackForm, defaultTrackForm())
  trackDialogVisible.value = true
}

function openEditTrack(row) {
  trackDialogMode.value = 'edit'
  editingTrackId.value = row.id
  Object.assign(trackForm, {
    program_code: row.program_code || '',
    program_name: row.program_name || '',
    customer: row.customer || '',
    location: row.location || '',
    process: row.process || '',
    line_nr: row.line_nr || '',
    issue_type: row.issue_type || 'OTHER',
    current_bol: Number(row.current_bol || 0),
    target_bol: Number(row.target_bol || 0),
    target_source: row.target_source || 'BUDGET',
    annual_volume: Number(row.annual_volume || 0),
    labor_rate: Number(row.labor_rate || 0),
    priority: row.priority || 'MEDIUM',
    change_type: row.change_type || '',
    paid_by: row.paid_by || '',
    change_reason: row.change_reason || '',
    root_cause: row.root_cause || '',
    improvement_action: row.improvement_action || '',
    improvement_plan: row.improvement_plan || '',
    improvement_type: row.improvement_type || '',
    owner: row.owner || '',
    owner_name: row.owner_name || '',
    target_date: row.target_date ? String(row.target_date).slice(0, 10) : '',
    remark: row.remark || ''
  })
  trackDialogVisible.value = true
}

async function handleTrackSubmit() {
  if (!trackForm.program_code) {
    ElMessage.warning('请填写项目代码')
    return
  }
  trackSubmitting.value = true
  try {
    const payload = { ...trackForm }
    if (trackDialogMode.value === 'create') {
      await trackingApi.create(payload)
      ElMessage.success('创建成功')
    } else {
      await trackingApi.update(editingTrackId.value, payload)
      ElMessage.success('更新成功')
    }
    trackDialogVisible.value = false
    loadTracking()
  } catch (e) {
    // ignore
  } finally {
    trackSubmitting.value = false
  }
}

async function handleDeleteTrack(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除项目 ${row.program_code} 的跟踪记录吗？`,
      '删除确认',
      { type: 'warning' }
    )
    await trackingApi.remove(row.id)
    ElMessage.success('删除成功')
    loadTracking()
  } catch (e) {
    // 用户取消
  }
}

// ============ 状态流转 ============
function openFlowDialog(type, row) {
  flowType.value = type
  flowRow.value = row
  Object.assign(flowForm, {
    owner: row.owner || '',
    owner_name: row.owner_name || '',
    target_date: row.target_date ? String(row.target_date).slice(0, 10) : '',
    operator_id: '',
    operator_name: '',
    bol_after: Number(row.current_bol || 0),
    progress: type === 'achieve' ? 100 : (row.progress || 0),
    verify_comment: '',
    reopen_reason: ''
  })
  flowDialogVisible.value = true
}

async function handleFlowSubmit() {
  if (!flowRow.value) return
  const id = flowRow.value.id
  flowSubmitting.value = true
  try {
    const payload = { ...flowForm }
    if (flowType.value === 'assign') {
      await trackingApi.assign(id, payload)
    } else if (flowType.value === 'start') {
      await trackingApi.start(id, payload)
    } else if (flowType.value === 'achieve') {
      await trackingApi.achieve(id, payload)
    } else if (flowType.value === 'verify') {
      await trackingApi.verify(id, payload)
    } else if (flowType.value === 'close') {
      await trackingApi.close(id, payload)
    } else if (flowType.value === 'reopen') {
      await trackingApi.reopen(id, payload)
    }
    ElMessage.success(`${flowDialogTitle.value}成功`)
    flowDialogVisible.value = false
    loadTracking()
  } catch (e) {
    // ignore
  } finally {
    flowSubmitting.value = false
  }
}

// 责任人下拉变更
function handleOwnerChange(val) {
  const opt = ownerOptions.value.find((o) => o.username === val)
  if (opt) {
    flowForm.owner_name = opt.name
  }
}

// ============ 时间线 ============
async function openTimelineDialog(row) {
  timelineRow.value = row
  timelineDialogVisible.value = true
  timelineLoading.value = true
  try {
    const res = await trackingApi.timeline(row.id)
    timelineNodes.value = Array.isArray(res) ? res : []
  } catch (e) {
    timelineNodes.value = []
  } finally {
    timelineLoading.value = false
  }
}

// ============ 进度日志 ============
async function openLogDialog(row) {
  currentTrack.value = row
  Object.assign(logForm, defaultLogForm())
  logForm.log_by = row.owner || ''
  logForm.log_by_name = row.owner_name || ''
  logDialogVisible.value = true
  await loadLogs(row.id)
}

async function loadLogs(trackingId) {
  logLoading.value = true
  try {
    // 通过 retrieve 取关联 logs
    const detail = await trackingApi.retrieve(trackingId)
    logList.value = detail?.logs || []
  } catch (e) {
    logList.value = []
  } finally {
    logLoading.value = false
  }
}

async function handleLogSubmit() {
  if (!logForm.action) {
    ElMessage.warning('请填写改善措施')
    return
  }
  logSubmitting.value = true
  try {
    await trackingApi.addLog(currentTrack.value.id, { ...logForm })
    ElMessage.success('日志已添加')
    Object.assign(logForm, defaultLogForm())
    logForm.log_by = currentTrack.value.owner || ''
    logForm.log_by_name = currentTrack.value.owner_name || ''
    await loadLogs(currentTrack.value.id)
    loadTracking()
  } catch (e) {
    // ignore
  } finally {
    logSubmitting.value = false
  }
}

function statusTagType(status) {
  const s = String(status || '').toUpperCase()
  if (s === 'OPEN') return 'danger'
  if (s === 'IN_PROGRESS') return 'warning'
  if (s === 'ACHIEVED') return 'success'
  if (s === 'VERIFIED') return 'primary'
  if (s === 'CLOSED') return 'info'
  if (s === 'REOPENED') return 'danger'
  return 'info'
}

function statusLabel(status) {
  const s = String(status || '').toUpperCase()
  const map = {
    OPEN: '待处理',
    IN_PROGRESS: '改善中',
    ACHIEVED: '已达成',
    VERIFIED: '已验证',
    CLOSED: '已关闭',
    REOPENED: '已重新打开'
  }
  return map[s] || status || '-'
}

function issueTypeLabel(type) {
  const map = {
    QWS_GAP: 'QWS差距',
    BUDGET_GAP: '预算差距',
    OTHER: '其他'
  }
  return map[String(type || '').toUpperCase()] || type || '-'
}

function priorityTagType(priority) {
  const map = { HIGH: 'danger', MEDIUM: 'warning', LOW: 'info' }
  return map[String(priority || '').toUpperCase()] || 'info'
}

function priorityLabel(priority) {
  const map = { HIGH: '高', MEDIUM: '中', LOW: '低' }
  return map[String(priority || '').toUpperCase()] || priority || '-'
}

function handlePageChange(page) {
  pagination.page = page
}

function handleSizeChange(size) {
  pagination.pageSize = size
  pagination.page = 1
}

// 计算当前行可执行的状态操作
function availableActions(row) {
  const s = String(row.status || '').toUpperCase()
  const actions = []
  if (s === 'OPEN' || s === 'REOPENED') {
    if (!row.owner) actions.push({ type: 'assign', label: '分派', btn: 'primary' })
    actions.push({ type: 'start', label: '开始', btn: 'success' })
  } else if (s === 'IN_PROGRESS') {
    actions.push({ type: 'achieve', label: '达成', btn: 'success' })
  } else if (s === 'ACHIEVED') {
    actions.push({ type: 'verify', label: '验证', btn: 'primary' })
  } else if (s === 'VERIFIED') {
    actions.push({ type: 'close', label: '关闭', btn: 'info' })
  } else if (s === 'CLOSED') {
    actions.push({ type: 'reopen', label: '重开', btn: 'warning' })
  }
  return actions
}

// ============ 图表配置 ============
// 1. 跟踪状态分布环形图
const statusDistOption = computed(() => {
  const items = aggregate(tableData.value, 'status', null, 'count')
  const statusMap = {
    OPEN: '待处理', IN_PROGRESS: '改善中', ACHIEVED: '已达成',
    VERIFIED: '已验证', CLOSED: '已关闭', REOPENED: '已重开'
  }
  const colorMap = {
    OPEN: '#f87171', IN_PROGRESS: '#fbbf24', ACHIEVED: '#4ade80',
    VERIFIED: '#2563eb', CLOSED: '#9ca3af', REOPENED: '#ef4444'
  }
  const data = items.map((it) => ({
    name: statusMap[it.name] || it.name || '未知',
    value: it.value,
    itemStyle: { color: colorMap[it.name] || '#8b5cf6' }
  }))
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    series: [{
      name: '跟踪状态',
      type: 'pie',
      radius: ['45%', '72%'],
      center: ['50%', '45%'],
      label: { show: true, color: '#1f2937', formatter: '{b}\n{d}%' },
      labelLine: { lineStyle: { color: '#6b7280' } },
      data
    }]
  }
})

// 2. 当前 BOL vs 目标 BOL 对比柱状图（Top10）
const bolCompareOption = computed(() => {
  const items = tableData.value
    .map((r) => ({
      name: `${r.program_code || '-'}${r.process ? '/' + r.process : ''}`,
      current: Number(r.current_bol) || 0,
      target: Number(r.target_bol) || 0
    }))
    .filter((it) => it.current > 0)
  const top = [...items].sort((a, b) => b.current - a.current).slice(0, 10)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['当前 BOL', '目标 BOL'], top: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 40, right: 20, top: 40, bottom: 50, containLabel: true },
    xAxis: { type: 'category', data: top.map((it) => it.name), axisLabel: { rotate: 30, fontSize: 11 } },
    yAxis: { type: 'value', name: 'BOL' },
    series: [
      {
        name: '当前 BOL',
        type: 'bar',
        data: top.map((it) => it.current),
        itemStyle: { color: dangerGradient() },
        ...adaptiveBarLayout(),
        label: buildValueLabelConfig('barCompact', top.length, {
          position: 'top',
          color: '#374151',
          formatter: '{c}'
        })
      },
      {
        name: '目标 BOL',
        type: 'bar',
        data: top.map((it) => it.target),
        itemStyle: { color: mintGradient() },
        ...adaptiveBarLayout(),
        label: buildValueLabelConfig('barCompact', top.length, {
          position: 'top',
          color: '#374151',
          formatter: '{c}'
        })
      }
    ]
  }
})

// 3. 优先级分布
const priorityOption = computed(() => {
  const items = aggregate(tableData.value, 'priority', null, 'count')
  const map = { HIGH: '高', MEDIUM: '中', LOW: '低' }
  const colorMap = { HIGH: '#ef4444', MEDIUM: '#f59e0b', LOW: '#3b82f6' }
  const data = items.map((it) => ({
    name: map[it.name] || it.name || '未知',
    value: it.value,
    itemStyle: { color: colorMap[it.name] || '#8b5cf6' }
  }))
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    series: [{
      name: '优先级', type: 'pie', radius: ['45%', '72%'], center: ['50%', '45%'],
      label: { show: true, color: '#1f2937', formatter: '{b}\n{d}%' },
      labelLine: { lineStyle: { color: '#6b7280' } },
      data
    }]
  }
})

onMounted(() => {
  loadTracking()
  loadOwners()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="高 BOL 跟踪管理"
      icon="Aim"
      subtitle="问题识别 → 分派负责人 → 改善 → 验证 → 关闭，形成完整闭环管理。状态流转：待处理 → 改善中 → 已达成 → 已验证 → 已关闭。"
      :breadcrumbs="[{ label: '跟踪管理' }, { label: '高 BOL 跟踪' }]"
    />
    <div class="page-container">

      <!-- 可视化图表区 -->
      <el-row :gutter="16" class="chart-row">
        <el-col :xs="24" :md="12" :lg="16">
          <ChartCard title="Top 10 项目：当前 BOL vs 目标 BOL" subtitle="红色为当前 BOL（应降低），绿色为目标 BOL" :option="bolCompareOption" :height="300" />
        </el-col>
        <el-col :xs="24" :md="12" :lg="8">
          <ChartCard title="跟踪状态分布" subtitle="待处理 / 改善中 / 已达成 / 已验证 / 已关闭" :option="statusDistOption" :height="300" />
        </el-col>
      </el-row>
      <el-row :gutter="16" class="chart-row">
        <el-col :xs="24" :lg="24">
          <ChartCard title="优先级分布" subtitle="高 / 中 / 低" :option="priorityOption" :height="280" />
        </el-col>
      </el-row>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 130px">
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select v-model="filters.issue_type" placeholder="问题类型" clearable style="width: 140px">
          <el-option v-for="opt in issueTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select v-model="filters.priority" placeholder="优先级" clearable style="width: 110px">
          <el-option v-for="opt in priorityOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-input v-model="filters.location" placeholder="地点" clearable style="width: 130px" @keyup.enter="handleSearch" />
        <el-input v-model="filters.owner" placeholder="负责人工号" clearable style="width: 140px" @keyup.enter="handleSearch" />
        <el-button type="primary" @click="handleSearch">
          <el-icon><Search /></el-icon>
          <span>查询</span>
        </el-button>
        <el-button @click="handleReset">
          <el-icon><Refresh /></el-icon>
          <span>重置</span>
        </el-button>
        <el-button type="success" @click="openCreateTrack">
          <el-icon><Plus /></el-icon>
          <span>新增跟踪</span>
        </el-button>
      </div>

      <!-- 跟踪记录表格 -->
      <div class="table-container">
        <el-table :data="pagedData" stripe border size="small" style="width: 100%">
          <el-table-column prop="program_code" label="项目代码" min-width="100" />
          <el-table-column prop="program_name" label="项目名称" min-width="130" show-overflow-tooltip />
          <el-table-column label="工艺" min-width="80">
            <template #default="{ row }">{{ row.process || '-' }}</template>
          </el-table-column>
          <el-table-column label="问题类型" min-width="90">
            <template #default="{ row }">{{ issueTypeLabel(row.issue_type) }}</template>
          </el-table-column>
          <el-table-column label="优先级" width="80">
            <template #default="{ row }">
              <el-tag :type="priorityTagType(row.priority)" size="small">{{ priorityLabel(row.priority) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="当前BOL" width="90">
            <template #default="{ row }">
              <span class="num-cell">{{ formatBol(row.current_bol) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="目标BOL" width="90">
            <template #default="{ row }">
              <span class="num-cell">{{ formatBol(row.target_bol) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="BOL差异" width="90">
            <template #default="{ row }">
              <span class="num-cell" :class="Number(row.bol_gap) > 0 ? 'bol-high' : 'bol-low'">
                {{ formatBol(row.bol_gap) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="年化成本差异" width="130">
            <template #default="{ row }">
              <span class="cost-loss">{{ formatCurrency(row.cost_gap) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="负责人" min-width="100">
            <template #default="{ row }">
              {{ row.owner_name || row.owner || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="目标日期" width="110">
            <template #default="{ row }">{{ formatDate(row.target_date) }}</template>
          </el-table-column>
          <el-table-column label="验证人" min-width="90">
            <template #default="{ row }">{{ row.verified_by_name || row.verified_by || '-' }}</template>
          </el-table-column>
          <el-table-column label="关闭人" min-width="90">
            <template #default="{ row }">{{ row.closed_by_name || row.closed_by || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button
                v-for="act in availableActions(row)"
                :key="act.type"
                :type="act.btn"
                link
                size="small"
                @click="openFlowDialog(act.type, row)"
              >
                {{ act.label }}
              </el-button>
              <el-button type="info" link size="small" @click="openTimelineDialog(row)">时间线</el-button>
              <el-button type="warning" link size="small" @click="openLogDialog(row)">日志</el-button>
              <el-button type="primary" link size="small" @click="openEditTrack(row)">编辑</el-button>
              <el-button type="danger" link size="small" @click="handleDeleteTrack(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="pagination.page"
            v-model:page-size="pagination.pageSize"
            :page-sizes="[10, 15, 20, 50]"
            :total="pagination.total"
            layout="total, sizes, prev, pager, next, jumper"
            background
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </div>

      <!-- 新增/编辑跟踪记录对话框 -->
      <el-dialog
        v-model="trackDialogVisible"
        :title="trackDialogMode === 'create' ? '新增跟踪记录' : '编辑跟踪记录'"
        width="920px"
        :close-on-click-modal="false"
        class="track-dialog"
      >
        <el-form :model="trackForm" label-width="96px" size="default" class="track-form">
          <!-- 区块一：项目基本信息（项目编号检索后自动回填） -->
          <div class="form-section">
            <div class="form-section-title">
              <el-icon><InfoFilled /></el-icon>
              <span>项目基本信息</span>
              <span class="form-section-hint">输入项目编号后自动检索 cbco_records（默认取当前年份下一年的数据）</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="项目编号" required>
                  <el-autocomplete
                    v-model="trackForm.program_code"
                    :fetch-suggestions="searchPrograms"
                    placeholder="输入项目编号检索"
                    clearable
                    value-key="value"
                    :trigger-on-focus="false"
                    style="width: 100%"
                    @select="handleProgramSelect"
                    @clear="handleProgramClear"
                  >
                    <template #default="{ item }">
                      <div class="program-sugg">
                        <div class="program-sugg-main">
                          <span class="program-sugg-code">{{ item.program_number }}</span>
                          <span v-if="item.customer" class="program-sugg-cust">{{ item.customer }}</span>
                        </div>
                        <div v-if="item.program_description" class="program-sugg-desc">{{ item.program_description }}</div>
                        <div class="program-sugg-meta">
                          <span v-if="item.irs_location">工厂: {{ item.irs_location }}</span>
                          <span v-if="item.year">年份: {{ item.year }}</span>
                          <span v-if="item.volume">年产量: {{ item.volume.toLocaleString('zh-CN') }}</span>
                        </div>
                      </div>
                    </template>
                  </el-autocomplete>
                </el-form-item>
              </el-col>
              <el-col :span="10">
                <el-form-item label="项目名称">
                  <el-input v-model="trackForm.program_name" placeholder="选择项目编号后自动带出" readonly />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="客户">
                  <el-input v-model="trackForm.customer" placeholder="自动带出" readonly />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="6">
                <el-form-item label="工厂" required>
                  <el-select v-model="trackForm.location" placeholder="选择工厂" style="width: 100%">
                    <el-option
                      v-for="opt in plantOptions"
                      :key="opt.value"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="工艺">
                  <el-select v-model="trackForm.process" placeholder="选择工艺" clearable style="width: 100%">
                    <el-option label="FA" value="FA" />
                    <el-option label="IHR" value="IHR" />
                    <el-option label="IHE" value="IHE" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="产线编号">
                  <el-input v-model="trackForm.line_nr" placeholder="产线编号" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="年产量">
                  <el-input-number v-model="trackForm.annual_volume" :min="0" :step="1000" controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- 区块二：问题识别与目标 -->
          <div class="form-section">
            <div class="form-section-title">
              <el-icon><Aim /></el-icon>
              <span>问题识别与目标</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="6">
                <el-form-item label="问题类型" required>
                  <el-select v-model="trackForm.issue_type" style="width: 100%">
                    <el-option
                      v-for="opt in issueTypeOptions.filter((o) => o.value)"
                      :key="opt.value" :label="opt.label" :value="opt.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="目标来源">
                  <el-select v-model="trackForm.target_source" style="width: 100%">
                    <el-option label="QWS 报价" value="QWS" />
                    <el-option label="年度预算" value="BUDGET" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="当前BOL">
                  <el-input-number v-model="trackForm.current_bol" :min="0" :precision="2" :step="0.1" controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="目标BOL">
                  <el-input-number v-model="trackForm.target_bol" :min="0" :precision="2" :step="0.1" controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="6">
                <el-form-item label="BOL差异">
                  <span class="num-cell" :class="bolVariance > 0 ? 'bol-high' : 'bol-low'">
                    {{ bolVariance.toFixed(2) }}
                  </span>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="工时单价（元/小时）">
                  <el-input-number v-model="trackForm.labor_rate" :min="0" :precision="2" :step="0.1" controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="优先级">
                  <el-select v-model="trackForm.priority" style="width: 100%">
                    <el-option
                      v-for="opt in priorityOptions.filter((o) => o.value)"
                      :key="opt.value" :label="opt.label" :value="opt.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="目标日期">
                  <el-date-picker v-model="trackForm.target_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- 区块三：变更属性 -->
          <div class="form-section">
            <div class="form-section-title">
              <el-icon><Switch /></el-icon>
              <span>变更属性</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="Change Type">
                  <el-select v-model="trackForm.change_type" placeholder="选择变更类型" clearable style="width: 100%">
                    <el-option
                      v-for="opt in changeTypeOptions"
                      :key="opt.value"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="Paid By">
                  <el-select v-model="trackForm.paid_by" placeholder="选择费用承担方" clearable style="width: 100%">
                    <el-option
                      v-for="opt in paidByOptions"
                      :key="opt.value"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="变更原因">
                  <el-select v-model="trackForm.change_reason" placeholder="选择变更原因" clearable style="width: 100%">
                    <el-option
                      v-for="opt in changeReasonOptions"
                      :key="opt.value"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- 区块四：改善方案与责任 -->
          <div class="form-section">
            <div class="form-section-title">
              <el-icon><Checked /></el-icon>
              <span>改善方案与责任</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="改善类型">
                  <el-select v-model="trackForm.improvement_type" clearable placeholder="选择改善类型" style="width: 100%">
                    <el-option
                      v-for="opt in improvementTypeOptions"
                      :key="opt.value" :label="opt.label" :value="opt.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="负责人">
                  <el-select
                    v-model="trackForm.owner"
                    filterable
                    clearable
                    placeholder="选择员工"
                    style="width: 100%"
                    @change="(val) => {
                      const o = ownerOptions.find((x) => x.username === val)
                      trackForm.owner_name = o ? o.name : ''
                    }"
                  >
                    <el-option
                      v-for="opt in ownerOptions"
                      :key="opt.username"
                      :label="`${opt.username} ${opt.name}`"
                      :value="opt.username"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="根本原因">
              <el-input v-model="trackForm.root_cause" type="textarea" :rows="2" placeholder="根本原因分析" />
            </el-form-item>
            <el-form-item label="改善措施">
              <el-input v-model="trackForm.improvement_action" type="textarea" :rows="2" placeholder="改善措施描述" />
            </el-form-item>
            <el-form-item label="改善计划">
              <el-input v-model="trackForm.improvement_plan" type="textarea" :rows="2" placeholder="详细改善计划" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="trackForm.remark" type="textarea" :rows="2" placeholder="备注" />
            </el-form-item>
          </div>
        </el-form>

        <template #footer>
          <el-button @click="trackDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="trackSubmitting" @click="handleTrackSubmit">确定</el-button>
        </template>
      </el-dialog>

      <!-- 状态流转对话框 -->
      <el-dialog
        v-model="flowDialogVisible"
        :title="flowDialogTitle"
        width="520px"
        :close-on-click-modal="false"
      >
        <el-form :model="flowForm" label-width="100px" size="default">
          <el-form-item label="项目代码">
            <span class="flow-program">{{ flowRow?.program_code || '-' }} · {{ flowRow?.program_name || '' }}</span>
          </el-form-item>

          <template v-if="flowType === 'assign'">
            <el-form-item label="负责人" required>
              <el-select
                v-model="flowForm.owner"
                filterable
                placeholder="选择员工"
                style="width: 100%"
                @change="handleOwnerChange"
              >
                <el-option
                  v-for="opt in ownerOptions"
                  :key="opt.username"
                  :label="`${opt.username} ${opt.name}`"
                  :value="opt.username"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="目标日期">
              <el-date-picker v-model="flowForm.target_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </template>

          <template v-if="flowType === 'achieve'">
            <el-form-item label="达成后 BOL">
              <el-input-number v-model="flowForm.bol_after" :min="0" :precision="2" :step="0.1" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item label="进度(%)">
              <el-input-number v-model="flowForm.progress" :min="0" :max="100" controls-position="right" style="width: 100%" />
            </el-form-item>
          </template>

          <template v-if="flowType === 'verify'">
            <el-form-item label="验证意见">
              <el-input v-model="flowForm.verify_comment" type="textarea" :rows="3" placeholder="验证说明" />
            </el-form-item>
          </template>

          <template v-if="flowType === 'reopen'">
            <el-form-item label="重开原因">
              <el-input v-model="flowForm.reopen_reason" type="textarea" :rows="3" placeholder="重新打开原因" />
            </el-form-item>
          </template>

          <el-form-item label="操作人工号">
            <el-input v-model="flowForm.operator_id" placeholder="您的工号" />
          </el-form-item>
          <el-form-item label="操作人姓名">
            <el-input v-model="flowForm.operator_name" placeholder="您的姓名" />
          </el-form-item>
        </el-form>

        <template #footer>
          <el-button @click="flowDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="flowSubmitting" @click="handleFlowSubmit">确定</el-button>
        </template>
      </el-dialog>

      <!-- 闭环时间线对话框 -->
      <el-dialog
        v-model="timelineDialogVisible"
        :title="`闭环时间线 · ${timelineRow?.program_code || ''}`"
        width="640px"
      >
        <div v-loading="timelineLoading" class="timeline-container">
          <el-timeline v-if="timelineNodes.length">
            <el-timeline-item
              v-for="(node, idx) in timelineNodes"
              :key="idx"
              :timestamp="formatDateTime(node.time)"
              placement="top"
              :type="
                node.type === 'CLOSE' ? 'success' :
                node.type === 'VERIFY' ? 'primary' :
                node.type === 'ACHIEVE' ? 'success' :
                node.type === 'START' ? 'warning' :
                node.type === 'ASSIGN' ? 'primary' :
                node.type === 'REOPEN' ? 'danger' :
                node.type === 'CREATE' ? 'info' : 'info'
              "
            >
              <h4 class="timeline-title">{{ node.title }}</h4>
              <p v-if="node.desc" class="timeline-desc">{{ node.desc }}</p>
              <div v-if="node.log_by" class="timeline-by">记录人：{{ node.log_by }}</div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无时间线数据" />
        </div>
        <template #footer>
          <el-button @click="timelineDialogVisible = false">关闭</el-button>
        </template>
      </el-dialog>

      <!-- 进度日志对话框 -->
      <el-dialog
        v-model="logDialogVisible"
        :title="`改善日志 · ${currentTrack?.program_code || ''}`"
        width="780px"
        :close-on-click-modal="false"
      >
        <div v-loading="logLoading">
          <el-table :data="logList" stripe border size="small" style="width: 100%; margin-bottom: 16px">
            <el-table-column label="日期" width="110">
              <template #default="{ row }">{{ formatDate(row.log_date) }}</template>
            </el-table-column>
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="
                  row.log_type === 'CLOSE' ? 'success' :
                  row.log_type === 'VERIFY' ? 'primary' :
                  row.log_type === 'ACHIEVE' ? 'success' :
                  row.log_type === 'START' ? 'warning' :
                  row.log_type === 'REOPEN' ? 'danger' : 'info'
                ">
                  {{ row.log_type || 'PROGRESS' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="action" label="行动记录" min-width="220" show-overflow-tooltip />
            <el-table-column label="改善后BOL" width="100">
              <template #default="{ row }">
                <span class="num-cell">{{ formatBol(row.bol_after) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="progress_update" label="进度" width="80" />
            <el-table-column label="记录人" min-width="100">
              <template #default="{ row }">{{ row.log_by_name || row.log_by || '-' }}</template>
            </el-table-column>
            <el-table-column label="时间" width="140">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>

          <div class="log-form-title">追加进度日志</div>
          <el-form :model="logForm" label-width="90px" size="default">
            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="改善后BOL">
                  <el-input-number v-model="logForm.bol_after" :min="0" :precision="2" :step="0.1" controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="进度(%)">
                  <el-input-number v-model="logForm.progress" :min="0" :max="100" controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="记录人工号">
                  <el-input v-model="logForm.log_by" placeholder="工号" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="记录人姓名">
              <el-input v-model="logForm.log_by_name" placeholder="姓名" />
            </el-form-item>
            <el-form-item label="行动记录" required>
              <el-input v-model="logForm.action" type="textarea" :rows="2" placeholder="本次采取的行动" />
            </el-form-item>
          </el-form>
        </div>

        <template #footer>
          <el-button @click="logDialogVisible = false">关闭</el-button>
          <el-button type="primary" :loading="logSubmitting" @click="handleLogSubmit">追加日志</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<style scoped>
.chart-row {
  margin-bottom: 16px;
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.log-form-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  padding: 8px 12px;
  background: #f4f5f7;
  border-left: 3px solid var(--color-primary);
  margin-bottom: 12px;
}

.flow-program {
  font-weight: 600;
  color: var(--color-text);
  font-size: 13px;
}

.timeline-container {
  max-height: 480px;
  overflow-y: auto;
  padding-right: 8px;
}

.timeline-title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.timeline-desc {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.timeline-by {
  font-size: 11px;
  color: var(--color-text-muted);
}

/* 跟踪记录弹窗：分区样式 */
.track-dialog .track-form {
  max-height: 68vh;
  overflow-y: auto;
  padding-right: 8px;
}

.form-section {
  margin-bottom: 18px;
  padding: 12px 14px 4px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.form-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #d1d5db;
}

.form-section-title .el-icon {
  color: var(--color-primary);
  font-size: 14px;
}

.form-section-hint {
  margin-left: auto;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted);
}

/* 项目检索下拉项 */
.program-sugg {
  padding: 4px 0;
  line-height: 1.5;
}

.program-sugg-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.program-sugg-code {
  font-weight: 600;
  color: var(--color-text);
  font-size: 13px;
}

.program-sugg-cust {
  font-size: 12px;
  color: var(--color-primary);
  background: #e0f2fe;
  padding: 1px 6px;
  border-radius: 3px;
}

.program-sugg-desc {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.program-sugg-meta {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--color-text-muted);
}
</style>

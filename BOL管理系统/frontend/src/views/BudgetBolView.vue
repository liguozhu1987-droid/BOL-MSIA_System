<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { budgetBolApi } from '@/api'
import { formatBol } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import BudgetBolComparison from './analytics/BudgetBolComparisonView.vue'

// ============ Tab 与 BOL 类型联动 ============
// 三个 Tab 对应三种 BOL 类型，切换 Tab 时自动设置 filters.bol_type 并加载数据
const activeTab = ref('BUDGET')
const comparisonSubTab = ref('BUDGET')
const tabOptions = [
  { value: 'BUDGET', label: 'Budget BOL' },
  { value: 'ACHIEVABLE', label: 'Achievable BOL' },
  { value: 'TARGET', label: 'Target BOL' },
  { value: 'COMPARISON', label: '财年对比' }
]

// 筛选条件（适配后端新字段：fiscal_year, bol_type, plant, process_type, project_code）
const filters = reactive({
  fiscal_year: '',
  bol_type: 'BUDGET',
  plant: '',
  process_type: '',
  project_code: '',
  project_name: ''
})

// 筛选器下拉选项（从 /filter-options/ 接口获取）
const yearOptions = ref([])
const plantOptions = ref([])
const processTypeOptions = ref([])

// 表格数据
const tableData = ref([])
const loading = ref(false)

// 当前登录用户（用于判断管理员权限）
const currentUser = ref(null)

// 分页（前端分页）
const pagination = reactive({
  page: 1,
  pageSize: 15,
  total: 0
})

const pagedData = computed(() => {
  const start = (pagination.page - 1) * pagination.pageSize
  return tableData.value.slice(start, start + pagination.pageSize)
})

// Excel 导入对话框
const importDialogVisible = ref(false)
const importForm = reactive({
  file: null,
  fiscal_year: new Date().getFullYear(),
  bol_type: 'ACHIEVABLE',
  created_by: ''
})
const importing = ref(false)
const importResult = ref(null)

// 清空数据对话框
const clearDialogVisible = ref(false)
const clearForm = reactive({
  fiscal_year: '',
  bol_type: '',
  confirm: ''
})
const clearing = ref(false)

// BOL 类型选项（用于导入对话框 radio 与清空对话框 select）
const bolTypeStaticOptions = [
  { value: 'ACHIEVABLE', label: 'Achievable BOL（CT/HC 计算）' },
  { value: 'BUDGET', label: 'Budget BOL（直接录入 BOL 值）' },
  { value: 'TARGET', label: 'Target BOL（产能规划目标）' }
]

// 是否管理员
const isAdmin = computed(() => {
  return currentUser.value?.role === 'ADMIN'
})

// 当前 Tab 决定列显示：Budget Tab 显示 Budget 列；其他 Tab 显示 Achievable/Target 列
const showBudgetColumns = computed(() => activeTab.value === 'BUDGET')
const showAchievableColumns = computed(() => activeTab.value !== 'BUDGET' && activeTab.value !== 'COMPARISON')
const isComparisonTab = computed(() => activeTab.value === 'COMPARISON')

// BOL 类型显示标签
function bolTypeLabel(type) {
  const t = String(type || '').toUpperCase()
  if (t === 'BUDGET') return 'Budget'
  if (t === 'ACHIEVABLE') return 'Achievable'
  if (t === 'TARGET') return 'Target'
  return type || '-'
}

// OEE 后端存储为小数（0-1），显示为百分比；兼容已是百分比的输入；空值或 0 显示 '-'
function formatOee(value) {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  if (num === 0) return '-'
  const percent = num <= 1 ? num * 100 : num
  return percent.toFixed(1) + '%'
}

// HC 显示：空值或 0 显示 '-'
function formatHc(value) {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  if (num === 0) return '-'
  return String(num)
}

// 切换 Tab：自动设置 bol_type 并重新加载数据（财年对比 tab 除外）
function handleTabChange(tab) {
  if (tab === 'COMPARISON') return
  filters.bol_type = tab || ''
  pagination.page = 1
  loadData()
}

// 获取当前登录用户
async function fetchCurrentUser() {
  try {
    const token = localStorage.getItem('bol_token')
    if (!token) return
    const res = await fetch('/api/users/me/', {
      headers: { 'Authorization': `Token ${token}` }
    })
    if (res.ok) {
      currentUser.value = await res.json()
    }
  } catch (e) {
    // ignore
  }
}

// 获取筛选器选项
async function fetchFilterOptions() {
  try {
    const res = await budgetBolApi.filterOptions()
    const data = res || {}
    yearOptions.value = (data.fiscal_years || []).map((v) => ({ label: String(v), value: v }))
    plantOptions.value = (data.plants || []).filter(Boolean).map((v) => ({ label: v, value: v }))
    processTypeOptions.value = (data.process_types || []).filter(Boolean).map((v) => ({ label: v, value: v }))
  } catch (e) {
    // 静默失败，筛选器仍可手动输入
  }
}

async function loadData() {
  loading.value = true
  try {
    const params = {}
    if (filters.fiscal_year) params.fiscal_year = filters.fiscal_year
    if (filters.bol_type) params.bol_type = filters.bol_type
    if (filters.plant) params.plant = filters.plant
    if (filters.process_type) params.process_type = filters.process_type
    if (filters.project_code) params.project_code = filters.project_code
    if (filters.project_name) params.project_name = filters.project_name
    const res = await budgetBolApi.list(params)
    const list = Array.isArray(res) ? res : (res.results || [])
    tableData.value = list
    pagination.total = list.length
    pagination.page = 1
  } catch (e) {
    // 已由拦截器提示
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  loadData()
}

function handleReset() {
  filters.fiscal_year = ''
  filters.plant = ''
  filters.process_type = ''
  filters.project_code = ''
  filters.project_name = ''
  // 注意：不重置 bol_type，因为它由 Tab 控制
  loadData()
}

// ============ Excel 导入相关 ============
function openImportDialog() {
  importForm.file = null
  importForm.fiscal_year = new Date().getFullYear()
  // 默认选当前 Tab 对应的 BOL 类型，方便用户
  importForm.bol_type = activeTab.value || 'ACHIEVABLE'
  importForm.created_by = ''
  importResult.value = null
  importDialogVisible.value = true
}

function handleFileChange(file) {
  importForm.file = file.raw
}

function handleFileRemove() {
  importForm.file = null
}

async function handleDownloadTemplate(templateType) {
  const t = (templateType || 'achievable').toLowerCase()
  try {
    const blob = await budgetBolApi.downloadTemplate(t)
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `budget_bol_${t}_template.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    ElMessage.success(t === 'budget' ? 'Budget BOL 模板已下载' : t === 'target' ? 'Target BOL 模板已下载' : 'Achievable BOL 模板已下载')
  } catch (e) {
    // 已由拦截器提示
  }
}

async function handleImportSubmit() {
  if (!importForm.file) {
    ElMessage.warning('请选择要导入的Excel文件')
    return
  }
  if (!importForm.fiscal_year) {
    ElMessage.warning('请填写财年')
    return
  }
  if (!importForm.bol_type) {
    ElMessage.warning('请选择 BOL 类型')
    return
  }
  importing.value = true
  importResult.value = null
  try {
    const res = await budgetBolApi.importExcel(
      importForm.file,
      importForm.fiscal_year,
      importForm.bol_type,
      importForm.created_by
    )
    importResult.value = res
    ElMessage.success('导入完成')
    // 导入完成后，自动切换到对应 Tab 显示数据
    activeTab.value = importForm.bol_type
    filters.bol_type = importForm.bol_type
    loadData()
    fetchFilterOptions()
  } catch (e) {
    // 已由拦截器提示
  } finally {
    importing.value = false
  }
}

// ============ 导入履历相关 ============
// Excel 导入历史记录（时间/文件/类型/用户等），从 import-logs 接口获取
const historyDialogVisible = ref(false)
const historyLoading = ref(false)
const historyList = ref([])
const historyFilter = reactive({
  fiscal_year: '',
  bol_type: ''
})

async function fetchImportHistory() {
  historyLoading.value = true
  try {
    const params = { limit: 100 }
    if (historyFilter.fiscal_year) params.fiscal_year = historyFilter.fiscal_year
    if (historyFilter.bol_type) params.bol_type = historyFilter.bol_type
    const res = await budgetBolApi.importLogs(params)
    historyList.value = Array.isArray(res) ? res : []
  } catch (e) {
    // 已由拦截器提示
  } finally {
    historyLoading.value = false
  }
}

function openHistoryDialog() {
  historyFilter.fiscal_year = ''
  historyFilter.bol_type = ''
  historyDialogVisible.value = true
  fetchImportHistory()
}

// 文件大小显示：B / KB / MB
function formatFileSize(size) {
  if (size === null || size === undefined || size === '') return '-'
  const num = Number(size)
  if (Number.isNaN(num) || num < 0) return '-'
  if (num < 1024) return `${num} B`
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`
  return `${(num / 1024 / 1024).toFixed(1)} MB`
}

// 时间显示：YYYY-MM-DD HH:mm:ss
function formatDateTime(dt) {
  if (!dt) return '-'
  return String(dt).slice(0, 19).replace('T', ' ')
}

// 导入履历 BOL 类型标签颜色（与模板下载按钮颜色一致）
function historyBolTypeTag(type) {
  const t = String(type || '').toUpperCase()
  if (t === 'BUDGET') return ''
  if (t === 'ACHIEVABLE') return 'success'
  if (t === 'TARGET') return 'danger'
  return 'info'
}

// ============ 一键清空相关 ============
function openClearDialog() {
  clearForm.fiscal_year = ''
  clearForm.bol_type = ''
  clearForm.confirm = ''
  clearDialogVisible.value = true
}

async function handleClearSubmit() {
  if (clearForm.confirm !== 'CONFIRM_CLEAR') {
    ElMessage.warning('请输入 CONFIRM_CLEAR 以确认清空操作')
    return
  }
  clearing.value = true
  try {
    const params = { confirm: clearForm.confirm }
    if (clearForm.fiscal_year) params.fiscal_year = clearForm.fiscal_year
    if (clearForm.bol_type) params.bol_type = clearForm.bol_type
    const res = await budgetBolApi.clearAll(params)
    ElMessage.success(`已清空 ${res.deleted} 条预算 BOL 数据`)
    clearDialogVisible.value = false
    loadData()
    fetchFilterOptions()
  } catch (e) {
    // 已由拦截器提示
  } finally {
    clearing.value = false
  }
}

function handlePageChange(page) {
  pagination.page = page
}

function handleSizeChange(size) {
  pagination.pageSize = size
  pagination.page = 1
}

onMounted(() => {
  fetchCurrentUser()
  fetchFilterOptions()
  // 初始加载第一个 Tab（Budget BOL）数据
  filters.bol_type = activeTab.value
  loadData()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="预算 BOL 管理"
      icon="Wallet"
      subtitle="支持标准化 Excel 模板导入 Budget / Achievable / Target 三类 BOL 数据；Achievable/Target 由 CT × HC × (1+1/15) / OEE / 60 计算"
      :breadcrumbs="[{ label: '数据管理' }, { label: '预算 BOL 管理' }]"
    />
    <div class="page-container">

    <!-- 筛选栏 -->
    <div class="filter-bar" v-if="!isComparisonTab">
      <el-select v-model="filters.fiscal_year" placeholder="财年" clearable style="width: 130px">
        <el-option v-for="opt in yearOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <!-- BOL 类型选择器已移除，由下方 Tab 代替 -->
      <el-select v-model="filters.plant" placeholder="工厂" clearable style="width: 150px">
        <el-option v-for="opt in plantOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-model="filters.process_type" placeholder="工艺类型" clearable style="width: 130px">
        <el-option v-for="opt in processTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-input
        v-model="filters.project_code"
        placeholder="项目代码"
        clearable
        style="width: 180px"
        @keyup.enter="handleSearch"
      />
      <el-input
        v-model="filters.project_name"
        placeholder="项目名称（模糊查询）"
        clearable
        style="width: 200px"
        @keyup.enter="handleSearch"
      />
      <el-button type="primary" @click="handleSearch">
        <el-icon><Search /></el-icon>
        <span>查询</span>
      </el-button>
      <el-button @click="handleReset">
        <el-icon><Refresh /></el-icon>
        <span>重置</span>
      </el-button>
      <el-button type="warning" @click="openImportDialog">
        <el-icon><Upload /></el-icon>
        <span>Excel 导入</span>
      </el-button>
      <el-button type="danger" plain @click="openClearDialog" v-if="isAdmin">
        <el-icon><Delete /></el-icon>
        <span>一键清空</span>
      </el-button>
    </div>

    <!-- 三个 Tab：Budget BOL / Achievable BOL / Target BOL -->
    <el-tabs v-model="activeTab" @tab-change="handleTabChange" class="bol-tabs">
      <el-tab-pane
        v-for="tab in tabOptions"
        :key="tab.value"
        :label="tab.label"
        :name="tab.value"
      />
    </el-tabs>

    <!-- 财年对比 Tab 内容：Budget 与 Achievable 子 tab -->
    <div v-if="isComparisonTab" class="comparison-tabs-container">
      <el-tabs v-model="comparisonSubTab" type="card" class="comparison-sub-tabs">
        <el-tab-pane label="Budget BOL 对比" name="BUDGET">
          <BudgetBolComparison v-if="comparisonSubTab === 'BUDGET'" :embedded="true" bol-type="BUDGET" />
        </el-tab-pane>
        <el-tab-pane label="Achievable BOL 对比" name="ACHIEVABLE">
          <BudgetBolComparison v-if="comparisonSubTab === 'ACHIEVABLE'" :embedded="true" bol-type="ACHIEVABLE" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 数据表格 -->
    <div class="table-container" v-if="!isComparisonTab">
      <el-table :data="pagedData" stripe border size="small" style="width: 100%">
        <!-- 基础列（所有 BOL 类型都显示） -->
        <el-table-column prop="fiscal_year" label="财年" width="80" />
        <el-table-column prop="project_code" label="项目代码" min-width="110" show-overflow-tooltip />
        <el-table-column prop="process_type" label="工艺类型" min-width="90" />
        <el-table-column prop="asset" label="产线" min-width="100" show-overflow-tooltip />
        <el-table-column prop="plant" label="工厂" min-width="100" />

        <!-- CBCO 项目基本信息列（所有 BOL 类型都显示） -->
        <el-table-column prop="customer" label="Customer" min-width="120" show-overflow-tooltip />
        <el-table-column prop="program_description" label="Programs" min-width="200" show-overflow-tooltip />
        <el-table-column prop="roof_type" label="Roof type" min-width="130" show-overflow-tooltip />
        <el-table-column prop="status" label="Status" min-width="90" />
        <el-table-column prop="sop" label="SOP" width="110" />
        <el-table-column prop="eop" label="EOP" width="110" />

        <!-- BOL 值列 -->
        <el-table-column v-if="!showBudgetColumns" label="BOL值" width="100">
          <template #default="{ row }">
            <span class="num-cell bol-mid">{{ formatBol(row.bol) }}</span>
          </template>
        </el-table-column>

        <!-- BUDGET Tab 额外列 -->
        <el-table-column v-if="showBudgetColumns" label="AME Target BOL" width="130">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.ame_target_bol) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showBudgetColumns" label="Achievable BOL" width="130">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.achievable_bol) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showBudgetColumns" label="Budget BOL" width="120">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.budget_bol) }}</span>
          </template>
        </el-table-column>

        <!-- ACHIEVABLE/TARGET Tab 额外列 -->
        <el-table-column v-if="showAchievableColumns" label="OEE" width="90">
          <template #default="{ row }">
            <span class="num-cell">{{ formatOee(row.oee) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺1 CT" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.process1_ct) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺1 HC" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatHc(row.process1_hc) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺2 CT" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.process2_ct) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺2 HC" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatHc(row.process2_hc) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺3 CT" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.process3_ct) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺3 HC" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatHc(row.process3_hc) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺4 CT" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.process4_ct) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺4 HC" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatHc(row.process4_hc) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺5 CT" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.process5_ct) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showAchievableColumns" label="子工艺5 HC" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatHc(row.process5_hc) }}</span>
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

    <!-- Excel 导入对话框 -->
    <el-dialog
      v-model="importDialogVisible"
      title="Excel 导入预算 BOL"
      width="620px"
      :close-on-click-modal="false"
    >
      <el-form :model="importForm" label-width="100px" size="default">
        <el-form-item label="BOL 类型" required>
          <el-radio-group v-model="importForm.bol_type">
            <el-radio
              v-for="opt in bolTypeStaticOptions"
              :key="opt.value"
              :value="opt.value"
              :label="opt.value"
            >
              {{ opt.label }}
            </el-radio>
          </el-radio-group>
          <div class="form-tip warning">
            <el-icon><Warning /></el-icon>
            <span>导入将清空该财年该类型的全部旧数据，再全量导入新数据</span>
          </div>
        </el-form-item>
        <el-form-item label="财年" required>
          <el-input-number v-model="importForm.fiscal_year" :min="2020" :max="2099" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="创建人">
          <el-input v-model="importForm.created_by" placeholder="创建人（可选）" />
        </el-form-item>
        <el-form-item label="下载模板">
          <el-button type="primary" plain size="small" @click="handleDownloadTemplate('budget')">
            <el-icon><Download /></el-icon>
            <span>Budget BOL</span>
          </el-button>
          <el-button type="success" plain size="small" @click="handleDownloadTemplate('achievable')">
            <el-icon><Download /></el-icon>
            <span>Achievable BOL</span>
          </el-button>
          <el-button type="danger" plain size="small" @click="handleDownloadTemplate('target')">
            <el-icon><Download /></el-icon>
            <span>Target BOL</span>
          </el-button>
          <el-button type="info" plain size="small" @click="$router.push('/budget-bol/help')">
            <el-icon><QuestionFilled /></el-icon>
            <span>导入帮助</span>
          </el-button>
        </el-form-item>
        <el-form-item label="导入履历">
          <el-button type="primary" plain size="small" @click="openHistoryDialog">
            <el-icon><Clock /></el-icon>
            <span>查看导入履历</span>
          </el-button>
          <div class="form-tip">可查看历史导入的时间、文件、类型、用户等信息</div>
        </el-form-item>
        <el-form-item label="Excel文件" required>
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".xlsx,.xls"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :file-list="[]"
          >
            <el-button type="primary" plain>
              <el-icon><Upload /></el-icon>
              <span>选择文件</span>
            </el-button>
            <template #tip>
              <div class="upload-tip">文件 sheet 名需与所选 BOL 类型对应</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>

      <!-- 导入结果 -->
      <div v-if="importResult" class="import-result">
        <div class="result-row">
          <span class="result-label">BOL 类型：</span>
          <span class="result-value">{{ bolTypeLabel(importResult.bol_type) }}</span>
        </div>
        <div class="result-row">
          <span class="result-label">财年：</span>
          <span class="result-value">{{ importResult.fiscal_year }}</span>
        </div>
        <div class="result-row">
          <span class="result-label">总行数：</span>
          <span class="result-value">{{ importResult.total_rows ?? 0 }}</span>
        </div>
        <div class="result-row" v-if="importResult.deleted !== undefined">
          <span class="result-label">已删除旧数据：</span>
          <span class="result-value" style="color: #ef4444">{{ importResult.deleted }}</span>
        </div>
        <div class="result-row">
          <span class="result-label">成功导入：</span>
          <span class="result-value" style="color: #10b981">{{ importResult.imported ?? 0 }}</span>
        </div>
        <div class="result-row">
          <span class="result-label">跳过：</span>
          <span class="result-value">{{ importResult.skipped ?? 0 }}</span>
        </div>
        <div v-if="importResult.errors && importResult.errors.length" class="error-list">
          <div class="error-title">错误明细（前 10 条）：</div>
          <ul>
            <li v-for="(err, idx) in importResult.errors.slice(0, 10)" :key="idx">{{ err }}</li>
          </ul>
        </div>
      </div>

      <template #footer>
        <el-button @click="importDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="importing" @click="handleImportSubmit">
          开始导入
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入履历对话框 -->
    <el-dialog
      v-model="historyDialogVisible"
      title="预算 BOL 导入履历"
      width="980px"
      :close-on-click-modal="false"
      append-to-body
    >
      <div class="history-filter-bar">
        <el-select v-model="historyFilter.fiscal_year" placeholder="财年" clearable style="width: 120px">
          <el-option v-for="opt in yearOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select v-model="historyFilter.bol_type" placeholder="BOL 类型" clearable style="width: 170px">
          <el-option v-for="opt in bolTypeStaticOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-button type="primary" @click="fetchImportHistory">
          <el-icon><Search /></el-icon>
          <span>查询</span>
        </el-button>
        <span class="history-count">共 {{ historyList.length }} 条记录</span>
      </div>
      <el-table
        :data="historyList"
        v-loading="historyLoading"
        stripe
        border
        size="small"
        style="width: 100%"
        max-height="480"
      >
        <el-table-column label="导入时间" width="150">
          <template #default="{ row }">
            <span class="num-cell">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="file_name" label="文件名" min-width="170" show-overflow-tooltip />
        <el-table-column label="BOL 类型" width="95">
          <template #default="{ row }">
            <el-tag :type="historyBolTypeTag(row.bol_type)" size="small">
              {{ bolTypeLabel(row.bol_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="fiscal_year" label="财年" width="65" />
        <el-table-column prop="imported_by" label="导入用户" width="95" show-overflow-tooltip />
        <el-table-column label="状态" width="70">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : 'danger'" size="small">
              {{ row.status === 'SUCCESS' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="imported" label="导入行数" width="80" align="right" />
        <el-table-column prop="total_rows" label="总行数" width="70" align="right" />
        <el-table-column prop="deleted" label="删除旧数据" width="85" align="right" />
        <el-table-column prop="skipped" label="跳过" width="60" align="right" />
        <el-table-column label="文件大小" width="80" align="right">
          <template #default="{ row }">
            <span class="num-cell">{{ formatFileSize(row.file_size) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="失败原因" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'history-error': !!row.error_message }">{{ row.error_message || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="history-empty-tip" v-if="!historyLoading && !historyList.length">
        暂无导入履历
      </div>
      <div class="form-tip" style="margin-top: 8px">
        每次执行 Excel 导入（无论成功或失败）都会自动记录一条履历；导入用户优先记录当前登录账号
      </div>
      <template #footer>
        <el-button @click="historyDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 一键清空对话框 -->
    <el-dialog
      v-model="clearDialogVisible"
      title="一键清空预算 BOL 数据"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="危险操作"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      >
        此操作将永久删除数据，不可恢复！请谨慎操作。
      </el-alert>
      <el-form :model="clearForm" label-width="100px" size="default">
        <el-form-item label="财年">
          <el-input-number
            v-model="clearForm.fiscal_year"
            :min="2020"
            :max="2099"
            controls-position="right"
            placeholder="留空清空所有财年"
            style="width: 100%"
          />
          <div class="form-tip">留空则清空所有财年的数据</div>
        </el-form-item>
        <el-form-item label="BOL类型">
          <el-select v-model="clearForm.bol_type" placeholder="留空清空所有类型" clearable style="width: 100%">
            <el-option v-for="opt in bolTypeStaticOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <div class="form-tip">留空则清空所有类型的数据</div>
        </el-form-item>
        <el-form-item label="确认操作" required>
          <el-input
            v-model="clearForm.confirm"
            placeholder="请输入 CONFIRM_CLEAR 确认"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="clearDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="clearing" @click="handleClearSubmit">
          确认清空
        </el-button>
      </template>
    </el-dialog>

    </div>
  </div>
</template>

<style scoped>
.bol-tabs {
  margin-bottom: 8px;
}

.bol-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.comparison-tabs-container {
  margin-top: 0;
}

.comparison-sub-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.comparison-sub-tabs :deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 500;
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.upload-tip {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  margin-top: 4px;
}

.form-tip {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.form-tip.warning {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 10px;
  background: var(--color-accent-glow);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: var(--radius-sm);
  color: var(--color-accent);
  font-weight: 500;
}

.import-result {
  margin-top: 12px;
  padding: 12px 14px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 4px;
}

.result-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  margin-bottom: 4px;
}

.result-label {
  color: var(--color-text-secondary);
}

.result-value {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--color-text);
}

.error-list {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #f87171;
}

.error-title {
  font-size: 13px;
  color: #b91c1c;
  font-weight: 600;
  margin-bottom: 4px;
}

.error-list ul {
  margin: 0;
  padding-left: 20px;
  font-size: 12px;
  color: #7f1d1d;
  max-height: 120px;
  overflow-y: auto;
}

.error-list li {
  line-height: 1.6;
}

/* ============ 导入履历 ============ */
.history-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.history-count {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-left: 8px;
}

.history-error {
  color: var(--color-danger);
}

.history-empty-tip {
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted);
  padding: 24px 0;
}
</style>

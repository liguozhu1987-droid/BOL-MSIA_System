<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { analyticsApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import { formatBol, normalizePlant } from '@/utils/format'
import { buildValueLabelConfig, adaptiveBarLayout } from '@/utils/echartsTheme'

const props = defineProps({
  embedded: { type: Boolean, default: false },
  bolType: { type: String, default: 'BUDGET' }
})

const loading = ref(false)
const data = ref(null)
const params = reactive({
  from_year: 2025,
  to_year: 2026,
})

// BOL 类型标签
const bolTypeLabel = computed(() => {
  const t = (props.bolType || 'BUDGET').toUpperCase()
  if (t === 'ACHIEVABLE') return 'Achievable BOL'
  if (t === 'TARGET') return 'Target BOL'
  return 'Budget BOL'
})

// 汇总卡片
const summaryStats = computed(() => {
  if (!data.value) return { total: 0, decreased: 0, increased: 0, hours: 0 }
  const s = data.value.summary
  const items = data.value.items || []
  const decreased = items.filter((x) => x.bol_reduction_pct > 0).length
  const increased = items.filter((x) => x.bol_reduction_pct < 0).length
  return {
    total: s.total_items || 0,
    decreased,
    increased,
    hours: s.total_hours_saved || 0,
  }
})

// 图表1：按工厂节省工时（柱状图）
const plantHoursOption = computed(() => {
  if (!data.value) return {}
  const list = data.value.by_plant || []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 55, right: 30, top: 55, bottom: 70, containLabel: true },
    xAxis: {
      type: 'category',
      data: list.map((x) => x.plant),
      axisLabel: { fontSize: 12, rotate: list.length > 4 ? 20 : 0, interval: 0 }
    },
    yAxis: {
      type: 'value',
      name: '节省工时 (h)',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { fontSize: 12, color: '#6b7280' },
      axisLabel: { fontSize: 11, color: '#6b7280' }
    },
    series: [{
      name: '节省工时',
      type: 'bar',
      data: list.map((x) => x.hours_saved),
      itemStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: '#3b82f6' },
            { offset: 1, color: '#93c5fd' }
          ]
        }
      },
      ...adaptiveBarLayout(),
      label: buildValueLabelConfig('bar', list.length, {
        position: 'top',
        color: '#4b5563',
        fontSize: 11,
        formatter: '{c} h'
      })
    }]
  }
})

// 图表2：按工艺节省工时（柱状图）
const processHoursOption = computed(() => {
  if (!data.value) return {}
  const list = data.value.by_process || []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 55, right: 30, top: 55, bottom: 45, containLabel: true },
    xAxis: {
      type: 'category',
      data: list.map((x) => x.process_type),
      axisLabel: { fontSize: 12, interval: 0 }
    },
    yAxis: {
      type: 'value',
      name: '节省工时 (h)',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { fontSize: 12, color: '#6b7280' },
      axisLabel: { fontSize: 11, color: '#6b7280' }
    },
    series: [{
      name: '节省工时',
      type: 'bar',
      data: list.map((x) => x.hours_saved),
      itemStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: '#f59e0b' },
            { offset: 1, color: '#fcd34d' }
          ]
        }
      },
      ...adaptiveBarLayout(),
      label: buildValueLabelConfig('bar', list.length, {
        position: 'top',
        color: '#4b5563',
        fontSize: 11,
        formatter: '{c} h'
      })
    }]
  }
})

// 图表3：按工厂指标卡（替换原散点图）
const plantCards = computed(() => {
  if (!data.value) return []
  const byPlant = data.value.by_plant || []
  const items = data.value.items || []
  return byPlant.map((p) => {
    const plantItems = items.filter((x) => normalizePlant(x.plant) === p.plant)
    const decreased = plantItems.filter((x) => x.bol_reduction_pct > 0).length
    const increased = plantItems.filter((x) => x.bol_reduction_pct < 0).length
    return { ...p, decreased, increased }
  })
})

// 弹窗状态
const dialogVisible = ref(false)
const dialogTitle = ref('')
const dialogItems = ref([])
const dialogPlantFilter = ref('')
const dialogProcessFilter = ref('')

// 主表格筛选
const tablePlantFilter = ref('')
const tableProcessFilter = ref('')

const tablePlantOptions = computed(() => {
  const items = data.value?.items || []
  const plants = [...new Set(items.map((x) => normalizePlant(x.plant)))].filter(Boolean)
  return plants.sort().map((p) => ({ value: p, label: p }))
})

const tableProcessOptions = computed(() => {
  const items = data.value?.items || []
  const types = [...new Set(items.map((x) => x.process_type))].filter(Boolean)
  return types.sort().map((t) => ({ value: t, label: t }))
})

const filteredTableItems = computed(() => {
  let items = data.value?.items || []
  if (tablePlantFilter.value) {
    items = items.filter((x) => normalizePlant(x.plant) === tablePlantFilter.value)
  }
  if (tableProcessFilter.value) {
    items = items.filter((x) => x.process_type === tableProcessFilter.value)
  }
  return items
})

const dialogPlantOptions = computed(() => {
  const plants = [...new Set(dialogItems.value.map((x) => normalizePlant(x.plant)))].filter(Boolean)
  return plants.sort().map((p) => ({ value: p, label: p }))
})

const dialogProcessOptions = computed(() => {
  const types = [...new Set(dialogItems.value.map((x) => x.process_type))].filter(Boolean)
  return types.sort().map((t) => ({ value: t, label: t }))
})

const filteredDialogItems = computed(() => {
  let items = dialogItems.value
  if (dialogPlantFilter.value) {
    items = items.filter((x) => normalizePlant(x.plant) === dialogPlantFilter.value)
  }
  if (dialogProcessFilter.value) {
    items = items.filter((x) => x.process_type === dialogProcessFilter.value)
  }
  return items
})

function filterItemsByPlant(plant) {
  return (data.value?.items || []).filter((x) => normalizePlant(x.plant) === plant)
}

function showAllItems() {
  dialogTitle.value = `全部对比项目（${summaryStats.value.total}）`
  dialogItems.value = data.value?.items || []
  dialogPlantFilter.value = ''
  dialogProcessFilter.value = ''
  dialogVisible.value = true
}

function showDecreasedItems() {
  const items = (data.value?.items || []).filter((x) => x.bol_reduction_pct > 0)
  dialogTitle.value = `BOL 降低项目（${items.length}）`
  dialogItems.value = items
  dialogPlantFilter.value = ''
  dialogProcessFilter.value = ''
  dialogVisible.value = true
}

function showIncreasedItems() {
  const items = (data.value?.items || []).filter((x) => x.bol_reduction_pct < 0)
  dialogTitle.value = `BOL 上升项目（${items.length}）`
  dialogItems.value = items
  dialogPlantFilter.value = ''
  dialogProcessFilter.value = ''
  dialogVisible.value = true
}

function showHoursDetail() {
  dialogTitle.value = `净节省工时明细`
  dialogItems.value = data.value?.items || []
  dialogPlantFilter.value = ''
  dialogProcessFilter.value = ''
  dialogVisible.value = true
}

function showPlantDetail(plant) {
  const items = filterItemsByPlant(plant)
  dialogTitle.value = `${plant} · 对比项目（${items.length}）`
  dialogItems.value = items
  dialogPlantFilter.value = ''
  dialogProcessFilter.value = ''
  dialogVisible.value = true
}

async function loadData() {
  loading.value = true
  try {
    const res = await analyticsApi.budgetBolComparison({
      from_year: params.from_year,
      to_year: params.to_year,
      bol_type: props.bolType,
    })
    data.value = res
  } catch (e) {
    // 已由拦截器提示
  } finally {
    loading.value = false
  }
}

// bolType 变化时重新加载
watch(() => props.bolType, () => {
  loadData()
})

onMounted(() => {
  loadData()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader v-if="!embedded"
      :title="`${bolTypeLabel} 财年对比`"
      icon="TrendCharts"
      :subtitle="`对比两个财年各项目 ${bolTypeLabel} 的变化，计算节省比例与节省工时，按工厂和工艺维度汇总分析`"
      :breadcrumbs="[{ label: '分析中心' }, { label: `${bolTypeLabel} 财年对比` }]"
    />
    <div class="page-container">

      <!-- 财年选择 -->
      <div class="filter-bar">
        <span class="filter-label" style="font-size: 14px; margin-right: 8px;">对比财年：</span>
        <el-input-number v-model="params.from_year" :min="2020" :max="2030" size="small" style="width: 110px" @change="loadData" />
        <span style="margin: 0 8px; color: var(--color-text-muted);">→</span>
        <el-input-number v-model="params.to_year" :min="2021" :max="2030" size="small" style="width: 110px" @change="loadData" />
        <el-button type="primary" size="small" @click="loadData" style="margin-left: 12px;">
          <el-icon><Search /></el-icon>
          <span>分析</span>
        </el-button>
      </div>

      <!-- 汇总指标卡 -->
      <div class="summary-grid" v-if="data">
        <div class="summary-item clickable" @click="showAllItems">
          <div class="summary-label">对比项目数</div>
          <div class="summary-value text-mono">{{ summaryStats.total }}</div>
        </div>
        <div class="summary-item clickable" @click="showDecreasedItems">
          <div class="summary-label">BOL 降低</div>
          <div class="summary-value text-mono bol-low">{{ summaryStats.decreased }}</div>
        </div>
        <div class="summary-item clickable" @click="showIncreasedItems">
          <div class="summary-label">BOL 上升</div>
          <div class="summary-value text-mono bol-high">{{ summaryStats.increased }}</div>
        </div>
        <div class="summary-item clickable" @click="showHoursDetail">
          <div class="summary-label">净节省工时</div>
          <div class="summary-value text-mono" :style="{ color: summaryStats.hours >= 0 ? '#10b981' : '#ef4444' }">{{ formatBol(summaryStats.hours) }} h</div>
        </div>
      </div>

      <!-- 图表 -->
      <el-row :gutter="16" class="chart-row" v-if="data">
        <el-col :xs="24" :lg="12">
          <ChartCard title="按工厂节省工时" :subtitle="`${params.from_year} → ${params.to_year} · 各工厂累计节省工时`" :option="plantHoursOption" :height="320" />
        </el-col>
        <el-col :xs="24" :lg="12">
          <ChartCard title="按工艺节省工时" :subtitle="`${params.from_year} → ${params.to_year} · 各工艺累计节省工时`" :option="processHoursOption" :height="320" />
        </el-col>
      </el-row>

      <!-- 按工厂指标卡 -->
      <div class="plant-cards-row" v-if="data && plantCards.length">
        <div class="plant-card clickable" v-for="card in plantCards" :key="card.plant" @click="showPlantDetail(card.plant)">
          <div class="plant-card-header">{{ card.plant }}</div>
          <div class="plant-card-body">
            <div class="plant-card-item">
              <span class="plant-card-label">净节省工时</span>
              <span class="plant-card-value" :style="{ color: card.hours_saved >= 0 ? '#10b981' : '#ef4444' }">
                {{ card.hours_saved >= 0 ? '+' : '' }}{{ formatBol(card.hours_saved) }} h
              </span>
            </div>
            <div class="plant-card-item">
              <span class="plant-card-label">BOL降低</span>
              <span class="plant-card-value bol-low">{{ card.decreased }}</span>
            </div>
            <div class="plant-card-item">
              <span class="plant-card-label">BOL上升</span>
              <span class="plant-card-value bol-high">{{ card.increased }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 明细表格 -->
      <div class="table-container" v-if="data">
        <div class="table-filter-bar">
          <el-select v-model="tablePlantFilter" placeholder="工厂" clearable size="small" style="width: 140px">
            <el-option v-for="opt in tablePlantOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-select v-model="tableProcessFilter" placeholder="工艺" clearable size="small" style="width: 110px; margin-left: 8px">
            <el-option v-for="opt in tableProcessOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <span class="table-filter-count">共 {{ filteredTableItems.length }} 条</span>
        </div>
        <el-table :data="filteredTableItems" stripe border size="small" max-height="500" style="width: 100%">
          <el-table-column prop="project_code" label="项目代码" min-width="110" fixed />
          <el-table-column prop="program_description" label="项目描述" min-width="200" show-overflow-tooltip />
          <el-table-column prop="process_type" label="工艺" width="80" />
          <el-table-column prop="plant" label="工厂" min-width="100" />
          <el-table-column :label="`${params.from_year} BOL`" width="90">
            <template #default="{ row }">
              <span class="num-cell">{{ formatBol(row.from_bol) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="`${params.to_year} BOL`" width="90">
            <template #default="{ row }">
              <span class="num-cell">{{ formatBol(row.to_bol) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="`${params.from_year} Volume`" width="110">
            <template #default="{ row }">
              <span class="num-cell">{{ row.from_volume || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="`${params.to_year} Volume`" width="110">
            <template #default="{ row }">
              <span class="num-cell">{{ row.to_volume || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="BOL变化比例" width="110">
            <template #default="{ row }">
              <span :class="['num-cell', row.bol_reduction_pct > 0 ? 'bol-low' : (row.bol_reduction_pct < 0 ? 'bol-high' : '')]">
                {{ row.bol_reduction_pct > 0 ? '↓' : (row.bol_reduction_pct < 0 ? '↑' : '') }}{{ Math.abs(row.bol_reduction_pct) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="工时变化" width="100">
            <template #default="{ row }">
              <span :class="['num-cell', row.hours_saved > 0 ? 'bol-low' : (row.hours_saved < 0 ? 'bol-high' : '')]">
                {{ row.hours_saved > 0 ? '+' : '' }}{{ formatBol(row.hours_saved) }} h
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 详情弹窗 -->
      <el-dialog v-model="dialogVisible" :title="dialogTitle" width="85%" top="5vh" :close-on-click-modal="true">
        <div class="dialog-filter-bar">
          <el-select v-model="dialogPlantFilter" placeholder="工厂" clearable size="small" style="width: 140px">
            <el-option v-for="opt in dialogPlantOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-select v-model="dialogProcessFilter" placeholder="工艺" clearable size="small" style="width: 110px; margin-left: 8px">
            <el-option v-for="opt in dialogProcessOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <span class="dialog-filter-count">共 {{ filteredDialogItems.length }} 条</span>
        </div>
        <el-table :data="filteredDialogItems" stripe border size="small" max-height="460" style="width: 100%">
          <el-table-column prop="project_code" label="项目代码" min-width="110" fixed />
          <el-table-column prop="program_description" label="项目描述" min-width="180" show-overflow-tooltip />
          <el-table-column prop="process_type" label="工艺" width="80" />
          <el-table-column prop="plant" label="工厂" min-width="100" />
          <el-table-column :label="`${params.from_year} BOL`" width="90">
            <template #default="{ row }">
              <span class="num-cell">{{ formatBol(row.from_bol) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="`${params.to_year} BOL`" width="90">
            <template #default="{ row }">
              <span class="num-cell">{{ formatBol(row.to_bol) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="BOL变化比例" width="110">
            <template #default="{ row }">
              <span :class="['num-cell', row.bol_reduction_pct > 0 ? 'bol-low' : (row.bol_reduction_pct < 0 ? 'bol-high' : '')]">
                {{ row.bol_reduction_pct > 0 ? '↓' : (row.bol_reduction_pct < 0 ? '↑' : '') }}{{ Math.abs(row.bol_reduction_pct) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="工时变化" width="100">
            <template #default="{ row }">
              <span :class="['num-cell', row.hours_saved > 0 ? 'bol-low' : (row.hours_saved < 0 ? 'bol-high' : '')]">
                {{ row.hours_saved > 0 ? '+' : '' }}{{ formatBol(row.hours_saved) }} h
              </span>
            </template>
          </el-table-column>
        </el-table>
      </el-dialog>

    </div>
  </div>
</template>

<style scoped>
.plant-cards-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 20px;
}

.plant-card {
  flex: 1;
  min-width: 180px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  transition: box-shadow 0.2s;
}

.plant-card:hover,
.clickable:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  cursor: pointer;
}

.clickable {
  transition: box-shadow 0.2s, transform 0.15s;
}

.clickable:active {
  transform: scale(0.98);
}

.plant-card-header {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f3f4f6;
}

.plant-card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plant-card-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.plant-card-label {
  font-size: 12px;
  color: #9ca3af;
}

.plant-card-value {
  font-size: 15px;
  font-weight: 700;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

/* filter-bar 统一由 main.css 全局规范接管（标准卡片式） */

.summary-grid {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}

.summary-item {
  flex: 1;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.summary-label {
  font-size: 13px;
  color: #9ca3af;
  margin-bottom: 6px;
}

.summary-value {
  font-size: 24px;
  font-weight: 700;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.text-mono {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.chart-row {
  margin-bottom: 20px;
}

.table-container {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
}

.num-cell {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 13px;
}

.bol-low {
  color: #059669;
}

.bol-high {
  color: #dc2626;
}

.page-container {
  padding: 0;
}

.dialog-filter-bar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.dialog-filter-count {
  margin-left: auto;
  font-size: 13px;
  color: #6b7280;
}

.table-filter-bar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.table-filter-count {
  margin-left: auto;
  font-size: 13px;
  color: #6b7280;
}
</style>
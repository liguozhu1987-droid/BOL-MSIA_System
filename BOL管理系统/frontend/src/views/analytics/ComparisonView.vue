<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { analyticsApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import { PALETTE, AXIS, mintGradient, CHART_SPEC, adaptiveBarLayout } from '@/utils/echartsTheme'

// 筛选条件
const filters = reactive({
  bol_type: 'ACHIEVABLE',
  fiscal_year: '',   // 空字符串=全部财年
  process_type: '',  // 空字符串=全部工艺
})

// 数据
const rawData = ref(null)
const loading = ref(false)

// 筛选选项
const bolTypeOptions = [
  { label: 'Achievable BOL（可达BOL）', value: 'ACHIEVABLE' },
  { label: 'Budget BOL（预算BOL）', value: 'BUDGET' },
  { label: 'Target BOL（目标BOL）', value: 'TARGET' },
]
const processTypeOptions = [
  { label: '全部工艺', value: '' },
  { label: 'FA（总装）', value: 'FA' },
  { label: 'IHE（厂内封装）', value: 'IHE' },
  { label: 'IHR（厂内卷帘）', value: 'IHR' },
]

async function loadData() {
  loading.value = true
  try {
    const params = { bol_type: filters.bol_type }
    if (filters.fiscal_year) params.fiscal_year = filters.fiscal_year
    if (filters.process_type) params.process_type = filters.process_type
    rawData.value = await analyticsApi.multiDimAnalysis(params)
  } catch (e) {
    // 已由拦截器提示
  } finally {
    loading.value = false
  }
}

function handleReset() {
  filters.bol_type = 'ACHIEVABLE'
  filters.fiscal_year = ''
  filters.process_type = ''
  trendLoaded.value = false
  trendComboFilter.value = ''
  loadData()
  if (activeTab.value === 'time') {
    loadTrendData()
  }
}

onMounted(() => {
  loadData()
})

// ===== 汇总信息 =====
const summary = computed(() => rawData.value?.summary || {
  total_projects: 0, plant_count: 0,
  process_type_count: 0, roof_type_count: 0, fiscal_years: [],
})

// ===== 数据列表 =====
const byProcessRoof = computed(() => rawData.value?.by_process_roof || [])
const crossPlant = computed(() => rawData.value?.cross_plant || [])

// 当前激活的 tab
const activeTab = ref('overview')

// 时间维度-多 BOL 类型对比数据（独立加载，对比 Budget/Achievable/Target）
const trendData = ref(null)
const trendLoading = ref(false)
const trendLoaded = ref(false)
// 时间维度-组合筛选（选择查看哪个 RoofType+工艺 组合的三类型对比）
const trendComboFilter = ref('')

async function loadTrendData() {
  trendLoading.value = true
  try {
    const params = {}
    if (filters.process_type) params.process_type = filters.process_type
    trendData.value = await analyticsApi.multiDimTrend(params)
    trendLoaded.value = true
    // 默认选择数据最丰富的组合（Budget+Achievable 同时有数据的组合优先）
    if (!trendComboFilter.value && trendComboOptions.value.length) {
      trendComboFilter.value = trendComboOptions.value[0].value
    }
  } catch (e) {
    // 已由拦截器提示
  } finally {
    trendLoading.value = false
  }
}

function onTabChange(tab) {
  if (tab === 'time' && !trendLoaded.value) {
    loadTrendData()
  }
}

// 工艺筛选变化时重新加载趋势数据
function handleProcessChange() {
  loadData()
  trendLoaded.value = false
  trendComboFilter.value = ''
  if (activeTab.value === 'time') {
    loadTrendData()
  }
}

// ============ 图表配置 ============

// 1. 工艺 × RoofType BOL 总览（柱=均值 + I型线=Min-Max + 菱形=中位数）
const overviewOption = computed(() => {
  const items = byProcessRoof.value.filter(it => it.roof_type && it.process_type)
  // 按工艺分组，组内按均值排序
  const processGroups = {}
  items.forEach(it => {
    if (!processGroups[it.process_type]) processGroups[it.process_type] = []
    processGroups[it.process_type].push(it)
  })
  // 每组内按均值降序
  Object.values(processGroups).forEach(arr => arr.sort((a, b) => b.mean - a.mean))

  // 构造 x 轴标签（工艺/RoofType）
  const labels = []
  const labelData = []  // 完整数据
  Object.entries(processGroups).forEach(([proc, arr]) => {
    arr.forEach(it => {
      labels.push(`${it.roof_type}`)
      labelData.push({ ...it, groupLabel: `${proc}/${it.roof_type}` })
    })
  })

  // 工艺分组信息（用于 x 轴分隔线）
  const processBoundaries = []
  let acc = 0
  Object.entries(processGroups).forEach(([proc, arr], idx) => {
    if (idx > 0) processBoundaries.push(acc - 0.5)
    acc += arr.length
  })

  return {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const it = labelData[p.dataIndex]
        if (!it) return ''
        return `<div style="min-width:200px">
          <b>${it.process_type} / ${it.roof_type}</b><br/>
          <span style="color:#6b7280">项目数: ${it.count}</span><br/>
          <hr style="margin:4px 0;border:none;border-top:1px solid #e5e7eb"/>
          均值: <b>${it.mean.toFixed(2)}</b> min<br/>
          中位数: <b>${it.median.toFixed(2)}</b> min<br/>
          Min-Max: <b>${it.min.toFixed(2)} ~ ${it.max.toFixed(2)}</b><br/>
          标准差: <b>${it.std.toFixed(2)}</b>
        </div>`
      }
    },
    legend: {
      data: ['均值', '中位数', 'Min-Max 范围'],
      top: 0,
      textStyle: { color: AXIS.text, fontSize: 11 }
    },
    grid: { left: 50, right: 30, top: 50, bottom: 80, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: {
        rotate: 35,
        fontSize: CHART_SPEC.labelAxis,
        color: AXIS.textDim,
        interval: 0,
      },
      splitLine: { show: false },
      axisLine: { lineStyle: { color: AXIS.lineBright } },
    },
    yAxis: {
      type: 'value',
      name: 'BOL (min)',
      nameLocation: 'middle',
      nameGap: 35,
      nameTextStyle: { fontSize: 11, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line, type: 'dashed' } },
    },
    series: [
      // 1. 均值柱状图
      {
        name: '均值',
        type: 'bar',
        data: labelData.map(it => it.mean),
        itemStyle: { color: mintGradient() },
        // 柔性柱宽：去掉固定百分比（固定 barWidth 会让 barMaxWidth 失效），随类别数自动伸缩
        ...adaptiveBarLayout(),
        label: {
          show: true,
          position: 'top',
          fontSize: CHART_SPEC.labelTick,
          color: AXIS.text,
          formatter: (p) => p.value.toFixed(1),
        },
        markLine: processBoundaries.length ? {
          symbol: 'none',
          silent: true,
          lineStyle: { color: '#94a3b8', type: 'dashed', width: 1 },
          data: processBoundaries.map(pos => [{ xAxis: pos }, { xAxis: pos }]),
        } : undefined,
      },
      // 2. Min-Max I 型线（用 custom 系列）
      {
        name: 'Min-Max 范围',
        type: 'custom',
        renderItem: (params, api) => {
          const idx = api.value(0)
          const minVal = api.value(1)
          const maxVal = api.value(2)
          const point = api.coord([idx, maxVal])
          const pointMin = api.coord([idx, minVal])
          return {
            type: 'group',
            children: [
              // 垂直线
              {
                type: 'line',
                shape: { x1: point[0], y1: point[1], x2: pointMin[0], y2: pointMin[1] },
                style: { stroke: '#94a3b8', lineWidth: 1.5 },
              },
              // 上横线
              {
                type: 'line',
                shape: { x1: point[0] - 5, y1: point[1], x2: point[0] + 5, y2: point[1] },
                style: { stroke: '#94a3b8', lineWidth: 1.5 },
              },
              // 下横线
              {
                type: 'line',
                shape: { x1: pointMin[0] - 5, y1: pointMin[1], x2: pointMin[0] + 5, y2: pointMin[1] },
                style: { stroke: '#94a3b8', lineWidth: 1.5 },
              },
            ],
          }
        },
        encode: { x: 0, y: [1, 2] },
        data: labelData.map((it, i) => [i, it.min, it.max]),
        z: 10,
      },
      // 3. 中位数菱形
      {
        name: '中位数',
        type: 'scatter',
        data: labelData.map((it, i) => [i, it.median]),
        symbol: 'diamond',
        symbolSize: 10,
        itemStyle: { color: '#f59e0b', borderColor: '#d97706', borderWidth: 1 },
        z: 11,
      },
    ],
  }
})

// 2. 跨工厂对比图（分组柱状图：同工艺+同RoofType下各工厂均值对比）
const crossPlantOption = computed(() => {
  // 按 (process_type, roof_type) 分组
  const combos = {}
  crossPlant.value.forEach(it => {
    const key = `${it.process_type}/${it.roof_type}`
    if (!combos[key]) combos[key] = []
    combos[key].push(it)
  })

  // 取项目数 ≥3 的组合（小样本对比意义有限），按总项目数降序取前 8 组
  const validCombos = Object.entries(combos)
    .filter(([, arr]) => arr.reduce((s, x) => s + x.count, 0) >= 3)
    .sort((a, b) => b[1].reduce((s, x) => s + x.count, 0) - a[1].reduce((s, x) => s + x.count, 0))
    .slice(0, 8)

  if (!validCombos.length) return {}

  // x 轴：组合标签
  const labels = validCombos.map(([key]) => key)
  // 收集所有工厂
  const plantSet = new Set()
  validCombos.forEach(([, arr]) => arr.forEach(it => plantSet.add(it.plant)))
  const plants = [...plantSet].sort()

  // 每个工厂一个 series
  const plantColors = [PALETTE[0], PALETTE[1], PALETTE[2], PALETTE[4], PALETTE[5], PALETTE[6], PALETTE[7], PALETTE[8]]
  const series = plants.map((plant, pi) => ({
    name: plant,
    type: 'bar',
    data: labels.map(key => {
      const arr = combos[key]
      const found = arr.find(it => it.plant === plant)
      return found ? found.mean : null
    }),
    itemStyle: { color: plantColors[pi % plantColors.length] },
    barGap: '10%',
    barCategoryGap: '35%',
    barMaxWidth: CHART_SPEC.barMaxWidth,
    emphasis: { focus: 'series' },
  }))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const key = params[0].axisValue
        const arr = combos[key]
        if (!arr) return ''
        let html = `<b>${key}</b><br/>`
        params.forEach(p => {
          if (p.value == null) return
          const found = arr.find(it => it.plant === p.seriesName)
          if (found) {
            html += `${p.marker} ${p.seriesName}: <b>${p.value.toFixed(2)}</b> min (n=${found.count}, 中位 ${found.median.toFixed(1)}, ${found.min.toFixed(1)}~${found.max.toFixed(1)})<br/>`
          }
        })
        return html
      }
    },
    legend: {
      top: 0,
      textStyle: { color: AXIS.text, fontSize: 11 },
      data: plants,
    },
    grid: { left: 50, right: 25, top: 50, bottom: 70, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { rotate: 30, fontSize: 10, color: AXIS.textDim, interval: 0 },
    },
    yAxis: {
      type: 'value',
      name: '均值 BOL (min)',
      nameLocation: 'middle',
      nameGap: 35,
      nameTextStyle: { fontSize: 11, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line, type: 'dashed' } },
    },
    series,
  }
})

// ===== 时间维度：多 BOL 类型对比分析 =====
const trendByYearCombo = computed(() => trendData.value?.by_year_combo || [])
const trendByYearPlantCombo = computed(() => trendData.value?.by_year_plant_combo || [])
const trendFiscalYears = computed(() => trendData.value?.fiscal_years || [])
const trendHasMultiYear = computed(() => trendFiscalYears.value.length > 1)

// 组合选项（按数据丰富度排序：Budget+Achievable 同时有数据的组合优先）
const trendComboOptions = computed(() => {
  const comboStats = {}
  trendByYearCombo.value.forEach(it => {
    if (!comboStats[it.combo]) comboStats[it.combo] = { value: it.combo, score: 0 }
    if (it.budget_mean != null) comboStats[it.combo].score += 2
    if (it.achievable_mean != null) comboStats[it.combo].score += 2
    if (it.target_mean != null) comboStats[it.combo].score += 1
  })
  return Object.values(comboStats).sort((a, b) => b.score - a.score)
})

// 图3：选定组合的 Budget / Achievable / Target 年度趋势对比
const trendTypeCompareOption = computed(() => {
  const combo = trendComboFilter.value
  if (!combo) return {}

  const items = trendByYearCombo.value.filter(it => it.combo === combo)
  if (!items.length) return {}

  const years = trendFiscalYears.value
  const typeColors = { budget: '#0ea5e9', achievable: '#f59e0b', target: '#10b981' }
  const typeLabels = { budget: 'Budget BOL', achievable: 'Achievable BOL', target: 'Target BOL' }

  const buildSeries = (field, color, label) => ({
    name: label,
    type: 'line',
    data: years.map(y => {
      const found = items.find(it => it.fiscal_year === y)
      return found ? found[field] : null
    }),
    smooth: true,
    symbol: 'circle',
    symbolSize: 9,
    lineStyle: { width: 2.5, color },
    itemStyle: { color },
    label: {
      show: true,
      position: 'top',
      fontSize: CHART_SPEC.labelTick,
      color: AXIS.text,
      formatter: (p) => p.value != null ? p.value.toFixed(1) : '',
    },
    connectNulls: false,
  })

  const series = [
    buildSeries('budget_mean', typeColors.budget, typeLabels.budget),
    buildSeries('achievable_mean', typeColors.achievable, typeLabels.achievable),
    buildSeries('target_mean', typeColors.target, typeLabels.target),
  ]

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        let html = `<div style="font-weight:600">${combo} · ${params[0].axisValue} 财年</div>`
        params.forEach(p => {
          if (p.value == null) return
          const found = items.find(it => it.fiscal_year === Number(p.axisValue))
          let extra = ''
          if (found) {
            if (p.seriesName === typeLabels.budget) extra = ` (n=${found.budget_count})`
            else if (p.seriesName === typeLabels.achievable) extra = ` (n=${found.achievable_count})`
            else if (p.seriesName === typeLabels.target) extra = ` (n=${found.target_count})`
          }
          html += `<div>${p.marker} ${p.seriesName}: <b>${p.value.toFixed(2)}</b> min${extra}</div>`
        })
        // 差距信息
        const found = items.find(it => it.fiscal_year === Number(params[0].axisValue))
        if (found && found.gap_budget_ach != null) {
          html += `<div style="margin-top:4px;color:#6b7280">Budget − Achievable 差距: <b style="color:${found.gap_budget_ach > 0 ? '#ef4444' : '#10b981'}">${found.gap_budget_ach > 0 ? '+' : ''}${found.gap_budget_ach}</b> min`
          if (found.gap_pct != null) html += ` (${found.gap_pct > 0 ? '+' : ''}${found.gap_pct}%)`
          html += `</div>`
        }
        return html
      }
    },
    legend: {
      top: 0,
      textStyle: { color: AXIS.text, fontSize: 11 },
      data: [typeLabels.budget, typeLabels.achievable, typeLabels.target],
    },
    grid: { left: 50, right: 30, top: 50, bottom: 40, containLabel: true },
    xAxis: {
      type: 'category',
      data: years.map(String),
      axisLabel: { color: AXIS.textDim, fontSize: 11 },
      axisLine: { lineStyle: { color: AXIS.lineBright } },
    },
    yAxis: {
      type: 'value',
      name: 'BOL (min)',
      nameLocation: 'middle',
      nameGap: 35,
      nameTextStyle: { fontSize: 11, color: AXIS.textDim },
      axisLabel: { color: AXIS.textDim, fontSize: 11 },
      splitLine: { lineStyle: { color: AXIS.line, type: 'dashed' } },
    },
    series,
  }
})

// 图5：按 RoofType+Process 组合分图，每个组合一个趋势图（各工厂年度 BOL 均值对比）
// 不再使用加权平均（无意义），改为每个组合独立展示各工厂的年度 BOL 均值走势
const trendComboChartList = computed(() => {
  const items = trendByYearPlantCombo.value
  if (!items.length) return []

  const years = trendFiscalYears.value

  // 收集所有组合及其数据量，按数据量降序排列
  const comboStats = {}
  items.forEach(it => {
    if (!it.combo) return
    comboStats[it.combo] = (comboStats[it.combo] || 0) + it.count
  })
  const allCombos = Object.entries(comboStats)
    .sort((a, b) => b[1] - a[1])
    .map(([combo]) => combo)

  const lineColors = [PALETTE[0], PALETTE[1], PALETTE[2], PALETTE[4], PALETTE[5], PALETTE[6], PALETTE[7], PALETTE[8]]

  return allCombos.map(combo => {
    const comboItems = items.filter(it => it.combo === combo)
    // 收集该组合下所有工厂
    const plantSet = new Set()
    comboItems.forEach(it => { if (it.plant) plantSet.add(it.plant) })
    const plants = [...plantSet].sort()

    const series = plants.map((plant, pi) => {
      const data = years.map(y => {
        const found = comboItems.find(it => it.fiscal_year === y && it.plant === plant)
        return found ? found.mean : null
      })
      return {
        name: plant,
        type: 'line',
        data,
        smooth: true,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2, color: lineColors[pi % lineColors.length] },
        itemStyle: { color: lineColors[pi % lineColors.length] },
        label: {
          show: true,
          position: 'top',
          fontSize: 9,
          color: AXIS.textDim,
          formatter: (p) => p.value != null ? p.value.toFixed(1) : '',
        },
        connectNulls: false,
      }
    })

    const [roof, proc] = combo.split('+')
    const procLabel = proc === 'IHE' ? 'IHE（厂内包边）' : proc === 'IHR' ? 'IHR（厂内卷帘）' : proc === 'FA' ? 'FA（总装）' : proc

    return {
      combo,
      option: {
        tooltip: {
          trigger: 'axis',
          formatter: (params) => {
            let html = `<div style="font-weight:600">${combo} · ${params[0].axisValue} 财年</div>`
            html += `<div style="color:#6b7280;font-size:11px;margin-bottom:4px">${roof} + ${procLabel}</div>`
            params.forEach(p => {
              if (p.value == null) return
              const found = comboItems.find(it => it.fiscal_year === Number(p.axisValue) && it.plant === p.seriesName)
              const n = found ? found.count : 0
              const med = found ? found.median.toFixed(1) : '-'
              html += `<div>${p.marker} ${p.seriesName}: <b>${p.value.toFixed(2)}</b> min (n=${n}, 中位 ${med})</div>`
            })
            return html
          }
        },
        legend: {
          top: 0,
          textStyle: { color: AXIS.text, fontSize: 11 },
          data: plants,
        },
        grid: { left: 50, right: 30, top: 50, bottom: 40, containLabel: true },
        xAxis: {
          type: 'category',
          data: years.map(String),
          axisLabel: { color: AXIS.textDim, fontSize: 11 },
          axisLine: { lineStyle: { color: AXIS.lineBright } },
        },
        yAxis: {
          type: 'value',
          name: 'BOL 均值 (min)',
          nameLocation: 'middle',
          nameGap: 35,
          nameTextStyle: { fontSize: 11, color: AXIS.textDim },
          axisLabel: { color: AXIS.textDim, fontSize: 11 },
          splitLine: { lineStyle: { color: AXIS.line, type: 'dashed' } },
        },
        series,
      }
    }
  })
})

// 时间维度明细表数据（三类型对比 + 差距）
const trendTableData = computed(() => trendByYearCombo.value)

// 财年选项
const fiscalYearOptions = computed(() => {
  const years = summary.value.fiscal_years || []
  return [
    { label: '全部财年', value: '' },
    ...years.map(y => ({ label: `${y} 财年`, value: y })),
  ]
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="综合多维度 BOL 分析"
      icon="DataAnalysis"
      subtitle="基于 Budget/Achievable BOL 数据，从工艺类型 × Roof Type × 工厂 × 财年 四个维度综合分析 BOL 分布特征与跨工厂差异。"
      :breadcrumbs="[{ label: '分析中心' }, { label: '综合多维度分析' }]"
    />
    <div class="page-container">

    <!-- 筛选 -->
    <div class="filter-bar">
      <span class="filter-label">BOL 类型：</span>
      <el-select v-model="filters.bol_type" style="width: 220px" @change="loadData">
        <el-option v-for="opt in bolTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <span class="filter-label">财年：</span>
      <el-select v-model="filters.fiscal_year" style="width: 140px" @change="loadData">
        <el-option v-for="opt in fiscalYearOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <span class="filter-label">工艺：</span>
      <el-select v-model="filters.process_type" style="width: 160px" @change="handleProcessChange">
        <el-option v-for="opt in processTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-button @click="handleReset">
        <el-icon><Refresh /></el-icon>
        <span>重置</span>
      </el-button>
    </div>

    <!-- 汇总指标卡 -->
    <div class="summary-grid">
      <div class="summary-item">
        <div class="summary-label">总项目数</div>
        <div class="summary-value text-mono">{{ summary.total_projects }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">工厂数</div>
        <div class="summary-value text-mono">{{ summary.plant_count }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">工艺类型数</div>
        <div class="summary-value text-mono">{{ summary.process_type_count }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">Roof Type 数</div>
        <div class="summary-value text-mono">{{ summary.roof_type_count }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">覆盖财年</div>
        <div class="summary-value text-mono">{{ (summary.fiscal_years || []).join(' / ') || '-' }}</div>
      </div>
    </div>

    <!-- 分析维度 Tab -->
    <el-tabs v-model="activeTab" class="analysis-tabs" @tab-change="onTabChange">
      <!-- Tab 1: 工艺 × RoofType 总览 -->
      <el-tab-pane label="工艺 × RoofType 总览" name="overview">
        <ChartCard
          title="工艺 × RoofType BOL 分布总览"
          subtitle="蓝柱=均值（柱顶标注）· 灰色 I 型线=Min-Max 范围 · 橙色菱形=中位数 · 虚线分隔不同工艺"
          :option="overviewOption"
          :height="400"
        />
        <div class="table-container">
          <el-table :data="byProcessRoof" stripe border size="small" style="width: 100%" max-height="420">
            <el-table-column prop="process_type" label="工艺" width="80" fixed="left" />
            <el-table-column prop="roof_type" label="Roof Type" min-width="140" show-overflow-tooltip />
            <el-table-column prop="count" label="项目数" width="80" align="right" />
            <el-table-column label="均值 (min)" width="100" align="right">
              <template #default="{ row }">{{ row.mean.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="中位数 (min)" width="110" align="right">
              <template #default="{ row }">{{ row.median.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="Min (min)" width="100" align="right">
              <template #default="{ row }">{{ row.min.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="Max (min)" width="100" align="right">
              <template #default="{ row }">{{ row.max.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="标准差" width="90" align="right">
              <template #default="{ row }">{{ row.std.toFixed(2) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- Tab 2: 跨工厂对比 -->
      <el-tab-pane label="跨工厂对比" name="cross-plant">
        <ChartCard
          title="同工艺+同 RoofType 下各工厂 BOL 均值对比"
          subtitle="仅展示 ≥2 个工厂的工艺+RoofType 组合 · tooltip 含项目数/中位数/范围 · 用于识别工厂间效率差异"
          :option="crossPlantOption"
          :height="400"
        />
        <div class="table-container">
          <el-table :data="crossPlant" stripe border size="small" style="width: 100%" max-height="420">
            <el-table-column prop="process_type" label="工艺" width="80" fixed="left" />
            <el-table-column prop="roof_type" label="Roof Type" min-width="140" show-overflow-tooltip />
            <el-table-column prop="plant" label="工厂" width="90" />
            <el-table-column prop="count" label="项目数" width="80" align="right" />
            <el-table-column label="均值 (min)" width="100" align="right">
              <template #default="{ row }">{{ row.mean.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="中位数 (min)" width="110" align="right">
              <template #default="{ row }">{{ row.median.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="Min (min)" width="100" align="right">
              <template #default="{ row }">{{ row.min.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="Max (min)" width="100" align="right">
              <template #default="{ row }">{{ row.max.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="标准差" width="90" align="right">
              <template #default="{ row }">{{ row.std.toFixed(2) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- Tab 3: 时间维度（多 BOL 类型对比） -->
      <el-tab-pane label="时间维度" name="time">
        <div v-loading="trendLoading">
          <el-alert
            v-if="!trendLoading && !trendHasMultiYear && trendLoaded"
            type="info"
            :closable="false"
            title="当前仅有一个财年的数据，时间维度趋势分析需要至少两年的数据。请在预算BOL模块导入多年数据后查看。"
            style="margin-bottom: 16px"
          />
          <el-alert
            v-if="trendHasMultiYear"
            type="success"
            :closable="false"
            title="时间维度分析：对比 Budget / Achievable / Target 三种 BOL 类型的年度变化趋势，识别改善空间与达成情况"
            style="margin-bottom: 16px"
          />
          <template v-if="trendHasMultiYear">
            <!-- 组合筛选器 -->
            <div class="trend-filter-bar">
              <span class="filter-label">查看组合：</span>
              <el-select v-model="trendComboFilter" style="width: 220px" placeholder="选择 RoofType+工艺 组合">
                <el-option v-for="opt in trendComboOptions" :key="opt.value" :label="opt.value" :value="opt.value" />
              </el-select>
              <span class="filter-hint">选择一个 RoofType+工艺 组合，查看该组合下 Budget / Achievable / Target 三种 BOL 的年度对比趋势</span>
            </div>

            <!-- 图1：选定组合的三类型年度趋势对比 -->
            <ChartCard
              v-if="trendComboFilter"
              :title="`${trendComboFilter} · Budget / Achievable / Target 年度对比`"
              subtitle="蓝线=Budget BOL（预算） · 橙线=Achievable BOL（可达） · 绿线=Target BOL（目标） · tooltip 含样本数和 Budget-Achievable 差距"
              :option="trendTypeCompareOption"
              :height="400"
            />

            <!-- 图2-N：按 RoofType+Process 组合分图，每个组合一个各工厂年度趋势对比 -->
            <div class="combo-charts-section">
              <div class="combo-charts-title">各 RoofType+Process 组合 · 工厂间年度 BOL 均值趋势对比</div>
              <div class="combo-charts-hint">每种产品类型+工艺类型独立展示 · 每条线代表一个工厂 · 用于对比同一组合下不同工厂的效率差异和改善趋势</div>
              <ChartCard
                v-for="chart in trendComboChartList"
                :key="chart.combo"
                :title="`${chart.combo} · 各工厂年度 BOL 均值趋势`"
                :subtitle="`每条线代表一个工厂 · tooltip 含样本数和中位数 · 用于识别同组合下工厂间效率差异`"
                :option="chart.option"
                :height="340"
                style="margin-bottom: 16px"
              />
            </div>

            <!-- 明细表：三类型对比 + 差距 -->
            <div class="table-container">
              <div class="table-title">三类型 BOL 年度对比明细</div>
              <el-table :data="trendTableData" stripe border size="small" style="width: 100%" max-height="420">
                <el-table-column prop="fiscal_year" label="财年" width="80" fixed="left" />
                <el-table-column prop="combo" label="组合" width="130" fixed="left" />
                <el-table-column prop="roof_type" label="Roof Type" min-width="120" show-overflow-tooltip />
                <el-table-column prop="process_type" label="工艺" width="70" />
                <el-table-column label="Budget 均值" width="110" align="right">
                  <template #default="{ row }">
                    <span v-if="row.budget_mean != null">{{ row.budget_mean.toFixed(2) }}</span>
                    <span v-else class="text-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="Budget 样本" width="90" align="right">
                  <template #default="{ row }">{{ row.budget_count || 0 }}</template>
                </el-table-column>
                <el-table-column label="Achievable 均值" width="120" align="right">
                  <template #default="{ row }">
                    <span v-if="row.achievable_mean != null">{{ row.achievable_mean.toFixed(2) }}</span>
                    <span v-else class="text-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="Achievable 样本" width="110" align="right">
                  <template #default="{ row }">{{ row.achievable_count || 0 }}</template>
                </el-table-column>
                <el-table-column label="Target 均值" width="110" align="right">
                  <template #default="{ row }">
                    <span v-if="row.target_mean != null">{{ row.target_mean.toFixed(2) }}</span>
                    <span v-else class="text-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="Target 样本" width="90" align="right">
                  <template #default="{ row }">{{ row.target_count || 0 }}</template>
                </el-table-column>
                <el-table-column label="Budget−Achievable 差距" width="150" align="right">
                  <template #default="{ row }">
                    <span v-if="row.gap_budget_ach != null" :style="{ color: row.gap_budget_ach > 0 ? '#ef4444' : '#10b981', fontWeight: 600 }">
                      {{ row.gap_budget_ach > 0 ? '+' : '' }}{{ row.gap_budget_ach }}
                    </span>
                    <span v-else class="text-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="差距百分比" width="110" align="right">
                  <template #default="{ row }">
                    <span v-if="row.gap_pct != null" :style="{ color: row.gap_pct > 0 ? '#ef4444' : '#10b981' }">
                      {{ row.gap_pct > 0 ? '+' : '' }}{{ row.gap_pct }}%
                    </span>
                    <span v-else class="text-muted">-</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </div>
      </el-tab-pane>
    </el-tabs>

    </div>
  </div>
</template>

<style scoped>
/* filter-bar / filter-label 统一由 main.css 全局规范接管（标准卡片式） */

.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.summary-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 14px 16px;
  text-align: center;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--transition);
}

.summary-item:hover {
  border-color: var(--color-border-bright);
  box-shadow: var(--shadow);
}

.summary-label {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 6px;
}

.summary-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-primary);
  line-height: 1.2;
}

.analysis-tabs {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 0 16px 16px;
}

.analysis-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.analysis-tabs :deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 500;
}

.table-container {
  margin-top: 16px;
}

.table-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 10px;
  padding-left: 8px;
  border-left: 3px solid var(--color-primary);
}

.trend-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  margin-bottom: 16px;
}

.filter-hint {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-left: 8px;
}

@media (max-width: 1024px) {
  .summary-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 640px) {
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.text-muted {
  color: var(--color-text-muted);
}

.combo-charts-section {
  margin-bottom: 16px;
}

.combo-charts-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 4px;
  padding-left: 8px;
  border-left: 3px solid var(--color-primary);
}

.combo-charts-hint {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 12px;
  padding-left: 11px;
}
</style>

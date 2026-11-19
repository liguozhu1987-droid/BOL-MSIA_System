<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { analyticsApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import { PALETTE, AXIS, withAlpha, CHART_SPEC, yoyYearColor, YOY_CHANGE, IMPROVE_HOURS, mintGradient, dangerGradient, buildValueLabelConfig } from '@/utils/echartsTheme'
import { nearDoubleAnomaly, nearDoubleAnomalyText } from '@/utils/format'

// 看板数据
const dashboardData = ref(null)
const loading = ref(false)

// Tab 3 筛选条件（顶层 ref，template 可直接 v-model）
const selectedYear = ref(null) // null = 采用后端默认（当前财年）
const selectedPlants = ref([])
const selectedProcessTypes = ref([])
const selectedRoofTypes = ref([])

// Tab 2 同比哑铃图筛选条件 + 数据（独立接口，支持工厂/年份/TopN 联动）
const yoyData = ref(null)
const yoyPlants = ref([])
const yoyYears = ref([]) // 默认 [本年, 上年]，由后端 selected_years 初始化
const yoyTopN = ref(10)
const yoyLoading = ref(false)

// Tab 3.5 改善目标对比（独立接口，懒加载：首次切入 Tab 时请求）
const improveData = ref(null)
const improveLoading = ref(false)

const targetBarGradient = (value, target) =>
  Number(value) >= target ? mintGradient() : dangerGradient()
const improveLoaded = ref(false)
const improveDrill = ref(null) // {plant, metric: 'budget'|'target'|'achievable'} 点击散点下钻

// 工厂选项（标准化短代码）
const plantOptions = ['CJ', 'BJ', 'SH', 'CQ', 'GZ', 'WH', 'CMC', 'YT']
const processTypeOptions = ['FA', 'IHR', 'IHE']
// 产品类型选项：动态来自后端（cbco_records.typ_of_roof 实际值）

// 活跃 Tab
const activeTab = ref('t1')

// ============ 数据切片 ============
const kpiCards = computed(() => dashboardData.value?.kpi_cards || {})
const bolLifecycle = computed(() => dashboardData.value?.bol_lifecycle || [])
const lifecyclePlantOptions = computed(() => dashboardData.value?.bol_lifecycle_plant_options || [])
const improvementOpportunities = computed(() => dashboardData.value?.improvement_opportunities || [])
// Tab 2 副表：Achievable BOL 同比上升项目清单（全量）
const improvementIncreases = computed(() => dashboardData.value?.improvement_increases || [])

// Tab 1 BOL全链路：工厂筛选器
const lifecyclePlants = ref([])
// Tab 2 同比哑铃图数据切片
const yoyItems = computed(() => yoyData.value?.items || [])
const yoySelectedYears = computed(() => (yoyData.value?.selected_years || []).slice().sort((a, b) => a - b))
const yoyYearOptions = computed(() => yoyData.value?.options?.years || [])
const yoyPlantOptions = computed(() => yoyData.value?.options?.plants || [])
const yearlyCompare = computed(() => dashboardData.value?.yearly_compare || { years: [], budget: [], achievable: [] })
const plantCompare = computed(() => dashboardData.value?.plant_compare || {})
const plantCompareStats = computed(() => plantCompare.value.stats || [])
const yearOptions = computed(() => plantCompare.value.available_years || [])
const roofTypeOptions = computed(() => plantCompare.value.roof_type_options || [])
const plantAchievement = computed(() => dashboardData.value?.plant_achievement || [])
// HRDB CN_AME_KPI_monthlyHistory 官方 KPI（最新月份，按工厂 + CMC 区域汇总值）
const ameKpis = computed(() => dashboardData.value?.ame_kpis || {})

// ============ 图表配置 ============

// Tab 1 主图: BOL 全链路对比（保留实测BOL ⚠️ 异常分段堆叠，TOP 20）
const bolLifecycleOption = computed(() => {
  const items = bolLifecycle.value
  const labels = items.map(it => `${it.project_code}/${it.process_type}`)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const it = items[idx]
        let html = `<b>${it.project_code}</b>/${it.process_type}`
        if (it.plant) html += ` <span style="color:${AXIS.textDim}">(${it.plant})</span>`
        html += '<br/>'
        if (it.project_name) html += `描述: ${it.project_name}<br/>`
        html += `Budget: ${it.budget}<br/>`
        html += `Achievable: ${it.achievable}<br/>`
        if (it.target) html += `Target: ${it.target}<br/>`
        if (it.actual) {
          const warnTag = it.actual_ach_gap_pct !== null && Math.abs(it.actual_ach_gap_pct) > 10
            ? ` <span style="color:${PALETTE[4]}">⚠️ 实测CT需确认准确性</span>`
            : ''
          html += `实测BOL: ${it.actual}${warnTag}<br/>`
        }
        html += `Volume: ${it.volume || 0}<br/>`
        html += `<b>差距: ${it.gap > 0 ? '+' : ''}${it.gap}</b>`
        return html
      }
    },
    legend: {
      data: ['Budget', 'Achievable', 'Target', '实测BOL', '实测BOL ⚠️'],
      top: 0,
      textStyle: { color: AXIS.text, fontSize: 11 }
    },
    grid: CHART_SPEC.gridTall,
    xAxis: {
      type: 'category',
      data: labels,
      name: '项目代码/工艺',
      nameLocation: 'middle',
      nameGap: 70,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: {
        fontSize: CHART_SPEC.labelAxis,
        rotate: 40,
        interval: 0,
        color: (value, index) => {
          const it = items[index]
          if (it && it.actual_ach_gap_pct !== null && Math.abs(it.actual_ach_gap_pct) > 10) return PALETTE[4]
          return AXIS.textDim
        },
        fontWeight: (value, index) => {
          const it = items[index]
          if (it && it.actual_ach_gap_pct !== null && Math.abs(it.actual_ach_gap_pct) > 10) return 'bold'
          return 'normal'
        },
      }
    },
    yAxis: {
      type: 'value',
      name: 'BOL 值',
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim }
    },
    series: [
      { name: 'Budget', type: 'bar', data: items.map(it => it.budget), itemStyle: { color: PALETTE[0] }, barGap: '10%', barMaxWidth: CHART_SPEC.barMaxWidth },
      { name: 'Achievable', type: 'bar', data: items.map(it => it.achievable), itemStyle: { color: PALETTE[1] }, barMaxWidth: CHART_SPEC.barMaxWidth },
      { name: 'Target', type: 'bar', data: items.map(it => it.target || null), itemStyle: { color: PALETTE[3] }, barMaxWidth: CHART_SPEC.barMaxWidth },
      {
        name: '实测BOL',
        type: 'bar',
        stack: 'actual',
        barMaxWidth: CHART_SPEC.barMaxWidth,
        data: items.map(it => {
          if (!it.actual) return null
          const isWarn = it.actual_ach_gap_pct !== null && Math.abs(it.actual_ach_gap_pct) > 10
          return isWarn ? null : it.actual
        }),
        itemStyle: { color: PALETTE[2] },
      },
      {
        name: '实测BOL ⚠️',
        type: 'bar',
        stack: 'actual',
        barMaxWidth: CHART_SPEC.barMaxWidth,
        data: items.map(it => {
          if (!it.actual) return null
          const isWarn = it.actual_ach_gap_pct !== null && Math.abs(it.actual_ach_gap_pct) > 10
          return isWarn ? it.actual : null
        }),
        itemStyle: { color: PALETTE[4] },
      },
    ]
  }
})

// Tab 2 主图: Achievable BOL 同比哑铃图（散点=各年份实际值 + 年份连线）
// 连线语义: 后一年更小(改善)=绿色 / 后一年更大(恶化)=红色
const achievableYoyOption = computed(() => {
  const items = yoyItems.value
  const years = yoySelectedYears.value
  if (!items.length || years.length < 2) return {}

  // 对比数据异常检测：任意相邻年份对接近 2 倍关系（偏差≈±50%）时标记 ⚠，
  // 疑似导入/提交不规范（如双线项目只提交一条线的数据）
  const anomalyFlags = items.map((it) => {
    const ys = years.filter(y => it.values[String(y)] != null)
    for (let i = 0; i < ys.length - 1; i++) {
      if (nearDoubleAnomaly(it.values[String(ys[i])], it.values[String(ys[i + 1])])) return true
    }
    return false
  })
  const labels = items.map((it, idx) =>
    `${it.label || `${it.project_code}/${it.process_type}`}${anomalyFlags[idx] ? ' ⚠' : ''}`
  )

  // 相邻年份连线段: value=[X索引, 前值, 后值]，颜色在 renderItem 中按升降判断
  const segments = []
  items.forEach((it, idx) => {
    const ys = years.filter(y => it.values[String(y)] != null)
    for (let i = 0; i < ys.length - 1; i++) {
      segments.push({
        value: [idx, it.values[String(ys[i])], it.values[String(ys[i + 1])]],
        fromYear: ys[i],
        toYear: ys[i + 1],
        item: it,
      })
    }
  })

  // Y 轴自适应范围（哑铃图不从 0 开始，留 15% 视觉余量放大差异）
  const vals = []
  items.forEach(it => Object.values(it.values || {}).forEach(v => { if (v != null) vals.push(v) }))
  const vMin = vals.length ? Math.min(...vals) : 0
  const vMax = vals.length ? Math.max(...vals) : 1
  const pad = (vMax - vMin) * 0.15 || Math.max(1, vMax * 0.05)

  // 每个年份一个独立散点系列（固定颜色，保证图例-颜色一致）
  const scatterSeries = years.map(y => ({
    name: String(y),
    type: 'scatter',
    z: 5,
    symbolSize: 9,
    itemStyle: {
      color: yoyYearColor(years, y),
      borderColor: '#ffffff',
      borderWidth: 1,
    },
    label: buildValueLabelConfig('scatter', items.length, {
      position: 'left',
      formatter: (params) => Number(params.value[1]).toFixed(2)
    }),
    data: items
      .map((it, idx) => ({ value: [idx, it.values[String(y)]], item: it }))
      .filter(d => d.value[1] != null),
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        if (p.seriesType === 'custom') {
          const d = p.data
          const it = d.item
          const diff = d.value[2] - d.value[1]
          const pct = d.value[1] > 0 ? (diff / d.value[1]) * 100 : 0
          const improve = diff < 0
          const color = improve ? YOY_CHANGE.down : YOY_CHANGE.up
          // 异常提示块：琥珀左边线 + 浅底，说明倍数关系并建议核实
          const warn = nearDoubleAnomaly(d.value[1], d.value[2])
            ? `<div style="margin-top:4px;padding:3px 6px;border-left:3px solid ${PALETTE[1]};background:${withAlpha(PALETTE[1], 0.1)};color:${PALETTE[1]};font-size:11px">⚠ 数据异常提示：${nearDoubleAnomalyText(d.value[1], d.value[2])}</div>`
            : ''
          return `<b>${it.label || it.project_code + '/' + it.process_type}</b> · ${it.plant}<br/>` +
            `${d.fromYear} → ${d.toYear} 同比<br/>` +
            `${d.fromYear}: ${d.value[1]} → ${d.toYear}: ${d.value[2]}<br/>` +
            `变化: <b style="color:${color}">${diff > 0 ? '+' : ''}${diff.toFixed(2)}</b>` +
            ` (${pct > 0 ? '+' : ''}${pct.toFixed(1)}%) ${improve ? '↓ 改善' : '↑ 恶化'}` + warn
        }
        const it = p.data.item
        return `<b>${it.label || it.project_code + '/' + it.process_type}</b> · ${it.plant}<br/>` +
          (it.project_name ? `项目: ${it.project_name}<br/>` : '') +
          `${p.seriesName}年 Achievable BOL: <b>${p.value[1]}</b><br/>` +
          `Volume: ${it.volume || 0}`
      }
    },
    legend: {
      data: years.map(String),
      top: 0,
      textStyle: { color: AXIS.text, fontSize: CHART_SPEC.labelAxis },
    },
    grid: { left: 60, right: 30, top: 50, bottom: 80, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { fontSize: CHART_SPEC.labelAxis, color: AXIS.textDim, rotate: 40, interval: 0 },
      axisLine: { lineStyle: { color: AXIS.line } },
      axisTick: { lineStyle: { color: AXIS.line } },
    },
    yAxis: {
      type: 'value',
      name: 'Achievable BOL',
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      min: Math.max(0, Math.floor((vMin - pad) * 100) / 100),
      max: Math.ceil((vMax + pad) * 100) / 100,
      axisLabel: { fontSize: CHART_SPEC.labelAxis, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line } },
    },
    series: [
      {
        name: '同比连线',
        type: 'custom',
        z: 3,
        silent: false,
        renderItem: (params, api) => {
          const x = api.value(0)
          const p1 = api.coord([x, api.value(1)])
          const p2 = api.coord([x, api.value(2)])
          const improve = api.value(2) < api.value(1)
          return {
            type: 'line',
            shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] },
            style: {
              stroke: improve ? YOY_CHANGE.down : YOY_CHANGE.up,
              lineWidth: 2.5,
              lineCap: 'round',
            },
          }
        },
        data: segments,
      },
      ...scatterSeries,
    ],
  }
})

// ============ Tab 2 副图: 近 3 年 Budget vs Achievable（三级钻取） ============
// 层级: year（年度总量）→ plant（该年各工厂）→ process（该年该工厂各工艺）
const yearlyDrill = ref({ level: 'year', year: null, plant: null })

// 钻取各层的数据（由 detail 扁平明细聚合，保证层级间口径一致）
const yearlyDrillData = computed(() => {
  const data = yearlyCompare.value
  const detail = data.detail || []
  if (!detail.length) return { labels: [], budget: [], achievable: [] }

  const agg = {}
  const add = (key, budget, achievable) => {
    if (!agg[key]) agg[key] = { budget: 0, achievable: 0 }
    agg[key].budget += budget
    agg[key].achievable += achievable
  }

  if (yearlyDrill.value.level === 'year') {
    detail.forEach(d => add(String(d.year), d.budget, d.achievable))
    // 保持年份升序
    const labels = Object.keys(agg).sort()
    return {
      labels,
      budget: labels.map(l => Math.round(agg[l].budget * 100) / 100),
      achievable: labels.map(l => Math.round(agg[l].achievable * 100) / 100),
    }
  }
  if (yearlyDrill.value.level === 'plant') {
    detail.filter(d => String(d.year) === yearlyDrill.value.year)
      .forEach(d => add(d.plant, d.budget, d.achievable))
  } else if (yearlyDrill.value.level === 'process') {
    detail.filter(d => String(d.year) === yearlyDrill.value.year && d.plant === yearlyDrill.value.plant)
      .forEach(d => add(d.process, d.budget, d.achievable))
  }
  const labels = Object.keys(agg).sort((a, b) => agg[b].budget + agg[b].achievable - agg[a].budget - agg[a].achievable)
  return {
    labels,
    budget: labels.map(l => Math.round(agg[l].budget * 100) / 100),
    achievable: labels.map(l => Math.round(agg[l].achievable * 100) / 100),
  }
})

// 各层级的标题/副标题
const yearlyDrillTitle = computed(() => {
  const { level, year, plant } = yearlyDrill.value
  if (level === 'year') return { title: '近 3 年 Budget vs Achievable 总量', subtitle: '点击柱子下钻至各工厂 · BOL 年度趋势' }
  if (level === 'plant') return { title: `${year} 财年 · 各工厂对比`, subtitle: '点击柱子下钻至该工厂各工艺' }
  return { title: `${year} 财年 · ${plant} 工厂 · 各工艺对比`, subtitle: 'FA / IHE / IHR / bonding 等 · 点击面包屑返回上层' }
})

// 图表点击 → 下钻
function onYearlyChartClick(params) {
  if (params.componentType !== 'series') return
  const name = params.name
  if (!name) return
  if (yearlyDrill.value.level === 'year') {
    yearlyDrill.value = { level: 'plant', year: name, plant: null }
  } else if (yearlyDrill.value.level === 'plant') {
    yearlyDrill.value = { level: 'process', year: yearlyDrill.value.year, plant: name }
  }
  // process 层不再下钻
}

// 面包屑跳转
function setYearlyLevel(level) {
  if (level === 'year') yearlyDrill.value = { level: 'year', year: null, plant: null }
  else if (level === 'plant') yearlyDrill.value = { level: 'plant', year: yearlyDrill.value.year, plant: null }
}

// 返回上一层级（process→plant→year）
function backYearlyOneLevel() {
  const { level, year } = yearlyDrill.value
  if (level === 'process') yearlyDrill.value = { level: 'plant', year, plant: null }
  else yearlyDrill.value = { level: 'year', year: null, plant: null }
}

const yearlyCompareOption = computed(() => {
  const { labels, budget, achievable } = yearlyDrillData.value
  if (!labels.length) return {}
  const { level } = yearlyDrill.value
  const xName = level === 'year' ? '财年' : (level === 'plant' ? '工厂' : '工艺')

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const b = budget[idx]
        const a = achievable[idx]
        const gap = (b - a).toFixed(2)
        const head = level === 'year' ? `${labels[idx]} 财年`
          : level === 'plant' ? `${labels[idx]} 工厂（${yearlyDrill.value.year}）`
          : `${labels[idx]} 工艺（${yearlyDrill.value.year} · ${yearlyDrill.value.plant}）`
        const hint = level !== 'process' ? '<br/><i>点击下钻</i>' : ''
        return `<b>${head}</b><br/>` +
               `Budget 总量: ${b}<br/>` +
               `Achievable 总量: ${a}<br/>` +
               `差距: <b>${gap > 0 ? '+' : ''}${gap}</b>${hint}`
      }
    },
    legend: { data: ['Budget 总量', 'Achievable 总量'], top: 0, textStyle: { color: AXIS.text, fontSize: 11 } },
    grid: { left: 50, right: 25, top: 50, bottom: 40, containLabel: true },
    xAxis: {
      type: 'category',
      name: xName,
      data: labels,
      axisLabel: { fontSize: 11, color: AXIS.textDim, interval: 0, rotate: labels.length > 8 ? 30 : 0 }
    },
    yAxis: {
      type: 'value',
      name: 'BOL 总量',
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim }
    },
    series: [
      {
        name: 'Budget 总量', type: 'bar', data: budget,
        itemStyle: { color: PALETTE[0] },
        barMaxWidth: CHART_SPEC.barMaxWidth,
        label: buildValueLabelConfig('bar', labels.length, {
          position: 'top',
          formatter: (params) => Number(params.value).toFixed(1)
        }),
        // 非末层提示可点击下钻
        cursor: level === 'process' ? 'default' : 'pointer'
      },
      {
        name: 'Achievable 总量', type: 'bar', data: achievable,
        itemStyle: { color: PALETTE[1] },
        barMaxWidth: CHART_SPEC.barMaxWidth,
        label: buildValueLabelConfig('bar', labels.length, {
          position: 'top',
          formatter: (params) => Number(params.value).toFixed(1)
        }),
        cursor: level === 'process' ? 'default' : 'pointer'
      }
    ]
  }
})

// Tab 3 主图: 各工厂 Achievable BOL 分布（箱线图 + 均值菱形标记，X=工厂）
const plantCompareOption = computed(() => {
  const stats = plantCompareStats.value
  if (!stats.length) return {}

  return {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        // 通过闭包直接读取统计数组（不依赖 ECharts 对附加数据的传递）
        const s = stats[p.dataIndex]
        if (!s) return ''
        if (p.seriesType === 'boxplot') {
          return `<b>${s.plant}</b>（${parseInt(s.count)} 个项目）<br/>` +
                 `最大值: ${s.max}<br/>Q3: ${s.q3}<br/>中位数: ${s.median}<br/>` +
                 `Q1: ${s.q1}<br/>最小值: ${s.min}<br/>均值: ${s.mean}`
        }
        return `<b>${s.plant}</b>（${parseInt(s.count)} 个项目）<br/>均值: ${s.mean}`
      }
    },
    legend: { data: ['BOL 分布', '均值'], top: 0, textStyle: { color: AXIS.text, fontSize: 11 } },
    grid: { left: 56, right: 32, top: 52, bottom: 56, containLabel: true },
    xAxis: {
      type: 'category',
      data: stats.map(s => s.plant),
      name: '工厂',
      nameLocation: 'middle',
      nameGap: 32,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 12, interval: 0, color: AXIS.text, margin: 10 }
    },
    yAxis: {
      type: 'value',
      name: 'Achievable BOL',
      nameLocation: 'middle',
      nameGap: 48,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim },
      min: (val) => Math.max(0, val.min * 0.92),
      max: (val) => val.max * 1.15,
      scale: true,
    },
    series: [
      {
        name: 'BOL 分布',
        type: 'boxplot',
        clip: true,
        // 附加位 [mean, count] 供 tooltip 展示（ECharts 箱线图取前 5 位绘制）
        data: stats.map(s => [s.min, s.q1, s.median, s.q3, s.max, s.mean, s.count]),
        itemStyle: { color: withAlpha(PALETTE[0], 0.2), borderColor: PALETTE[0] },
        boxWidth: ['28%', '52%'],
        label: buildValueLabelConfig('boxplot', stats.length, {
          position: 'insideTop',
          distance: 2,
          formatter: (params) => Number(params.value[5] ?? params.value).toFixed(2)
        })
      },
      {
        name: '均值',
        type: 'scatter',
        symbol: 'diamond',
        symbolSize: 8,
        clip: true,
        data: stats.map(s => s.mean),
        itemStyle: { color: PALETTE[1], borderColor: '#fff', borderWidth: 1 },
        label: buildValueLabelConfig('scatter', stats.length, {
          position: 'top',
          distance: 5,
          formatter: (params) => Number(params.value).toFixed(2)
        })
      }
    ]
  }
})

// Tab 3 图表标题/副标题（反映当前筛选）
const plantCompareTitle = computed(() => {
  const y = plantCompare.value.year
  const parts = []
  if (selectedProcessTypes.value.length) parts.push(`工艺 ${selectedProcessTypes.value.join('/')}`)
  if (selectedRoofTypes.value.length) parts.push(`产品 ${selectedRoofTypes.value.join('/')}`)
  const scope = parts.length ? parts.join(' · ') : '全部项目'
  const total = plantCompareStats.value.reduce((acc, s) => acc + (s.count || 0), 0)
  return {
    title: `${y} 财年 · 各工厂 Achievable BOL 分布`,
    subtitle: `筛选范围: ${scope} · 共 ${total} 个项目 · 箱线图: 最小/Q1/中位/Q3/最大 ◆ 均值 · 点击箱线图查看数据明细`
  }
})

// Tab 4 图 1: BOL 年度更新率（垂直柱形图；CMC 区域汇总固定最右，独立系列区分）
const bolUpdatesRateOption = computed(() => {
  const TARGET = 100
  const d = ameKpis.value['BOL Updates Rate']
  const byPlant = d?.by_plant || {}
  const cmc = d?.cmc_pct
  // 工厂按更新率降序排列；CMC 为区域汇总值固定置于最右
  const plants = Object.keys(byPlant).sort((a, b) => byPlant[b] - byPlant[a])
  const hasCmc = cmc != null
  const categories = [...plants, ...(hasCmc ? ['CMC'] : [])]
  if (!categories.length) return {}

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const isCmc = idx >= plants.length
        const v = isCmc ? cmc : byPlant[categories[idx]]
        return `<b>${categories[idx]}${isCmc ? '（区域汇总）' : ''}</b><br/>BOL 年度更新率: <b>${v}%</b><br/>官方 KPI（${d.month} 月）`
      }
    },
    legend: { data: ['工厂', 'CMC 区域汇总'], top: 0, textStyle: { color: AXIS.text, fontSize: 11 } },
    grid: { left: 45, right: 25, top: 34, bottom: 34, containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        fontSize: 11, color: AXIS.textDim, interval: 0,
        formatter: (value) => value === 'CMC' ? '{cmc|CMC}' : value,
        rich: { cmc: { color: PALETTE[5], fontWeight: 'bold', fontSize: 11 } }
      }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%', fontSize: 10, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line } }
    },
    series: [
      {
        name: '工厂',
        type: 'bar',
        stack: 'rate',
        data: [...plants.map(p => byPlant[p]), ...(hasCmc ? [null] : [])],
        barMaxWidth: 26,
        itemStyle: {
          color: (params) => targetBarGradient(params.value, TARGET),
          borderRadius: [3, 3, 0, 0],
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: PALETTE[1], type: 'dashed', width: 1.5 },
          label: { formatter: `Target ${TARGET}%`, fontSize: 10, color: PALETTE[1], position: 'insideEndTop' },
          data: [{ yAxis: TARGET }]
        },
        label: buildValueLabelConfig('bar', categories.length, {
          position: 'top',
          formatter: '{c}%'
        })
      },
      {
        name: 'CMC 区域汇总',
        type: 'bar',
        stack: 'rate',
        data: [...plants.map(() => null), ...(hasCmc ? [cmc] : [])],
        barMaxWidth: 26,
        itemStyle: {
          color: (params) => targetBarGradient(params.value, TARGET),
          borderRadius: [3, 3, 0, 0],
        },
        label: buildValueLabelConfig('bar', categories.length, {
          position: 'top',
          formatter: '{c}%',
          fontWeight: 'bold'
        })
      }
    ]
  }
})

// Tab 4 图 2: 各工厂达成率（vs 改善目标 5.4%）（垂直柱形图+横向目标线，CMC 固定最右）
const bolReductionRateOption = computed(() => {
  const d = ameKpis.value['BOL Reduction Rate']
  const byPlant = d?.by_plant || {}
  const cmc = d?.cmc_pct
  // 工厂按降低率降序排列；CMC 为区域汇总值固定置于最右
  const plants = Object.keys(byPlant).sort((a, b) => byPlant[b] - byPlant[a])
  const values = plants.map(p => byPlant[p])
  const categories = [...plants]
  if (cmc != null) {
    categories.push('CMC')
    values.push(cmc)
  }
  if (!categories.length) return {}

  const TARGET = 5.4
  // 动态颜色拆分为固定颜色双系列（达成=翠绿/未达成=红），stack 占位实现同位置显示
  const hitData = values.map(v => v >= TARGET ? v : null)
  const missData = values.map(v => v < TARGET ? v : null)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const v = values[idx]
        const isCmc = idx >= plants.length
        const status = v >= TARGET ? '达成' : '未达成'
        return `<b>${categories[idx]}${isCmc ? '（区域汇总）' : ''}</b><br/>BOL 降低率: <b>${v}%</b><br/>改善目标: ${TARGET}%<br/>状态: ${status}`
      }
    },
    legend: { data: ['达成', '未达成', `Target ${TARGET}%`], top: 0, textStyle: { color: AXIS.text, fontSize: 11 } },
    grid: { left: 45, right: 25, top: 34, bottom: 34, containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        fontSize: 11, color: AXIS.textDim, interval: 0,
        formatter: (value) => value === 'CMC' ? '{cmc|CMC}' : value,
        rich: { cmc: { color: PALETTE[5], fontWeight: 'bold', fontSize: 11 } }
      }
    },
    yAxis: {
      type: 'value',
      min: 0,
      axisLabel: { formatter: '{value}%', fontSize: 10, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line } }
    },
    series: [
      {
        name: '达成',
        type: 'bar',
        stack: 'rate',
        data: hitData,
        barMaxWidth: 26,
        itemStyle: { color: mintGradient(), borderRadius: [3, 3, 0, 0] },
        label: buildValueLabelConfig('bar', categories.length, {
          position: 'top',
          formatter: (params) => `${params.value}% ✓`
        })
      },
      {
        name: '未达成',
        type: 'bar',
        stack: 'rate',
        data: missData,
        barMaxWidth: 26,
        itemStyle: { color: dangerGradient(), borderRadius: [3, 3, 0, 0] },
        label: buildValueLabelConfig('bar', categories.length, {
          position: 'top',
          formatter: (params) => `${params.value}% ✗`
        })
      },
      {
        name: `Target ${TARGET}%`,
        type: 'line',
        data: categories.map(() => TARGET),
        symbol: 'none',
        silent: true,
        z: 10,
        tooltip: { show: false },
        lineStyle: { color: PALETTE[1], type: 'dashed', width: 2 },
        label: {
          show: true,
          position: 'end',
          formatter: `Target ${TARGET}%`,
          fontSize: 10,
          color: PALETTE[1],
        },
      }
    ]
  }
})

// Tab 4 图 4: LB 线平衡率（官方 KPI，CMC 区域汇总固定最右）
const lbRateOption = computed(() => {
  const TARGET = 80
  const d = ameKpis.value['LB']
  const byPlant = d?.by_plant || {}
  const cmc = d?.cmc_pct
  const plants = Object.keys(byPlant).sort((a, b) => byPlant[b] - byPlant[a])
  const hasCmc = cmc != null
  const categories = [...plants, ...(hasCmc ? ['CMC'] : [])]
  if (!categories.length) return {}

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const isCmc = idx >= plants.length
        const value = isCmc ? cmc : byPlant[categories[idx]]
        return `<b>${categories[idx]}${isCmc ? '（区域汇总）' : ''}</b><br/>LB 线平衡率: <b>${value}%</b><br/>官方 KPI（${d.month} 月）`
      }
    },
    legend: { data: ['工厂', 'CMC 区域汇总'], top: 0, textStyle: { color: AXIS.text, fontSize: 11 } },
    grid: { left: 45, right: 25, top: 34, bottom: 34, containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        fontSize: 11, color: AXIS.textDim, interval: 0,
        formatter: (value) => value === 'CMC' ? '{cmc|CMC}' : value,
        rich: { cmc: { color: PALETTE[5], fontWeight: 'bold', fontSize: 11 } }
      }
    },
    yAxis: {
      type: 'value', min: 0, max: 100,
      axisLabel: { formatter: '{value}%', fontSize: 10, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line } }
    },
    series: [
      {
        name: '工厂', type: 'bar', stack: 'rate',
        data: [...plants.map(plant => byPlant[plant]), ...(hasCmc ? [null] : [])],
        barMaxWidth: 26,
        itemStyle: {
          color: (params) => targetBarGradient(params.value, TARGET),
          borderRadius: [3, 3, 0, 0],
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: PALETTE[1], type: 'dashed', width: 1.5 },
          label: { formatter: `Target ${TARGET}%`, fontSize: 10, color: PALETTE[1], position: 'insideEndTop' },
          data: [{ yAxis: TARGET }]
        },
        label: buildValueLabelConfig('bar', categories.length, { position: 'top', formatter: '{c}%' })
      },
      {
        name: 'CMC 区域汇总', type: 'bar', stack: 'rate',
        data: [...plants.map(() => null), ...(hasCmc ? [cmc] : [])],
        barMaxWidth: 26,
        itemStyle: {
          color: (params) => targetBarGradient(params.value, TARGET),
          borderRadius: [3, 3, 0, 0],
        },
        label: buildValueLabelConfig('bar', categories.length, {
          position: 'top', formatter: '{c}%', fontWeight: 'bold'
        })
      }
    ]
  }
})

// Tab 4 图 3: ACT CT 抓取率（官方 KPI 口径，水平条形图；CMC 区域汇总固定最上，独立系列区分）
const ctCaptureBarOption = computed(() => {
  const TARGET = 100
  const d = ameKpis.value['Acutal CT Rate']
  const byPlant = d?.by_plant || {}
  const cmc = d?.cmc_pct
  // 工厂按抓取率升序排列（自下而上递增，便于阅读）；CMC 区域汇总固定置于最上
  const plants = Object.keys(byPlant).sort((a, b) => byPlant[a] - byPlant[b])
  const hasCmc = cmc != null
  const categories = [...plants, ...(hasCmc ? ['CMC'] : [])]
  if (!categories.length) return {}

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const isCmc = idx >= plants.length
        const v = isCmc ? cmc : byPlant[categories[idx]]
        return `<b>${categories[idx]}${isCmc ? '（区域汇总）' : ''}</b><br/>实测 CT 抓取率: <b>${v}%</b><br/>官方 KPI（${d.month} 月）`
      }
    },
    legend: { data: ['工厂', 'CMC 区域汇总'], top: 0, textStyle: { color: AXIS.text, fontSize: 11 } },
    // 上/下留足类目空间防止首尾条形与标签被裁剪；右侧预留数值标签宽度
    grid: { left: 45, right: 60, top: 34, bottom: 34, containLabel: true },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%', fontSize: 10, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line } }
    },
    yAxis: {
      type: 'category',
      data: categories,
      // 首尾类目内边距，保证 CJ/SH 标签与条形完整显示
      boundaryGap: true,
      axisLabel: {
        fontSize: 11, color: AXIS.text, margin: 10,
        formatter: (value) => value === 'CMC' ? '{cmc|CMC}' : value,
        rich: { cmc: { color: PALETTE[5], fontWeight: 'bold', fontSize: 11 } }
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: AXIS.line } }
    },
    series: [
      {
        name: '工厂',
        type: 'bar',
        stack: 'ct',
        data: [...plants.map(p => byPlant[p]), ...(hasCmc ? [null] : [])],
        barMaxWidth: 13,
        // 类目内留白，降低条形的视觉密度
        barCategoryGap: '45%',
        itemStyle: {
          color: (params) => targetBarGradient(params.value, TARGET),
          borderRadius: [0, 3, 3, 0],
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: PALETTE[1], type: 'dashed', width: 1.5 },
          label: { formatter: `Target ${TARGET}%`, fontSize: 10, color: PALETTE[1], position: 'insideEndTop' },
          data: [{ xAxis: TARGET }]
        },
        label: {
          show: true,
          position: 'right',
          // 100% 时标签右移仍留在容器内（grid.right 已预留）
          distance: 6,
          formatter: '{c}%',
          fontSize: 11,
          color: AXIS.text
        },
        // 背景轨道：显示 0-100% 全量刻度
        showBackground: true,
        backgroundStyle: { color: AXIS.line, opacity: 0.35 }
      },
      {
        name: 'CMC 区域汇总',
        type: 'bar',
        stack: 'ct',
        data: [...plants.map(() => null), ...(hasCmc ? [cmc] : [])],
        barMaxWidth: 13,
        barCategoryGap: '45%',
        itemStyle: {
          color: (params) => targetBarGradient(params.value, TARGET),
          borderRadius: [0, 3, 3, 0],
        },
        label: {
          show: true,
          position: 'right',
          distance: 6,
          formatter: '{c}%',
          fontSize: 11,
          fontWeight: 'bold',
          color: AXIS.text
        }
      }
    ]
  }
})

// ============ Tab 3.5 改善目标对比：三工时哑铃图 + 下钻明细 ============
const improveSummary = computed(() => improveData.value?.summary || [])
const improveYear = computed(() => improveData.value?.year || '')

// Region 顶卡复用图表实际显示的工厂点；改善空间仅比较 Budget/Achievable 均有效的共同工厂。
const improveTotals = computed(() => {
  const items = improveSummary.value
  const total = (field) => {
    const points = items.filter((item) => item[field] != null && Number.isFinite(Number(item[field])))
    return {
      value: points.reduce((sum, item) => sum + Number(item[field]), 0),
      plants: points.length,
    }
  }
  const budget = total('budget_hours')
  const target = total('target_hours')
  const achievable = total('achievable_hours')
  const comparable = items.filter((item) =>
    item.budget_hours != null && item.achievable_hours != null &&
    Number.isFinite(Number(item.budget_hours)) && Number.isFinite(Number(item.achievable_hours))
  )
  const saving = comparable.reduce(
    (sum, item) => sum + Number(item.budget_hours) - Number(item.achievable_hours), 0
  )
  const comparableBudget = comparable.reduce((sum, item) => sum + Number(item.budget_hours), 0)
  const savingPct = comparableBudget > 0 ? saving / comparableBudget * 100 : null
  return {
    budget: budget.value, budgetPlants: budget.plants,
    target: target.value, targetPlants: target.plants,
    achievable: achievable.value, achievablePlants: achievable.plants,
    saving, savingPct, comparablePlants: comparable.length,
  }
})

// 三指标定义（系列名/汇总字段/计数/颜色统一来源；顺序即连线顺序）
// 指标视觉规格（用户指定）：独立形状 + 语义色
//   Budget      → 黑色横线（rect + [长 48, 粗 4] 数组尺寸渲染为水平粗线）
//   改善目标    → 绿色圆点（直径 10）
//   Achievable  → 浅蓝三角（宽 9）
//   约束：横线长度 48 > 5 × 三角宽 9（=45）
const IMPROVE_SYMBOL = {
  budgetLine: [48, 4],   // 黑色横线 [长, 粗]（px）—— symbolSize 数组避免被等比拉伸成方块
  circleSize: 10,        // 绿点直径（px）
  triangleSize: 9,       // 三角形宽（px）
}

const IMPROVE_METRICS = [
  {
    key: 'budget', label: 'Budget 工时', field: 'budget_hours', count: 'budget_count',
    color: AXIS.text, symbol: 'rect', symbolSize: IMPROVE_SYMBOL.budgetLine,
    // 横线不加白描边（细长矩形描边会喧宾夺主），保持纯黑实线
    itemStyle: { color: AXIS.text, borderWidth: 0 },
  },
  {
    key: 'target', label: '改善目标工时', field: 'target_hours', count: 'target_count',
    color: IMPROVE_HOURS.achievable, symbol: 'circle', symbolSize: IMPROVE_SYMBOL.circleSize,
    itemStyle: { color: IMPROVE_HOURS.achievable, borderColor: '#ffffff', borderWidth: 1.5 },
  },
  {
    key: 'achievable', label: 'Achievable 工时', field: 'achievable_hours', count: 'achievable_count',
    // 浅天蓝 = PALETTE[7]（#38bdf8）；此前误用 PALETTE[2]（翠绿 #10b981）导致三角显示绿色
    color: PALETTE[7], symbol: 'triangle', symbolSize: IMPROVE_SYMBOL.triangleSize,
    symbolRotate: 180,
    itemStyle: { color: PALETTE[7], borderColor: '#ffffff', borderWidth: 1.5 },
  },
]

const fmtHour = (n) => n == null ? '-' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 1 })

const improveOption = computed(() => {
  const items = improveSummary.value
  if (!items.length) return {}
  // 工厂按 Budget 工时总量降序排列（无 Budget 的按 Target/Achievable 兜底），大厂在前更利于横向对比
  const sorted = items.slice().sort((a, b) =>
    (b.budget_hours ?? b.target_hours ?? b.achievable_hours ?? 0) -
    (a.budget_hours ?? a.target_hours ?? a.achievable_hours ?? 0)
  )
  const labels = sorted.map(s => s.plant)

  // 相邻指标连线段（Budget→改善目标→Achievable 顺序，中性灰蓝；任一端无数据跳过）
  const segments = []
  sorted.forEach((s, idx) => {
    for (let i = 0; i < IMPROVE_METRICS.length - 1; i++) {
      const v1 = s[IMPROVE_METRICS[i].field]
      const v2 = s[IMPROVE_METRICS[i + 1].field]
      if (v1 == null || v2 == null) continue
      segments.push({
        value: [idx, v1, v2],
        fromLabel: IMPROVE_METRICS[i].label,
        toLabel: IMPROVE_METRICS[i + 1].label,
        plant: s.plant,
      })
    }
  })

  // 每指标独立散点系列（独立形状/尺寸/颜色定义于 IMPROVE_METRICS，携带下钻 payload）
  const scatterSeries = IMPROVE_METRICS.map(m => ({
    name: m.label,
    type: 'scatter',
    z: 5,
    symbol: m.symbol,
    symbolSize: m.symbolSize,
    symbolRotate: m.symbolRotate,
    cursor: 'pointer',
    itemStyle: m.itemStyle,
    emphasis: { scale: 1.4 },
    data: sorted
      .map((s, idx) => ({
        value: [idx, s[m.field]],
        plant: s.plant, metric: m.key, metricLabel: m.label, count: s[m.count],
      }))
      .filter(d => d.value[1] != null),
  }))

  return {
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (p) => {
        const d = p.data
        if (!d?.plant) return ''
        // 悬停任一散点/连线，均显示该工厂三种工时的完整数值
        const s = improveSummary.value.find(x => x.plant === d.plant)
        if (!s) return ''
        const hovered = d.metric || null
        const rows = IMPROVE_METRICS.map(m => {
          const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${m.color};margin-right:6px;"></span>`
          const v = s[m.field]
          const val = v == null
            ? `<span style="color:${AXIS.textDim}">无数据</span>`
            : `<b>${fmtHour(v)} h</b> <span style="color:${AXIS.textDim}">(${s[m.count]} 项)</span>`
          const mark = hovered === m.key ? ' ◀' : ''
          return `${dot}${m.label}: ${val}${mark}`
        })
        const budget = s.budget_hours
        const gaps = [
          ['Budget − 改善目标', s.target_hours],
          ['Budget − Achievable', s.achievable_hours],
        ].map(([label, value]) => {
          if (budget == null || value == null) return `${label}: 无数据`
          const gap = budget - value
          const pct = budget > 0 ? ` (${(gap / budget * 100).toFixed(1)}%)` : ''
          return `${label}: <b>${fmtHour(gap)} h</b>${pct}`
        })
        return `<b>${d.plant}</b> · 三工时年化汇总<br/>${rows.join('<br/>')}` +
          `<br/><b>工时差</b><br/>${gaps.join('<br/>')}` +
          `<br/><span style="color:${AXIS.textDim}">点击散点查看该指标项目明细</span>`
      }
    },
    legend: {
      data: IMPROVE_METRICS.map(m => m.label),
      top: 0,
      textStyle: { color: AXIS.text, fontSize: CHART_SPEC.labelAxis },
    },
    toolbox: {
      show: true,
      right: 8,
      top: 0,
      feature: {
        restore: { title: '恢复默认缩放' },
      },
    },
    dataZoom: [{
      type: 'inside',
      yAxisIndex: 0,
      filterMode: 'none',
      zoomOnMouseWheel: true,
      moveOnMouseMove: true,
      moveOnMouseWheel: false,
    }],
    grid: { left: 70, right: 30, top: 50, bottom: 40, containLabel: true },
    xAxis: {
      type: 'category',
      name: '工厂',
      data: labels,
      axisLabel: { fontSize: CHART_SPEC.labelAxis, color: AXIS.text },
      axisLine: { lineStyle: { color: AXIS.line } },
      axisTick: { lineStyle: { color: AXIS.line } },
    },
    yAxis: {
      type: 'value',
      name: '工时数（小时）',
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: {
        fontSize: CHART_SPEC.labelAxis, color: AXIS.textDim,
        formatter: (v) => v >= 10000 ? (v / 10000) + '万' : v,
      },
      splitLine: { lineStyle: { color: AXIS.line } },
    },
    series: [
      {
        name: '对比连线',
        type: 'custom',
        z: 3,
        silent: false,
        tooltip: { show: true },
        renderItem: (params, api) => {
          const x = api.value(0)
          const p1 = api.coord([x, api.value(1)])
          const p2 = api.coord([x, api.value(2)])
          return {
            type: 'line',
            shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] },
            style: { stroke: IMPROVE_HOURS.link, lineWidth: 2, lineCap: 'round', opacity: 0.7 },
          }
        },
        data: segments,
      },
      ...scatterSeries,
    ],
  }
})

// ---- 下钻明细（仅点击类型；Tab 内切换 + 面包屑返回） ----
const improveMetricLabel = computed(() =>
  IMPROVE_METRICS.find(m => m.key === improveDrill.value?.metric)?.label || ''
)

const improveDrillRows = computed(() => {
  const d = improveDrill.value
  if (!d) return []
  const list = improveData.value?.details?.[d.metric] || []
  return list
    .filter(r => r.plant === d.plant)
    .slice()
    .sort((a, b) => (b.hours ?? -1) - (a.hours ?? -1))
})

// 计入汇总的有效行（有 Volume → 工时可算），与一级图 tooltip 的"明细项目数"同口径
const improveValidCount = computed(() =>
  improveDrillRows.value.filter(r => r.hours != null).length
)

const improveDrillColumns = computed(() => {
  const m = improveDrill.value?.metric
  if (!m) return []
  const volHours = [
    { prop: 'volume', label: 'Volume (台)', width: 110, formatter: (r) => r.volume == null ? '' : r.volume.toLocaleString('zh-CN') },
    { prop: 'hours', label: '工时数 (h)', width: 130, formatter: (r) => fmtHour(r.hours) },
  ]
  const base = [
    { prop: 'project_code', label: '项目代码', width: 110, align: 'left' },
    { prop: 'project_name', label: '项目名称', minWidth: 200, align: 'left', showOverflowTooltip: true },
    { prop: 'process_type', label: '工艺', width: 80, align: 'left' },
  ]
  if (m === 'budget') {
    return [...base, { prop: 'bol', label: 'Budget BOL (min)', width: 140, formatter: (r) => r.bol ?? '' }, ...volHours]
  }
  if (m === 'target') {
    return [
      ...base,
      { prop: 'bol_budget', label: 'Budget BOL (min)', width: 140, formatter: (r) => r.bol_budget ?? '' },
      { prop: 'target_pct', label: '改善比例', width: 150, showOverflowTooltip: true, formatter: (r) => r.target_pct == null ? '未设置（按0%改善）' : (r.target_pct * 100).toFixed(1) + '%' },
      ...volHours,
    ]
  }
  return [
    ...base,
    { prop: 'bol', label: 'Achievable BOL (min)', width: 160, formatter: (r) => r.bol ?? '' },
    { prop: 'source', label: '数据来源', width: 100, formatter: (r) => r.source === 'process' ? '实测CT·HC' : '预算回退' },
    ...volHours,
  ]
})

function onImproveChartClick(params) {
  if (params.seriesType !== 'scatter' && params.seriesType !== 'bar') return
  const d = params.data
  if (!d?.plant || !d?.metric) return
  improveDrill.value = { plant: d.plant, metric: d.metric }
}

function backToImproveChart() {
  improveDrill.value = null
}

// ---- 工厂对比箱线图钻取弹窗（查看统计背后的项目明细） ----
const plantCompareDetails = computed(() => plantCompare.value.details || [])
const boxDialogVisible = ref(false)
const boxDialogPlants = ref([]) // 弹窗内工厂筛选（默认=点击的工厂）

function onPlantCompareClick(params) {
  // 点击箱线图或均值菱形均可钻取
  if (params.seriesType !== 'boxplot' && params.seriesType !== 'scatter') return
  const s = plantCompareStats.value[params.dataIndex]
  if (!s?.plant) return
  boxDialogPlants.value = [s.plant]
  boxDialogVisible.value = true
}

// 弹窗内表格数据：按弹窗工厂筛选器过滤
const boxDialogRows = computed(() => {
  const sel = boxDialogPlants.value
  const rows = sel.length
    ? plantCompareDetails.value.filter(r => sel.includes(r.plant))
    : plantCompareDetails.value
  return rows
})

// 弹窗内当前筛选的统计摘要（直接复用上层箱线图统计值）
const boxDialogSummary = computed(() =>
  plantCompareStats.value.filter(s => boxDialogPlants.value.includes(s.plant))
)

async function fetchImprove() {
  improveLoading.value = true
  try {
    improveData.value = await analyticsApi.improveTargetCompare()
  } catch (e) {
    // 错误已由拦截器统一提示
  } finally {
    improveLoading.value = false
  }
}

// 懒加载：首次切入改善目标对比 Tab 时请求
watch(activeTab, (tab) => {
  if (tab === 't35' && !improveLoaded.value) {
    improveLoaded.value = true
    fetchImprove()
  }
})

// ============ 数据加载 ============
// 首次加载后同步后端默认年份时，抑制 watch 触发的重复请求
let suppressYearWatch = false
async function loadDashboard() {
  loading.value = true
  try {
    const params = {}
    if (selectedYear.value) params.year = selectedYear.value
    if (selectedPlants.value.length) params.plants = selectedPlants.value.join(',')
    if (selectedProcessTypes.value.length) params.process_types = selectedProcessTypes.value.join(',')
    if (selectedRoofTypes.value.length) params.roof_types = selectedRoofTypes.value.join(',')
    if (lifecyclePlants.value.length) params.lifecycle_plants = lifecyclePlants.value.join(',')
    const res = await analyticsApi.dashboard(params)
    dashboardData.value = res
    // Tab 2 同比哑铃图：首屏数据直接复用 dashboard 返回，筛选器默认年份同步后端
    if (res.achievable_yoy) {
      yoyData.value = res.achievable_yoy
      if (!yoyYears.value.length) {
        yoyYears.value = res.achievable_yoy.selected_years || []
      }
    }
    // 首次加载：同步后端使用的对比年份（flush:'sync' watch 需在赋值前设置抑制标记）
    if (selectedYear.value === null && res.plant_compare?.year) {
      suppressYearWatch = true
      selectedYear.value = res.plant_compare.year
      suppressYearWatch = false
    }
  } catch (e) {
    // 错误已由拦截器统一提示
  } finally {
    loading.value = false
  }
}

// Tab 3 筛选条件变化时重新加载（flush:'sync' 保证抑制标记时序正确）
watch([selectedYear, selectedPlants, selectedProcessTypes, selectedRoofTypes], () => {
  if (suppressYearWatch) return
  if (activeTab.value === 't3') {
    loadDashboard()
  }
}, { flush: 'sync' })

function resetFilters() {
  selectedPlants.value = []
  selectedProcessTypes.value = []
  selectedRoofTypes.value = []
}

// ============ Tab 2 同比哑铃图：筛选器查询 ============
async function fetchYoy() {
  if (yoyYears.value.length < 2) {
    ElMessage.warning('请至少选择两个对比年份')
    return
  }
  yoyLoading.value = true
  try {
    const params = {
      years: yoyYears.value.join(','),
      top_n: yoyTopN.value,
    }
    if (yoyPlants.value.length) params.plants = yoyPlants.value.join(',')
    yoyData.value = await analyticsApi.achievableYoy(params)
  } catch (e) {
    // 错误已由拦截器统一提示
  } finally {
    yoyLoading.value = false
  }
}

function resetYoyFilters() {
  yoyPlants.value = []
  yoyTopN.value = 10
  // 年份重置为可选年份中最新的两年（默认本年 vs 上年）
  const ys = yoyYearOptions.value
  yoyYears.value = ys.length >= 2 ? [ys[ys.length - 2], ys[ys.length - 1]] : [...ys]
  fetchYoy()
}

onMounted(() => {
  loadDashboard()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="综合看板"
      icon="Odometer"
      subtitle="BOL审批记录 · 预算BOL · 实测CT 综合分析"
      :breadcrumbs="[{ label: '数据管理' }, { label: '综合看板' }]"
    />
    <div class="page-container">

      <!-- 4 Tab 导航 -->
      <el-tabs v-model="activeTab" class="dashboard-tabs">

        <!-- ========== Tab 1: BOL 全链路 ========== -->
        <el-tab-pane label="BOL 全链路" name="t1">
          <!-- 筛选条：工厂多选（空=全部） -->
          <el-card shadow="never" class="filter-card">
            <div class="filter-bar filter-bar--compact">
              <span class="filter-label">工厂:</span>
              <el-select
                v-model="lifecyclePlants"
                multiple
                collapse-tags
                collapse-tags-tooltip
                clearable
                placeholder="全部工厂（空=所有）"
                style="width: 260px"
                size="small"
                @change="loadDashboard"
              >
                <el-option
                  v-for="p in lifecyclePlantOptions"
                  :key="p"
                  :label="p"
                  :value="p"
                />
              </el-select>
              <span class="filter-hint">
                选中 {{ lifecyclePlants.length || lifecyclePlantOptions.length }} 个工厂 ·
                展示 {{ bolLifecycle.length }} 个项目 ·
                排序：FA优先 + Volume 降序 Top20
              </span>
            </div>
          </el-card>
          <el-row :gutter="16" class="chart-row">
            <el-col :span="24">
              <ChartCard
                title="BOL 全链路对比 Top 20"
                subtitle="Budget → Achievable → Target → 实测BOL（FA优先 + 按当年Volume降序）"
                :option="bolLifecycleOption"
                :height="420"
              />
            </el-col>
          </el-row>
          <!-- 全链路图表明细数据（随工厂筛选联动，可按节省率升/降序分析预算偏差） -->
          <el-card shadow="never" class="recent-card">
            <template #header>
              <div class="card-header">
                <span>BOL 全链路对比明细</span>
                <el-tag size="small">
                  {{ lifecyclePlants.length ? '工厂: ' + lifecyclePlants.join('/') : '全部工厂' }} ·
                  共 {{ bolLifecycle.length }} 项 · 点击列头可排序
                </el-tag>
              </div>
            </template>
            <el-table :data="bolLifecycle" stripe size="small" max-height="420"
              :default-sort="{ prop: 'saving_pct', order: 'descending' }"
            >
              <el-table-column prop="project_code" label="项目代码" min-width="100" sortable />
              <el-table-column prop="project_name" label="项目名称" min-width="180" show-overflow-tooltip />
              <el-table-column prop="plant" label="工厂" min-width="65" align="center" sortable />
              <el-table-column prop="process_type" label="工艺" min-width="70" align="center" sortable />
              <el-table-column prop="budget" label="Budget" min-width="90" align="right" header-align="center" sortable>
                <template #default="{ row }"><span class="num-cell">{{ row.budget }}</span></template>
              </el-table-column>
              <el-table-column prop="achievable" label="Achievable" min-width="100" align="right" header-align="center" sortable>
                <template #default="{ row }"><span class="num-cell">{{ row.achievable }}</span></template>
              </el-table-column>
              <el-table-column prop="target" label="Target" min-width="85" align="right" header-align="center" sortable>
                <template #default="{ row }"><span class="num-cell">{{ row.target ?? '—' }}</span></template>
              </el-table-column>
              <el-table-column prop="actual" label="实测BOL" min-width="90" align="right" header-align="center" sortable>
                <template #default="{ row }">
                  <span class="num-cell" :style="row.actual_ach_gap_pct !== null && Math.abs(row.actual_ach_gap_pct) > 10 ? 'color: var(--color-danger);' : ''">
                    {{ row.actual ?? '—' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="gap" label="差距(B-A)" min-width="95" align="right" header-align="center" sortable>
                <template #default="{ row }"><span class="num-cell">{{ row.gap }}</span></template>
              </el-table-column>
              <el-table-column prop="saving_pct" label="节省率%" min-width="95" align="right" header-align="center" sortable
                :sort-method="(a, b) => (a.saving_pct ?? -9999) - (b.saving_pct ?? -9999)"
              >
                <template #default="{ row }">
                  <span v-if="row.saving_pct === null" class="num-cell">—</span>
                  <span v-else-if="row.saving_pct >= 0" class="num-cell" style="color: var(--color-success); font-weight: 600;">
                    +{{ row.saving_pct }}%
                  </span>
                  <span v-else class="num-cell" style="color: var(--color-danger); font-weight: 600;">
                    {{ row.saving_pct }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="volume" label="Volume" min-width="100" align="right" header-align="center" sortable>
                <template #default="{ row }"><span class="num-cell">{{ (row.volume ?? 0).toLocaleString() }}</span></template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!bolLifecycle.length" description="暂无全链路数据" :image-size="60" />
          </el-card>
        </el-tab-pane>

        <!-- ========== Tab 2: 同/环比趋势 ========== -->
        <el-tab-pane label="同/环比趋势" name="t2">
          <el-card shadow="never" class="filter-card">
            <div class="filter-bar filter-bar--compact" v-loading="yoyLoading">
              <span class="filter-label">对比年份:</span>
              <el-select
                v-model="yoyYears"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="至少选两个年份"
                style="width: 220px"
                size="small"
              >
                <el-option v-for="y in yoyYearOptions" :key="y" :label="String(y)" :value="y" />
              </el-select>
              <span class="filter-label">工厂:</span>
              <el-select
                v-model="yoyPlants"
                multiple
                collapse-tags
                collapse-tags-tooltip
                clearable
                placeholder="全部工厂"
                style="width: 200px"
                size="small"
              >
                <el-option v-for="p in yoyPlantOptions" :key="p" :label="p" :value="p" />
              </el-select>
              <span class="filter-label">数量:</span>
              <el-select v-model="yoyTopN" style="width: 110px" size="small">
                <el-option label="Top 10" :value="10" />
                <el-option label="Top 15" :value="15" />
                <el-option label="Top 20" :value="20" />
                <el-option label="Top 30" :value="30" />
                <el-option label="全部" :value="0" />
              </el-select>
              <el-button type="primary" size="small" @click="fetchYoy">查询</el-button>
              <el-button size="small" @click="resetYoyFilters">重置</el-button>
            </div>
          </el-card>
          <el-row :gutter="16" class="chart-row">
            <el-col :span="24">
              <ChartCard
                :title="`Achievable BOL 同比变化 ${yoyTopN === 0 ? '全量' : 'Top ' + yoyTopN}`"
                :subtitle="`${yoySelectedYears.join(' ↔ ')} · 散点=各年份 Achievable 实际值 · 连线: 绿=同比下降(改善) / 红=同比上升(恶化) · ⚠ = 疑似数据异常（接近 2 倍关系）`"
                :option="achievableYoyOption"
                :height="420"
              />
            </el-col>
          </el-row>
          <!-- Achievable BOL 同比下降项目清单（全量） -->
          <el-card shadow="never" class="recent-card">
            <template #header>
              <div class="card-header">
                <span>Achievable BOL 同比下降项目清单（全量）</span>
                <el-tag size="small" type="success">改善 · 按 BOL 降幅降序 · 共 {{ improvementOpportunities.length }} 项</el-tag>
              </div>
            </template>
            <el-table :data="improvementOpportunities" stripe size="small" max-height="320">
              <el-table-column prop="project_code" label="项目代码" width="110" />
              <el-table-column prop="project_name" label="项目名称" min-width="180" show-overflow-tooltip />
              <el-table-column prop="plant" label="工厂" width="70" />
              <el-table-column prop="process_type" label="工艺" width="80" />
              <el-table-column prop="volume" label="Volume" width="90" align="right" header-align="center" sortable>
                <template #default="{ row }"><span class="num-cell">{{ (row.volume ?? 0).toLocaleString() }}</span></template>
              </el-table-column>
              <el-table-column label="上年 BOL" width="100" align="right" header-align="center">
                <template #default="{ row }"><span class="num-cell">{{ row.from_bol }}</span></template>
              </el-table-column>
              <el-table-column label="本年 BOL" width="100" align="right" header-align="center">
                <template #default="{ row }"><span class="num-cell">{{ row.to_bol }}</span></template>
              </el-table-column>
              <el-table-column prop="bol_reduction" label="BOL 降幅" width="100" align="right" header-align="center" sortable>
                <template #default="{ row }">
                  <span class="num-cell" style="color: var(--color-success); font-weight: 600;">↓{{ row.bol_reduction }}</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!improvementOpportunities.length" description="暂无 BOL 同比下降项目" :image-size="60" />
          </el-card>
          <!-- Achievable BOL 同比上升项目清单（全量） -->
          <el-card shadow="never" class="recent-card">
            <template #header>
              <div class="card-header">
                <span>Achievable BOL 同比上升项目清单（全量）</span>
                <el-tag size="small" type="danger">恶化 · 按 BOL 升幅降序 · 共 {{ improvementIncreases.length }} 项</el-tag>
              </div>
            </template>
            <el-table :data="improvementIncreases" stripe size="small" max-height="320">
              <el-table-column prop="project_code" label="项目代码" width="110" />
              <el-table-column prop="project_name" label="项目名称" min-width="180" show-overflow-tooltip />
              <el-table-column prop="plant" label="工厂" width="70" />
              <el-table-column prop="process_type" label="工艺" width="80" />
              <el-table-column prop="volume" label="Volume" width="90" align="right" header-align="center" sortable>
                <template #default="{ row }"><span class="num-cell">{{ (row.volume ?? 0).toLocaleString() }}</span></template>
              </el-table-column>
              <el-table-column label="上年 BOL" width="100" align="right" header-align="center">
                <template #default="{ row }"><span class="num-cell">{{ row.from_bol }}</span></template>
              </el-table-column>
              <el-table-column label="本年 BOL" width="100" align="right" header-align="center">
                <template #default="{ row }"><span class="num-cell">{{ row.to_bol }}</span></template>
              </el-table-column>
              <el-table-column prop="bol_reduction" label="BOL 升幅" width="100" align="right" header-align="center"
                sortable :sort-method="(a, b) => a.bol_reduction - b.bol_reduction"
              >
                <template #default="{ row }">
                  <span class="num-cell" style="color: var(--color-danger); font-weight: 600;">↑{{ Math.abs(row.bol_reduction) }}</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!improvementIncreases.length" description="暂无 BOL 同比上升项目" :image-size="60" />
          </el-card>
        </el-tab-pane>

        <!-- ========== Tab 3: 工厂对比 ========== -->
        <el-tab-pane label="工厂对比" name="t3">
          <el-card shadow="never" class="filter-card">
            <div class="filter-bar filter-bar--compact">
              <span class="filter-label">年份:</span>
              <el-select
                v-model="selectedYear"
                placeholder="对比年份"
                style="width: 110px"
                size="small"
              >
                <el-option v-for="y in yearOptions" :key="y" :label="String(y)" :value="y" />
              </el-select>
              <span class="filter-label">工厂:</span>
              <el-select
                v-model="selectedPlants"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择工厂"
                style="width: 240px"
                size="small"
              >
                <el-option v-for="p in plantOptions" :key="p" :label="p" :value="p" />
              </el-select>
              <span class="filter-label">工艺:</span>
              <el-select
                v-model="selectedProcessTypes"
                multiple
                collapse-tags
                placeholder="选择工艺"
                style="width: 200px"
                size="small"
              >
                <el-option v-for="p in processTypeOptions" :key="p" :label="p" :value="p" />
              </el-select>
              <span class="filter-label">产品类型:</span>
              <el-select
                v-model="selectedRoofTypes"
                multiple
                collapse-tags
                placeholder="选择产品类型"
                style="width: 180px"
                size="small"
              >
                <el-option v-for="p in roofTypeOptions" :key="p" :label="p" :value="p" />
              </el-select>
              <el-button size="small" plain @click="resetFilters">重置</el-button>
            </div>
          </el-card>
          <el-row :gutter="16" class="chart-row">
            <el-col :span="24">
              <ChartCard
                :title="plantCompareTitle.title"
                :subtitle="plantCompareTitle.subtitle"
                :option="plantCompareOption"
                :height="480"
                @chart-click="onPlantCompareClick"
              />
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- ========== Tab 3.5: 改善目标对比 ========== -->
        <el-tab-pane label="改善目标对比" name="t35">
          <!-- 一级视图：汇总统计卡 + 三工时哑铃图（点击散点下钻） -->
          <template v-if="!improveDrill">
            <div v-loading="improveLoading">
              <!-- 汇总统计卡：全工厂三工时总量对比 + 改善空间 -->
              <el-row :gutter="16" class="stat-row" v-if="improveSummary.length">
                <el-col :xs="12" :sm="6">
                  <el-card class="stat-card" shadow="never" data-bar-color="warning">
                    <div class="stat-card-inner">
                      <div class="stat-bar"></div>
                      <div class="stat-label">Region Σ Budget 工时</div>
                      <div class="stat-value" :style="{ color: IMPROVE_METRICS[0].color }">{{ fmtHour(improveTotals.budget) }} h</div>
                      <div class="stat-sub">图表有效点求和 · {{ improveTotals.budgetPlants }} 家工厂</div>
                    </div>
                  </el-card>
                </el-col>
                <el-col :xs="12" :sm="6">
                  <el-card class="stat-card" shadow="never" data-bar-color="violet">
                    <div class="stat-card-inner">
                      <div class="stat-bar"></div>
                      <div class="stat-label">Region Σ 改善目标工时</div>
                      <div class="stat-value" :style="{ color: IMPROVE_METRICS[1].color }">{{ fmtHour(improveTotals.target) }} h</div>
                      <div class="stat-sub">图表有效点求和 · {{ improveTotals.targetPlants }} 家工厂</div>
                    </div>
                  </el-card>
                </el-col>
                <el-col :xs="12" :sm="6">
                  <el-card class="stat-card" shadow="never" data-bar-color="success">
                    <div class="stat-card-inner">
                      <div class="stat-bar"></div>
                      <div class="stat-label">Region Σ Achievable 工时</div>
                      <div class="stat-value" :style="{ color: IMPROVE_METRICS[2].color }">{{ fmtHour(improveTotals.achievable) }} h</div>
                      <div class="stat-sub">图表有效点求和 · {{ improveTotals.achievablePlants }} 家工厂</div>
                    </div>
                  </el-card>
                </el-col>
                <el-col :xs="12" :sm="6">
                  <el-card class="stat-card" shadow="never" data-bar-color="accent">
                    <div class="stat-card-inner">
                      <div class="stat-bar"></div>
                      <div class="stat-label">改善空间（Budget − Achievable）</div>
                      <div class="stat-value">{{ fmtHour(improveTotals.saving) }} h</div>
                      <div class="stat-sub">
                        {{ improveTotals.comparablePlants }} 家共同工厂配对 · 相对配对 Budget {{ improveTotals.savingPct == null ? '-' : improveTotals.savingPct.toFixed(1) + '%' }}
                      </div>
                    </div>
                  </el-card>
                </el-col>
              </el-row>
              <ChartCard
                title="改善目标对比 · 各工厂三工时汇总"
                :subtitle="`${improveYear ? improveYear + ' 财年 · ' : ''}HRDB improveTarget 同源口径 · 工时 = BOL × Volume / 60（Volume 来自 improveTarget_volume）· BOL≤0 视为无数据，不绘点、不计样本 · target_bol 未设置按 0% 改善（目标工时=Budget）· Achievable BOL = Σ(CT×HC)×(1+1/15)/0.85/60（仅计 CT、HC 均非空的工段）；无有效工段或结果为 0 时回退 bol_budget · 顶卡为图表有效工厂点求和；改善空间按 Budget/Achievable 共同工厂配对计算 · 点击散点查看项目明细`"
                :option="improveOption"
                :height="560"
                class="improve-chart"
                @chart-click="onImproveChartClick"
              />
            </div>
          </template>
          <!-- 二级视图：点击工厂 × 指标的项目级明细表 -->
          <el-card v-else shadow="never">
            <div class="drill-nav">
              <el-button size="small" @click="backToImproveChart">← 返回上层图表</el-button>
              <div class="drill-breadcrumb">
                <el-breadcrumb separator="/">
                  <el-breadcrumb-item>
                    <a @click.prevent="backToImproveChart">全部工厂汇总</a>
                  </el-breadcrumb-item>
                  <el-breadcrumb-item>
                    <span class="drill-current">{{ improveDrill.plant }} · {{ improveMetricLabel }}（共 {{ improveDrillRows.length }} 项 · 计入汇总 {{ improveValidCount }} 项）</span>
                  </el-breadcrumb-item>
                </el-breadcrumb>
              </div>
            </div>
            <el-table :data="improveDrillRows" size="small" stripe border max-height="520">
              <el-table-column
                v-for="c in improveDrillColumns"
                :key="c.prop"
                :prop="c.prop"
                :label="c.label"
                :width="c.width"
                :min-width="c.minWidth"
                :formatter="c.formatter"
                :show-overflow-tooltip="c.showOverflowTooltip"
                :align="c.align || 'right'"
              />
            </el-table>
          </el-card>
          <!-- 近 3 年 Budget vs Achievable 总量（三级钻取：年度→工厂→工艺） -->
          <el-row :gutter="16" class="chart-row">
            <el-col :span="24">
              <!-- 返回上层按钮 + 钻取面包屑 -->
              <div class="drill-nav" v-if="yearlyDrill.level !== 'year'">
                <el-button size="small" @click="backYearlyOneLevel">← 返回上层</el-button>
                <div class="drill-breadcrumb">
                  <el-breadcrumb separator="/">
                    <el-breadcrumb-item>
                      <a @click.prevent="setYearlyLevel('year')">年度总量</a>
                    </el-breadcrumb-item>
                    <el-breadcrumb-item v-if="yearlyDrill.level === 'process'">
                      <a @click.prevent="setYearlyLevel('plant')">{{ yearlyDrill.year }} 各工厂</a>
                    </el-breadcrumb-item>
                    <el-breadcrumb-item>
                      <span class="drill-current">
                        {{ yearlyDrill.level === 'plant'
                          ? yearlyDrill.year + ' 各工厂'
                          : yearlyDrill.plant + ' 工厂' }}
                      </span>
                    </el-breadcrumb-item>
                  </el-breadcrumb>
                </div>
              </div>
              <ChartCard
                :title="yearlyDrillTitle.title"
                :subtitle="yearlyDrillTitle.subtitle"
                :option="yearlyCompareOption"
                :height="280"
                @chart-click="onYearlyChartClick"
              />
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- ========== Tab 4: KPI 总览 ========== -->
        <el-tab-pane label="KPI 总览" name="t4">
          <el-row :gutter="16" class="stat-row">
            <el-col :xs="12" :sm="6" :md="6">
              <el-card class="stat-card" shadow="never" data-bar-color="info">
                <div class="stat-card-inner">
                  <div class="stat-bar"></div>
                  <div class="stat-label">ACT CT 抓取率</div>
                  <div class="stat-value">{{ kpiCards.ct_capture_rate ?? 0 }}%</div>
                  <div class="stat-sub">官方 KPI · {{ ameKpis['Acutal CT Rate']?.month ?? '-' }} 月 · CMC 区域汇总</div>
                </div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <el-card class="stat-card" shadow="never" data-bar-color="success">
                <div class="stat-card-inner">
                  <div class="stat-bar"></div>
                  <div class="stat-label">BOL 降低率</div>
                  <div class="stat-value">{{ kpiCards.bol_reduction_rate ?? 0 }}%</div>
                  <div class="stat-sub">官方 KPI · {{ ameKpis['BOL Reduction Rate']?.month ?? '-' }} 月 · CMC 区域汇总</div>
                </div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <el-card class="stat-card" shadow="never" data-bar-color="accent">
                <div class="stat-card-inner">
                  <div class="stat-bar"></div>
                  <div class="stat-label">BOL 更新率</div>
                  <div class="stat-value">{{ kpiCards.bol_updates_rate ?? 0 }}%</div>
                  <div class="stat-sub">官方 KPI · {{ ameKpis['BOL Updates Rate']?.month ?? '-' }} 月 · CMC 区域汇总</div>
                </div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <el-card class="stat-card" shadow="never" data-bar-color="info">
                <div class="stat-card-inner">
                  <div class="stat-bar"></div>
                  <div class="stat-label">LB 线平衡率</div>
                  <div class="stat-value">{{ kpiCards.lb_rate ?? 0 }}%</div>
                  <div class="stat-sub">官方 KPI · {{ ameKpis['LB']?.month ?? '-' }} 月 · CMC 区域汇总</div>
                </div>
              </el-card>
            </el-col>
          </el-row>

          <el-row :gutter="16" class="chart-row">
            <el-col :xs="24" :md="12">
              <ChartCard
                title="BOL 年度更新率"
                subtitle="官方 KPI · 按工厂排序 · CMC 区域汇总置尾 · 当前月份"
                :option="bolUpdatesRateOption"
                :height="280"
              />
            </el-col>
            <el-col :xs="24" :md="12">
              <ChartCard
                title="各工厂达成率（vs 改善目标 5.4%）"
                subtitle="BOL Reduction Rate · 琥珀虚线为目标线 · ≥5.4% 为达成 · CMC 置尾"
                :option="bolReductionRateOption"
                :height="280"
              />
            </el-col>
            <el-col :xs="24" :md="12">
              <ChartCard
                title="ACT CT 抓取率（按工厂）"
                subtitle="官方 KPI · CMC 区域汇总置顶 · 最新月份"
                :option="ctCaptureBarOption"
                :height="280"
              />
            </el-col>
            <el-col :xs="24" :md="12">
              <ChartCard
                title="LB 线平衡率（按工厂）"
                subtitle="官方 KPI · 按工厂排序 · CMC 区域汇总置尾 · 最新月份"
                :option="lbRateOption"
                :height="280"
              />
            </el-col>
          </el-row>
        </el-tab-pane>

      </el-tabs>

      <!-- 工厂对比箱线图钻取弹窗：查看统计背后的项目明细 -->
      <el-dialog v-model="boxDialogVisible" width="860px" top="6vh"
        :title="`数据明细 — ${plantCompare.year} 财年 Achievable BOL 分布`"
      >
        <!-- 弹窗内工厂筛选器 -->
        <div class="filter-bar filter-bar--compact" style="margin-bottom: 10px;">
          <span class="filter-label">工厂:</span>
          <el-select
            v-model="boxDialogPlants"
            multiple
            collapse-tags
            collapse-tags-tooltip
            clearable
            placeholder="全部工厂"
            style="width: 240px"
            size="small"
          >
            <el-option v-for="s in plantCompareStats" :key="s.plant" :label="s.plant" :value="s.plant" />
          </el-select>
          <span class="filter-hint">共 {{ boxDialogRows.length }} 条项目明细</span>
        </div>
        <!-- 统计摘要（与上层箱线图同口径） -->
        <div class="box-stat-summary" v-if="boxDialogSummary.length">
          <div v-for="s in boxDialogSummary" :key="s.plant" class="box-stat-item">
            <b>{{ s.plant }}</b>（{{ s.count }} 项）：
            最小 {{ s.min }} · Q1 {{ s.q1 }} · 中位 {{ s.median }} · Q3 {{ s.q3 }} · 最大 {{ s.max }} · 均值 {{ s.mean }}
          </div>
        </div>
        <el-table :data="boxDialogRows" stripe size="small" max-height="420">
          <el-table-column prop="project_code" label="项目代码" min-width="100" sortable />
          <el-table-column prop="project_name" label="项目名称" min-width="180" show-overflow-tooltip />
          <el-table-column prop="plant" label="工厂" min-width="65" align="center" sortable />
          <el-table-column prop="process_type" label="工艺" min-width="70" align="center" sortable />
          <el-table-column prop="bol" label="Achievable BOL" min-width="110" align="right" header-align="center" sortable>
            <template #default="{ row }"><span class="num-cell">{{ row.bol }}</span></template>
          </el-table-column>
          <el-table-column prop="roof_type" label="产品类型" min-width="85" align="center" />
          <el-table-column prop="volume" label="Volume" min-width="95" align="right" header-align="center" sortable>
            <template #default="{ row }"><span class="num-cell">{{ (row.volume ?? 0).toLocaleString() }}</span></template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!boxDialogRows.length" description="暂无明细数据" :image-size="60" />
      </el-dialog>

    </div>
  </div>
</template>

<style scoped>
.dashboard-tabs {
  margin-bottom: 16px;
}

.dashboard-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.stat-row {
  margin-bottom: 16px;
}

/* stat-card 系列样式统一由 main.css 全局规范接管：
   字号/字体/色条/内边距不再在 scoped 重复定义，
   KPI 差异色通过模板中 data-bar-color 修饰器声明 */

.chart-row {
  margin-bottom: 16px;
}

/* 改善目标对比图表：与下方“近 3 年”图表保持与 chart-row 一致的间距 */
.improve-chart {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 14px;
  /* 对齐三层标题规范 H3 */
  font-family: var(--font-display);
  color: var(--color-text);
}

.recent-card {
  margin-bottom: 16px;
}

/* Tab 2 钻取面包屑 */
.drill-breadcrumb {
  margin-bottom: 8px;
  padding: 6px 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-size: 12px;
}

/* 钻取返回按钮 + 面包屑 排版行 */
.drill-nav {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.drill-nav .drill-breadcrumb {
  margin-bottom: 0;
  flex: 1;
}

/* 箱线图钻取弹窗统计摘要 */
.box-stat-summary {
  margin-bottom: 10px;
  padding: 8px 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--color-text-2, var(--color-text));
}

.box-stat-item {
  line-height: 1.8;
}

.drill-breadcrumb a {
  color: var(--color-primary);
  cursor: pointer;
}

.drill-breadcrumb a:hover {
  text-decoration: underline;
}

.drill-current {
  color: var(--color-text);
  font-weight: 600;
}

.anomaly-card {
  margin-top: 8px;
  border-left: 3px solid var(--color-danger);
}

.filter-card {
  margin-bottom: 12px;
}

/* filter-bar 系列：统一由 main.css 全局规范接管，
   Tab 内嵌筛选使用 .filter-bar--compact 修饰器 */

.num-cell {
  font-variant-numeric: tabular-nums;
}
</style>


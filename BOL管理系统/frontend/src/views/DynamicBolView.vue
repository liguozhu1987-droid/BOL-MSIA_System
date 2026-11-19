<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { dynamicBolApi } from '@/api'
import { formatBol, formatDate, bolColorClass, normalizePlant, nearDoubleAnomaly, nearDoubleAnomalyText } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import { PALETTE, mintGradient, amberGradient, dangerGradient, aggregate, topN, histogram, withAlpha, BOL_COLORS, YOY_CHANGE, buildValueLabelConfig, adaptiveBarLayout } from '@/utils/echartsTheme'

// 筛选条件
const filters = reactive({
  location: '',
  process: '',
  roof_type: '',
  final_approve_status: '',
  program_code: ''
})

// 地点 / 工艺 / Roof Type / 审批状态下拉选项
const locationOptions = ref([])
const processOptions = ref([])
const roofTypeOptions = ref([])
const statusOptions = ref([
  { label: '全部', value: '' },
  { label: '已通过', value: 'Approved' },
  { label: '已驳回', value: 'Rejected' }
])

// 表格数据
const tableData = ref([])
const approvalStats = ref(null)
// by-process 数据（含 lb_rate），用于 Top10 LB 图表
const byProcessData = ref([])
const loading = ref(false)

// 分页
const pagination = reactive({
  page: 1,
  pageSize: 15,
  total: 0
})

// 当前页展示的数据（前端分页）
const pagedData = computed(() => {
  const start = (pagination.page - 1) * pagination.pageSize
  return tableData.value.slice(start, start + pagination.pageSize)
})

async function loadData() {
  loading.value = true
  try {
    const params = {}
    // location 不传后端（数据库存全称，前端显示标准代码，改为前端过滤）
    if (filters.process) params.process = filters.process
    if (filters.final_approve_status) params.final_approve_status = filters.final_approve_status
    if (filters.program_code) params.program_code = filters.program_code
    const statsParams = { ...params }
    if (filters.location) statsParams.location = filters.location
    if (filters.roof_type) statsParams.type = filters.roof_type
    const [res, stats] = await Promise.all([
      dynamicBolApi.overview(params),
      dynamicBolApi.approvalOverviewStats(statsParams).catch(() => null),
    ])
    approvalStats.value = stats
    const list = Array.isArray(res) ? res : (res.results || [])

    // 工厂名称标准化：将 location 字段统一为短代码（CJ/BJ/SH/CQ/GZ/WH）
    list.forEach((item) => {
      if (item.location) item.location = normalizePlant(item.location)
    })

    // 前端按 Roof Type 和 Location 过滤
    let filtered = list
    if (filters.roof_type) {
      filtered = filtered.filter((it) => it.type === filters.roof_type)
    }
    if (filters.location) {
      filtered = filtered.filter((it) => it.location === filters.location)
    }
    tableData.value = filtered
    pagination.total = filtered.length
    pagination.page = 1

    // 同时加载 by-process 数据（含 lb_rate），用于 Top10 LB 图表
    try {
      const bpRes = await dynamicBolApi.byProcess({ page_size: 200, ordering: '-update_time' })
      const bpList = Array.isArray(bpRes) ? bpRes : (bpRes.results || [])
      bpList.forEach((item) => {
        if (item.location) item.location = normalizePlant(item.location)
      })
      byProcessData.value = bpList
    } catch (e2) {
      byProcessData.value = []
    }

    // 填充筛选下拉项
    const locSet = new Set()
    const procSet = new Set()
    const roofSet = new Set()
    list.forEach((item) => {
      if (item.location) locSet.add(item.location)
      if (item.process) procSet.add(item.process)
      if (item.type) roofSet.add(item.type)
    })
    locationOptions.value = [{ label: '全部', value: '' }, ...[...locSet].sort().map((v) => ({ label: v, value: v }))]
    processOptions.value = [{ label: '全部', value: '' }, ...[...procSet].sort().map((v) => ({ label: v, value: v }))]
    roofTypeOptions.value = [{ label: '全部', value: '' }, ...[...roofSet].sort().map((v) => ({ label: v, value: v }))]
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
  filters.location = ''
  filters.process = ''
  filters.roof_type = ''
  filters.final_approve_status = ''
  filters.program_code = ''
  loadData()
}

function handlePageChange(page) {
  pagination.page = page
}

function handleSizeChange(size) {
  pagination.pageSize = size
  pagination.page = 1
}

// 审批状态标签颜色
function statusTagType(status) {
  const s = String(status || '')
  if (s === 'Approved') return 'success'
  if (s === 'Rejected') return 'danger'
  return 'info'
}

function statusLabel(status) {
  const s = String(status || '')
  if (s === 'Approved') return '已通过'
  if (s === 'Rejected') return '已驳回'
  return '待处理'
}

// 根据 BOL 值返回语义色
function bolValueColor(v) {
  if (v > 30) return BOL_COLORS.high
  if (v >= 20) return BOL_COLORS.mid
  return BOL_COLORS.low
}

// 计算中位数
function median(arr) {
  if (!arr.length) return 0
  const sorted = [...arr].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

// ============ 图表配置 ============

// 1. 近12个自然月各工厂审批通过项目-工艺数（全量后端聚合）
const factoryApprovedCountOption = computed(() => {
  const entries = (approvalStats.value?.approved_by_location || [])
    .slice()
    .sort((a, b) => b.count - a.count)

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 56, right: 20, top: 20, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: entries.map((e) => e.name),
      axisLabel: { rotate: entries.length > 4 ? 20 : 0, fontSize: 12 }
    },
    yAxis: {
      type: 'value',
      name: '审批通过项目数',
      nameLocation: 'middle',
      nameGap: 38,
      minInterval: 1
    },
    series: [{
      name: '审批通过项目数',
      type: 'bar',
      data: entries.map((e) => e.count),
      itemStyle: { color: mintGradient() },
      ...adaptiveBarLayout(),
      label: buildValueLabelConfig('barCompact', entries.length, {
        position: 'top',
        color: '#4b5563',
        fontSize: 12,
        formatter: '{c}'
      })
    }]
  }
})

// 2. Top10 LB 最低项目柱形图（数据源：CN_IE_BOLOverView_byProcess.lb_rate）
//    同一 project_code+process 仅取 update_time 最新的一条记录
//    横坐标显示"项目名称/process"
const topBolOption = computed(() => {
  // 构建 BOL_Nr → program_name 映射（来源：BolOverView 表数据）
  const bolNrToName = new Map()
  tableData.value.forEach((r) => {
    if (r.bol_nr && r.program_name) {
      if (!bolNrToName.has(r.bol_nr)) bolNrToName.set(r.bol_nr, r.program_name)
    }
  })

  // 按 (program_code, process) 分组，取 update_time 最新的一条
  const latestMap = new Map()
  byProcessData.value.forEach((r) => {
    const key = `${r.program_code || '-'}|${r.process || '-'}`
    const existing = latestMap.get(key)
    if (!existing || (r.update_time || '') > (existing.update_time || '')) {
      latestMap.set(key, r)
    }
  })

  // 提取 lb_rate，转为百分比
  const items = []
  latestMap.forEach((r, key) => {
    const lb = Number(r.lb_rate)
    if (Number.isNaN(lb) || lb <= 0) return
    // lb_rate 存储为 0-1 小数，转为百分比
    const pct = lb <= 1 ? lb * 100 : lb
    const [code, proc] = key.split('|')
    // 通过 BOL_Nr 查找项目名称
    const projName = bolNrToName.get(r.bol_nr) || code
    items.push({
      name: `${projName}/${proc}`,
      value: Number(pct.toFixed(2))
    })
  })

  // 按 LB rate 升序排列，取前 10（LB 最低的）
  items.sort((a, b) => a.value - b.value)
  const top = items.slice(0, 10)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = params[0]
        return `${p.name}<br/>LB rate: ${p.value}%`
      }
    },
    grid: { left: 40, right: 30, top: 30, bottom: 90, containLabel: true },
    xAxis: {
      type: 'category',
      data: top.map((it) => it.name),
      name: '项目名称/工艺',
      nameLocation: 'middle',
      nameGap: 70,
      nameTextStyle: { fontSize: 12, color: '#6b7280' },
      axisLabel: { fontSize: 10, rotate: 35, interval: 0, color: '#6b7280', width: 80, overflow: 'truncate' }
    },
    yAxis: {
      type: 'value',
      name: 'LB rate (%)',
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { fontSize: 12, color: '#6b7280' },
      axisLabel: { fontSize: 11, color: '#6b7280', formatter: '{value}%' },
      min: 0,
      max: 100
    },
    series: [{
      name: 'LB rate',
      type: 'bar',
      data: top.map((it) => it.value),
      itemStyle: {
        color: (params) => {
          const v = params.value
          // LB 越低越差（红），越高越好（绿）
          if (v < 70) return dangerGradient()
          if (v < 85) return amberGradient()
          return mintGradient()
        }
      },
      label: buildValueLabelConfig('barCompact', top.length, {
        position: 'top',
        color: '#4b5563',
        formatter: '{c}%'
      }),
      ...adaptiveBarLayout()
    }]
  }
})

// 3. 审批状态环形图
const statusDistOption = computed(() => {
  const items = aggregate(tableData.value, 'final_approve_status', null, 'count')
  const statusMap = { Approved: '已通过', Rejected: '已驳回', null: '待处理', '': '待处理' }
  const colorMap = { '已通过': BOL_COLORS.low, '已驳回': BOL_COLORS.high, '待处理': BOL_COLORS.mid }
  const data = items.map((it) => ({
    name: statusMap[it.name] || it.name || '待处理',
    value: it.value,
    itemStyle: { color: colorMap[statusMap[it.name] || it.name || '待处理'] || PALETTE[0] }
  }))
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    series: [{
      name: '审批状态',
      type: 'pie',
      radius: ['45%', '72%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: true,
      label: { show: true, color: '#1f2937', formatter: '{b}\n{d}%' },
      labelLine: { lineStyle: { color: '#6b7280' } },
      data
    }]
  }
})

// 4. 按工艺 BOL 散点分布图（同工艺下不同项目/产线的 BOL 分布对比）
// 说明：按工厂整体求平均无意义（不同 Roof Type / Process Type 混合），
// 改为按工艺分组展示每条记录的 BOL 值，便于同工艺下跨项目对比。
const procBolScatterOption = computed(() => buildScatterByDimension('process', '工艺'))

// 5. 按 Roof Type BOL 散点分布图
const roofBolScatterOption = computed(() => buildScatterByDimension('type', 'Roof Type'))

// 6. 按 Location BOL 散点分布图
const locBolScatterOption = computed(() => buildScatterByDimension('location', '地点'))

// 通用：按指定维度构建散点分布图（同维度下不同记录的 BOL 散点分布）
function buildScatterByDimension(field, label) {
  const groupMap = new Map()
  tableData.value.forEach((r) => {
    const key = r[field] || '未分类'
    if (!groupMap.has(key)) groupMap.set(key, [])
    const v = Number(r.bol)
    if (!Number.isNaN(v) && v > 0) {
      groupMap.get(key).push({
        value: v,
        program: r.program_code || '-',
        line: r.line_nr || '',
        location: r.location || '-',
        process: r.process || '-',
        roof: r.type || '-'
      })
    }
  })
  const list = [...groupMap.entries()].map(([name, arr]) => ({
    name, arr, median: median(arr.map((a) => a.value))
  })).sort((a, b) => b.median - a.median)

  const categories = list.map((it) => it.name)
  const series = list.map((it, idx) => ({
    name: it.name,
    type: 'scatter',
    data: it.arr.map((item) => [idx, item.value, item]),
    symbolSize: 10,
    itemStyle: {
      color: (params) => bolValueColor(params.value[1]),
      opacity: 0.75
    },
    emphasis: { focus: 'series', label: { show: false } }
  }))
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const d = p.data[2] || {}
        return `<b>${p.seriesName}</b><br/>BOL: ${p.data[1]}<br/>项目: ${d.program}<br/>产线: ${d.line || '-'}<br/>地点: ${d.location}<br/>工艺: ${d.process}<br/>Roof: ${d.roof}`
      }
    },
    grid: { left: 56, right: 24, top: 20, bottom: 50, containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { rotate: categories.length > 4 ? 20 : 0, fontSize: 11 },
      splitLine: { show: true, lineStyle: { color: '#e5e7eb', type: 'dashed' } }
    },
    yAxis: {
      type: 'value',
      name: 'BOL',
      nameLocation: 'middle',
      nameGap: 38
    },
    series
  }
}

// 7. 工艺 × Roof Type BOL 中位数热力图
const procRoofHeatmapOption = computed(() => {
  const procSet = new Set()
  const roofSet = new Set()
  const map = new Map() // key: `${proc}||${roof}`
  tableData.value.forEach((r) => {
    const proc = r.process || '未分类'
    const roof = r.type || '未分类'
    const v = Number(r.bol)
    if (Number.isNaN(v) || v <= 0) return
    procSet.add(proc)
    roofSet.add(roof)
    const key = `${proc}||${roof}`
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(v)
  })

  const procs = [...procSet].sort()
  const roofs = [...roofSet].sort()
  const data = []
  let maxVal = 0
  procs.forEach((proc, i) => {
    roofs.forEach((roof, j) => {
      const arr = map.get(`${proc}||${roof}`) || []
      if (arr.length > 0) {
        const med = Number(median(arr).toFixed(2))
        data.push({ value: [i, j, med, arr.length] })
        if (med > maxVal) maxVal = med
      }
    })
  })

  return {
    tooltip: {
      position: 'top',
      formatter: (p) => `${procs[p.value[0]]} × ${roofs[p.value[1]]}<br/>中位数 BOL: ${p.value[2]}<br/>样本数: ${p.value[3]}`
    },
    grid: { left: 60, right: 24, top: 30, bottom: 60, containLabel: true },
    xAxis: { type: 'category', data: procs, name: '工艺', splitArea: { show: true }, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'category', data: roofs, name: 'Roof Type', splitArea: { show: true }, axisLabel: { fontSize: 11 } },
    visualMap: {
      min: 0,
      max: maxVal || 50,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      textStyle: { color: '#4b5563', fontSize: 10 },
      inRange: { color: ['#dbeafe', '#3b82f6', '#f59e0b', '#dc2626'] }
    },
    series: [{
      name: 'BOL中位数',
      type: 'heatmap',
      data,
      label: buildValueLabelConfig('heatmap', Math.max(1, data.length), {
        color: '#1f2937',
        formatter: (p) => p.value[2]
      }),
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
    }]
  }
})

// 8. 近12个自然月审批记录状态趋势
const locStatusStackOption = computed(() => {
  const months = approvalStats.value?.months || []
  const statusLabelMap = { Approved: '已通过', Rejected: '已驳回', Pending: '待处理', Other: '其他' }
  const statusColorMap = {
    Approved: BOL_COLORS.low,
    Rejected: BOL_COLORS.high,
    Pending: BOL_COLORS.mid,
    Other: PALETTE[0],
  }
  const series = (approvalStats.value?.monthly_status || []).map((item) => ({
    name: statusLabelMap[item.status] || item.status,
    type: 'bar',
    stack: 'total',
    data: item.data,
    itemStyle: { color: statusColorMap[item.status] || PALETTE[0] },
    emphasis: { focus: 'series' }
  }))

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: '#4b5563' } },
    grid: { left: 56, right: 20, top: 20, bottom: 40, containLabel: true },
    xAxis: { type: 'category', data: months, axisLabel: { fontSize: 11, rotate: 30 } },
    yAxis: {
      type: 'value',
      name: '审批记录数（条）',
      nameLocation: 'middle',
      nameGap: 38
    },
    series
  }
})

// ===== TOP10 对比分析（审批BOL vs QWS、与上次审批环比） =====
const topCompareData = ref(null)
const topCompareLoading = ref(false)
const topCompareLocation = ref('')

const topComparePlantOptions = computed(() => topCompareData.value?.plant_options || [])

// 水平条形图构建：rise 红（上升/恶化）、drop 绿（下降/改善）
// TOP10 对比异常检测取值对：qws=审批BOL vs QWS报价；mom=最新BOL vs 上次BOL
function topCompareAnomalyPair(d, mode) {
  return mode === 'qws' ? [d.bol, d.qws_bol] : [d.bol_latest, d.bol_prev]
}

function topCompareBarOption(rows, mode, direction) {
  // rank1 在顶部：ECharts category 轴自下而上，反转数组（数据未加载时为空）
  const list = [...(rows || [])].reverse()
  if (!list.length) return {}
  const isDrop = direction === 'drop'
  const color = isDrop ? YOY_CHANGE.down : YOY_CHANGE.up
  // 接近 2 倍关系（偏差≈±50%）→ 疑似过程漏提交/重复提交，标记 ⚠
  const anomalyFlags = list.map((d) => {
    const [a, b] = topCompareAnomalyPair(d, mode)
    return !!nearDoubleAnomaly(a, b)
  })

  const tooltipBody = mode === 'qws'
    ? (d) =>
        `审批 BOL: <b>${d.bol}</b> · QWS 报价: <b>${d.qws_bol}</b><br/>` +
        `差值: <b>${d.gap > 0 ? '+' : ''}${d.gap}</b>（<b style="color:${color}">${d.change_pct > 0 ? '+' : ''}${d.change_pct}%</b>）`
    : (d) =>
        `上次 BOL: <b>${d.bol_prev}</b>（v${d.version_prev} · ${d.submit_date_prev || '-'}）<br/>` +
        `最新 BOL: <b>${d.bol_latest}</b>（v${d.version_latest} · ${d.submit_date_latest || '-'}）<br/>` +
        `变化: <b style="color:${color}">${d.change_pct > 0 ? '+' : ''}${d.change_pct}%</b>`

  return {
    grid: { left: 8, right: 70, top: 10, bottom: 10, containLabel: true },
    tooltip: {
      confine: true,
      trigger: 'item',
      formatter: (p) => {
        const d = list[p.dataIndex]
        if (!d) return ''
        // 异常提示块：琥珀左边线 + 浅底，说明倍数关系并建议核实
        const warn = anomalyFlags[p.dataIndex]
          ? `<div style="margin-top:4px;padding:3px 6px;border-left:3px solid ${PALETTE[1]};background:${withAlpha(PALETTE[1], 0.1)};color:${PALETTE[1]};font-size:11px">⚠ 提交异常提示：${nearDoubleAnomalyText(...topCompareAnomalyPair(d, mode))}</div>`
          : ''
        return `<b>${d.program_code} / ${d.process}</b>（${d.location || '-'}）<br/>` +
          `${d.program_name || ''}<br/>` + tooltipBody(d) + warn
      },
    },
    xAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%', fontSize: 11, color: '#6b7280' },
      splitLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'category',
      // 异常行的类目标签追加 ⚠，与 tooltip/汇总警告条呼应
      data: list.map((r, i) => `${r.program_code}/${r.process}${anomalyFlags[i] ? ' ⚠' : ''}`),
      axisLabel: { fontSize: 11, color: '#374151' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 18,
      itemStyle: { color, borderRadius: isDrop ? [3, 0, 0, 3] : [0, 3, 3, 0] },
      label: buildValueLabelConfig('barCompact', list.length, {
        position: isDrop ? 'left' : 'right',
        formatter: (p) => (p.value > 0 ? '+' : '') + p.value + '%' + (anomalyFlags[p.dataIndex] ? ' ⚠' : ''),
        color: '#374151',
        fontSize: 11,
      }),
      data: list.map((r) => r.change_pct),
    }],
  }
}

const qwsDropOption = computed(() => topCompareBarOption(topCompareData.value?.qws?.drop, 'qws', 'drop'))
const qwsRiseOption = computed(() => topCompareBarOption(topCompareData.value?.qws?.rise, 'qws', 'rise'))
const momDropOption = computed(() => topCompareBarOption(topCompareData.value?.mom?.drop, 'mom', 'drop'))
const momRiseOption = computed(() => topCompareBarOption(topCompareData.value?.mom?.rise, 'mom', 'rise'))

// TOP10 对比异常汇总：四张图中接近 2 倍关系的对比组（偏差≈±50%，疑似提交不规范）
const topCompareAnomalies = computed(() => {
  const data = topCompareData.value
  if (!data) return []
  const groups = [
    { mode: 'qws', label: '审批BOL vs QWS报价', lists: [['上升', data.qws?.rise], ['下降', data.qws?.drop]] },
    { mode: 'mom', label: '与上次审批环比', lists: [['上升', data.mom?.rise], ['下降', data.mom?.drop]] },
  ]
  const result = []
  for (const g of groups) {
    for (const [dir, rows] of g.lists) {
      for (const r of rows || []) {
        const [a, b] = topCompareAnomalyPair(r, g.mode)
        if (nearDoubleAnomaly(a, b)) {
          result.push({
            chart: `${g.label} · ${dir} TOP10`,
            name: `${r.program_code} / ${r.process}`,
            location: r.location || '-',
            pair: [a, b],
          })
        }
      }
    }
  }
  return result
})

async function loadTopCompare() {
  topCompareLoading.value = true
  try {
    const params = { top: 10 }
    if (topCompareLocation.value) params.location = topCompareLocation.value
    topCompareData.value = await dynamicBolApi.topCompare(params)
  } catch (e) {
    console.error('TOP10对比加载失败', e)
  } finally {
    topCompareLoading.value = false
  }
}

// 汇总卡片数据
const summaryStats = computed(() => {
  const total = tableData.value.length
  const approved = tableData.value.filter((r) => r.final_approve_status === 'Approved').length
  const rejected = tableData.value.filter((r) => r.final_approve_status === 'Rejected').length
  const pending = total - approved - rejected
  const locs = new Set(tableData.value.map((r) => r.location).filter(Boolean))
  const procs = new Set(tableData.value.map((r) => r.process).filter(Boolean))
  const roofs = new Set(tableData.value.map((r) => r.type).filter(Boolean))
  return {
    total, approved, rejected, pending,
    locCount: locs.size, procCount: procs.size, roofCount: roofs.size
  }
})

// 月度提交指标卡片（本月 / 上月 / 同比）—— 替代原"按月提交 BOL 趋势"图，避免与综合看板月度趋势重复
const monthlyStats = computed(() => {
  const now = new Date()
  const thisMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const lastMonthDate = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  const lastMonth = `${lastMonthDate.getFullYear()}-${String(lastMonthDate.getMonth() + 1).padStart(2, '0')}`

  let thisCount = 0, lastCount = 0
  tableData.value.forEach((r) => {
    if (!r.submit_date) return
    const m = String(r.submit_date).slice(0, 7)
    if (m === thisMonth) thisCount += 1
    else if (m === lastMonth) lastCount += 1
  })
  const yoyRate = lastCount > 0 ? (((thisCount - lastCount) / lastCount) * 100).toFixed(1) : null
  return {
    thisMonth: thisCount,
    lastMonth: lastCount,
    yoyRate: yoyRate === null ? null : Number(yoyRate),
    yoyDirection: yoyRate === null ? 'none' : (Number(yoyRate) >= 0 ? 'up' : 'down')
  }
})

// ======================== BOL 变更审批履历 Tab ========================

// Tab 切换
const activeTab = ref('overview')

// 级联筛选器（默认值：BJ+FA+BJFA1+T6763，避免进入页面无数据展示）
const trendFilters = reactive({
  location: 'BJ',
  process: 'FA',
  line_nr: 'BJFA1',
  program_code: 'T6763',
})
const trendFilterOptions = ref({
  locations: [],
  processes: [],
  lines: [],
  projects: [],
})
const trendFilterLoading = ref(false)

// 履历数据
const trendData = ref(null)
const trendLoading = ref(false)

// 选中项目名称（展示用）
const selectedProjectName = ref('')

// 加载级联筛选器选项
async function loadTrendFilterOptions() {
  trendFilterLoading.value = true
  try {
    const params = {}
    if (trendFilters.location) params.location = trendFilters.location
    if (trendFilters.process) params.process = trendFilters.process
    if (trendFilters.line_nr) params.line_nr = trendFilters.line_nr
    const res = await dynamicBolApi.approvalTrendFilterOptions(params)
    // 拦截器已返回 response.data，res 即为后端 JSON
    trendFilterOptions.value = res
  } catch (e) {
    console.error('加载筛选器失败', e)
  } finally {
    trendFilterLoading.value = false
  }
}

// 工厂变化时重置下游选项并重新加载
function onTrendLocationChange() {
  trendFilters.process = ''
  trendFilters.line_nr = ''
  trendFilters.program_code = ''
  selectedProjectName.value = ''
  loadTrendFilterOptions()
}

// 工艺变化时重置下游选项并重新加载
function onTrendProcessChange() {
  trendFilters.line_nr = ''
  trendFilters.program_code = ''
  selectedProjectName.value = ''
  loadTrendFilterOptions()
}

// 产线变化时重置项目选项并重新加载
function onTrendLineChange() {
  trendFilters.program_code = ''
  selectedProjectName.value = ''
  loadTrendFilterOptions()
}

// 项目变化时同步项目名称
function onTrendProjectChange() {
  const proj = trendFilterOptions.value.projects.find(p => p.code === trendFilters.program_code)
  selectedProjectName.value = proj ? proj.name : ''
}

// 查询履历
async function loadTrend() {
  if (!trendFilters.program_code || !trendFilters.process) {
    return
  }
  trendLoading.value = true
  try {
    const res = await dynamicBolApi.approvalTrend({
      program_code: trendFilters.program_code,
      process: trendFilters.process,
    })
    // 拦截器已返回 response.data，res 即为后端 JSON
    trendData.value = res
  } catch (e) {
    console.error('加载审批履历失败', e)
    trendData.value = null
  } finally {
    trendLoading.value = false
  }
}

// 是否可查询
const canQueryTrend = computed(() => !!trendFilters.program_code && !!trendFilters.process)

// 履历表格排序
const sortedTrendTimeline = computed(() => {
  if (!trendData.value?.timeline) return []
  return [...trendData.value.timeline].sort((a, b) => {
    const da = a.submit_date || ''
    const db = b.submit_date || ''
    return da.localeCompare(db)
  })
})

// ----- 4 个趋势折线图配置 -----

// 1. BOL(min) 趋势
const bolTrendOption = computed(() => {
  const tl = trendData.value?.timeline || []
  const xData = tl.map(t => t.submit_date || '')
  const yData = tl.map(t => t.bol_overall)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const idx = p.dataIndex
        const item = tl[idx]
        if (!item) return p.name
        return `<div style="font-weight:600;margin-bottom:4px">${item.submit_date || '-'}</div>
          <div>BOL: <b>${item.bol_overall ?? '-'} min</b></div>
          <div>版本: ${item.version || '-'}</div>
          <div>提交人: ${item.submit_user || '-'}</div>`
      }
    },
    grid: { left: 56, right: 24, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: xData, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: 'BOL (min)', scale: true },
    series: [{
      name: 'BOL',
      type: 'line',
      data: yData,
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3, color: '#0ea5e9' },
      itemStyle: { color: '#0ea5e9' },
      areaStyle: { color: 'rgba(14,165,233,0.1)' },
      label: buildValueLabelConfig('line', yData.length, {
        position: 'top',
        formatter: (p) => p.value != null ? p.value.toFixed(2) : ''
      }),
    }]
  }
})

// 2. CT(s) 趋势
const ctTrendOption = computed(() => {
  const tl = trendData.value?.timeline || []
  const xData = tl.map(t => t.submit_date || '')
  const yData = tl.map(t => t.ct)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const idx = p.dataIndex
        const item = tl[idx]
        if (!item) return p.name
        return `<div style="font-weight:600;margin-bottom:4px">${item.submit_date || '-'}</div>
          <div>CT: <b>${item.ct != null ? item.ct.toFixed(2) + ' s' : '-'}</b></div>
          <div>瓶颈工位: ${item.bottleneck_station || '-'}</div>
          <div>版本: ${item.version || '-'}</div>`
      }
    },
    grid: { left: 56, right: 24, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: xData, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: 'CT (s)', scale: true },
    series: [{
      name: 'CT',
      type: 'line',
      data: yData,
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3, color: '#0284c7' },
      itemStyle: { color: '#0284c7' },
      areaStyle: { color: 'rgba(2,132,199,0.1)' },
      label: buildValueLabelConfig('line', yData.length, {
        position: 'top',
        formatter: (p) => p.value != null ? p.value.toFixed(2) : ''
      }),
    }]
  }
})

// 3. HC(人数) 趋势
const hcTrendOption = computed(() => {
  const tl = trendData.value?.timeline || []
  const xData = tl.map(t => t.submit_date || '')
  const yData = tl.map(t => t.hc)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const idx = p.dataIndex
        const item = tl[idx]
        if (!item) return p.name
        return `<div style="font-weight:600;margin-bottom:4px">${item.submit_date || '-'}</div>
          <div>HC: <b>${item.hc != null ? item.hc.toFixed(1) + ' 人' : '-'}</b></div>
          <div>版本: ${item.version || '-'}</div>
          <div>提交人: ${item.submit_user || '-'}</div>`
      }
    },
    grid: { left: 56, right: 24, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: xData, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: 'HC (人)', scale: true },
    series: [{
      name: 'HC',
      type: 'line',
      data: yData,
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3, color: '#38bdf8' },
      itemStyle: { color: '#38bdf8' },
      areaStyle: { color: 'rgba(56,189,248,0.1)' },
      label: buildValueLabelConfig('line', yData.length, {
        position: 'top',
        formatter: (p) => p.value != null ? p.value.toFixed(1) : ''
      }),
    }]
  }
})

// 4. LB(线平衡率) 趋势 - 转为百分比
const lbTrendOption = computed(() => {
  const tl = trendData.value?.timeline || []
  const xData = tl.map(t => t.submit_date || '')
  const yData = tl.map(t => (t.lb != null ? +(t.lb * 100).toFixed(2) : null))
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const idx = p.dataIndex
        const item = tl[idx]
        if (!item) return p.name
        return `<div style="font-weight:600;margin-bottom:4px">${item.submit_date || '-'}</div>
          <div>LB: <b>${item.lb != null ? (item.lb * 100).toFixed(2) + '%' : '-'}</b></div>
          <div>瓶颈工位: ${item.bottleneck_station || '-'}</div>
          <div>版本: ${item.version || '-'}</div>`
      }
    },
    grid: { left: 56, right: 24, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: xData, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: 'LB (%)', scale: true, axisLabel: { formatter: '{value}%' } },
    series: [{
      name: 'LB',
      type: 'line',
      data: yData,
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3, color: '#0ea5e9' },
      itemStyle: { color: '#0ea5e9' },
      areaStyle: { color: 'rgba(14,165,233,0.1)' },
      label: buildValueLabelConfig('line', yData.filter(v => v != null).length, {
        position: 'top',
        formatter: (p) => p.value != null ? p.value + '%' : ''
      }),
      markLine: {
        silent: true,
        data: [{ yAxis: 85, lineStyle: { color: '#10b981', type: 'dashed' }, label: { formatter: '目标 85%' } }]
      }
    }]
  }
})

// 履历摘要变化量显示
function formatChange(val, unit = '', decimals = 2) {
  if (val == null) return '-'
  const sign = val > 0 ? '+' : ''
  return `${sign}${val.toFixed(decimals)}${unit}`
}

function changeColor(val) {
  if (val == null) return 'var(--color-text-muted)'
  // BOL/CT/HC 降低是改善（绿色），LB 提升是改善（绿色）
  return val < 0 ? 'var(--color-success)' : (val > 0 ? 'var(--color-danger)' : 'var(--color-text-muted)')
}

function lbChangeColor(val) {
  if (val == null) return 'var(--color-text-muted)'
  return val > 0 ? 'var(--color-success)' : (val < 0 ? 'var(--color-danger)' : 'var(--color-text-muted)')
}

// Tab 切换时初始化数据
async function onTabChange(tab) {
  if (tab === 'trend') {
    if (trendFilterOptions.value.locations.length === 0) {
      await loadTrendFilterOptions()
    }
    // 默认值齐全时自动查询履历
    if (trendFilters.program_code && trendFilters.process && !trendData.value) {
      // 同步项目名称
      const proj = trendFilterOptions.value.projects.find(p => p.code === trendFilters.program_code)
      selectedProjectName.value = proj ? proj.name : ''
      loadTrend()
    }
  }
  if (tab === 'lowlb' && !lowLbData.value) {
    loadLowLbAnalysis()
  }
  if (tab === 'topcompare' && !topCompareData.value) {
    loadTopCompare()
  }
}

// ======================== 改善机会分析 Tab ========================

const lowLbLoading = ref(false)
const lowLbData = ref(null)
const lowLbFilters = reactive({
  location: '',
  process: '',
  threshold: 0.85,
})
const lowLbLocationOptions = ref(['BJ', 'CJ', 'CMC', 'CQ', 'GZ', 'SH', 'YT', 'WH'])
const lowLbProcessOptions = ref(['FA', 'IHE', 'IHR', 'bonding'])

async function loadLowLbAnalysis() {
  lowLbLoading.value = true
  try {
    const params = { threshold: lowLbFilters.threshold }
    if (lowLbFilters.location) params.location = lowLbFilters.location
    if (lowLbFilters.process) params.process = lowLbFilters.process
    const res = await dynamicBolApi.lowLbAnalysis(params)
    lowLbData.value = res
  } catch (e) {
    console.error('加载低线平衡率分析失败', e)
    lowLbData.value = null
  } finally {
    lowLbLoading.value = false
  }
}

// 潜在减人 Top15 柱形图（保守方案）
const lowLbReduceOption = computed(() => {
  const items = lowLbData.value?.items || []
  const top = [...items].sort((a, b) => b.conservative.reduce - a.conservative.reduce).slice(0, 15)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = params[0]
        const idx = p.dataIndex
        const item = top[idx]
        if (!item) return p.name
        return `<div style="font-weight:600">${item.program_code}/${item.process}</div>
          <div>项目: ${item.program_name || '-'}</div>
          <div>客户: ${item.customer || '-'}</div>
          <div>当前 HC: ${item.hc}，LB: ${item.lb_percent}%</div>
          <div>潜在减人: ${item.potential_reduce} 人（原始值 ${item.potential_reduce_raw}）</div>
          <div style="color:#10b981">保守方案: 减 ${item.conservative.reduce} 人 → HC ${item.conservative.new_hc}（需LB ${item.conservative.lb_needed_percent}%）</div>
          <div style="color:#3b82f6">激进方案: 减 ${item.aggressive.reduce} 人 ${item.aggressive.feasible ? '→ HC ' + item.aggressive.new_hc + '（需LB ' + item.aggressive.lb_needed_percent + '%）' : '(不可行，需LB>91%)'}</div>`
      }
    },
    grid: { left: 70, right: 30, top: 35, bottom: 90, containLabel: true },
    xAxis: {
      type: 'category',
      data: top.map(it => `${it.program_code}/${it.process}`),
      axisLabel: { rotate: 35, fontSize: 10, interval: 0, color: '#6b7280', width: 80, overflow: 'truncate' },
    },
    yAxis: {
      type: 'value',
      name: '可减人数',
      nameLocation: 'end',
      nameGap: 15,
      nameTextStyle: { fontSize: 12, color: '#6b7280', align: 'left' },
      axisLabel: { color: '#6b7280' },
      minInterval: 1,
    },
    series: [{
      name: '保守减人',
      type: 'bar',
      data: top.map(it => it.conservative.reduce),
      itemStyle: { color: '#10b981' },
      label: buildValueLabelConfig('barCompact', top.length, {
        position: 'top',
        color: '#4b5563',
        formatter: '{c}'
      }),
      ...adaptiveBarLayout(),
    }, {
      name: '激进减人',
      type: 'bar',
      data: top.map(it => it.aggressive.feasible ? it.aggressive.reduce : 0),
      itemStyle: { color: '#3b82f6' },
      label: buildValueLabelConfig('barCompact', top.length, {
        position: 'top',
        color: '#4b5563',
        formatter: '{c}'
      }),
      ...adaptiveBarLayout(),
    }],
    legend: { top: 0, textStyle: { color: '#4b5563' } },
  }
})

onMounted(() => {
  loadData()
})

</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="BOL 审批记录"
      icon="DataLine"
      subtitle="所谓「动态 BOL」实际是 BOL 审批更新的历史记录：工厂做完改善后在系统提交 BOL 变更，经审批后形成更新记录。下表展示 HRDB 中 CN_IE_BOLOverView 的全部记录。"
      :breadcrumbs="[{ label: '数据管理' }, { label: 'BOL 审批记录' }]"
    />
    <div class="page-container">

    <el-tabs v-model="activeTab" type="border-card" class="bol-tabs" @tab-change="onTabChange">

    <!-- ===== Tab 1: BOL 审批概览 ===== -->
    <el-tab-pane label="BOL 审批概览" name="overview">

    <!-- 汇总指标卡 -->
    <div class="summary-grid">
      <div class="summary-item">
        <div class="summary-label">记录总数</div>
        <div class="summary-value text-mono">{{ summaryStats.total }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">已通过</div>
        <div class="summary-value text-mono bol-low">{{ summaryStats.approved }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">已驳回</div>
        <div class="summary-value text-mono bol-high">{{ summaryStats.rejected }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">待处理</div>
        <div class="summary-value text-mono bol-mid">{{ summaryStats.pending }}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">地点数</div>
        <div class="summary-value text-mono">{{ summaryStats.locCount }}</div>
      </div>
    </div>

    <!-- 区块 1：基础分布 -->
    <div class="section-title">
      <span class="section-bar"></span>
      <span class="section-text">基础分布</span>
      <span class="section-hint">近12个自然月 · 各工厂按项目编号+工艺去重计数</span>
    </div>
    <el-row :gutter="16" class="chart-row">
      <el-col :xs="24" :md="12" :lg="12">
        <ChartCard title="各工厂审批通过项目-工艺数" :subtitle="`近12个自然月 · 当前筛选范围 · 按工厂+项目编号+工艺去重`" :option="factoryApprovedCountOption" :height="260" />
      </el-col>
      <el-col :xs="24" :md="12" :lg="12">
        <ChartCard title="Top 10 LB 最低项目" subtitle="最新审批记录 · 按 LB rate 升序前 10（红=低&lt;70% / 黄=中70-85% / 绿=高≥85%）" :option="topBolOption" :height="260" />
      </el-col>
    </el-row>

    <!-- 区块 2：交叉维度分析 -->
    <div class="section-title">
      <span class="section-bar"></span>
      <span class="section-text">交叉维度分析</span>
      <span class="section-hint">工艺 × Roof Type 中位数 BOL 热力图；近12个自然月审批记录状态趋势</span>
    </div>
    <el-row :gutter="16" class="chart-row">
      <el-col :xs="24" :lg="14">
        <ChartCard title="工艺 × Roof Type BOL 中位数热力图" subtitle="交叉组合的 BOL 中位数（颜色越红值越高，仅显示有样本的单元格）" :option="procRoofHeatmapOption" :height="320" />
      </el-col>
      <el-col :xs="24" :lg="10">
        <ChartCard title="近12个月各月审批记录状态趋势" subtitle="当前筛选范围内的审批记录行数 · 堆叠区分已通过、已驳回、待处理及其他状态 · 不按项目去重" :option="locStatusStackOption" :height="320" />
      </el-col>
    </el-row>

    <!-- 筛选栏 -->
    <div class="section-title">
      <span class="section-bar"></span>
      <span class="section-text">明细数据</span>
      <span class="section-hint">筛选并查看具体记录</span>
    </div>
    <div class="filter-bar">
      <el-select v-model="filters.location" placeholder="地点" clearable style="width: 140px" filterable>
        <el-option v-for="opt in locationOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-model="filters.process" placeholder="工艺" clearable style="width: 140px" filterable>
        <el-option v-for="opt in processOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-model="filters.roof_type" placeholder="Roof Type" clearable style="width: 140px" filterable>
        <el-option v-for="opt in roofTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-model="filters.final_approve_status" placeholder="审批状态" clearable style="width: 130px">
        <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-input
        v-model="filters.program_code"
        placeholder="搜索项目代码"
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
    </div>

    <!-- 数据表格 -->
    <div class="table-container">
      <el-table :data="pagedData" stripe border size="small" style="width: 100%">
        <el-table-column prop="bol_nr" label="BOL编号" min-width="120" show-overflow-tooltip />
        <el-table-column prop="program_code" label="项目代码" min-width="110" />
        <el-table-column prop="program_name" label="项目名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="customer" label="客户" min-width="120" show-overflow-tooltip />
        <el-table-column prop="location" label="地点" min-width="90" />
        <el-table-column prop="process" label="工艺" min-width="90" />
        <el-table-column prop="type" label="Roof Type" min-width="100" />
        <el-table-column prop="line_nr" label="产线" min-width="80" />
        <el-table-column label="CT" width="80">
          <template #default="{ row }">
            <span class="num-cell">{{ Number(row.ct || 0).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="HC" width="80">
          <template #default="{ row }">
            <span class="num-cell">{{ Number(row.hc || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="OEE" width="80">
          <template #default="{ row }">
            <span class="num-cell">{{ (Number(row.oee || 0) * 100).toFixed(1) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="BOL值" width="100">
          <template #default="{ row }">
            <span class="num-cell" :class="bolColorClass(row.bol)">
              {{ formatBol(row.bol) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="QWS BOL" width="100">
          <template #default="{ row }">
            <span class="num-cell">{{ formatBol(row.qws_bol) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="差异" width="90">
          <template #default="{ row }">
            <span class="num-cell" :class="Number(row.gap_bol) > 0 ? 'bol-high' : 'bol-low'">
              {{ formatBol(row.gap_bol) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="审批状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.final_approve_status)" size="small">
              {{ statusLabel(row.final_approve_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="提交日期" width="110">
          <template #default="{ row }">{{ formatDate(row.submit_date) }}</template>
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
    </el-tab-pane>

    <!-- ===== Tab 2: BOL 审批履历 ===== -->
    <el-tab-pane label="BOL 审批履历" name="trend">
      <div v-loading="trendLoading" element-loading-text="加载审批履历...">

      <!-- 级联筛选器 -->
      <div class="trend-filter-bar" v-loading="trendFilterLoading" element-loading-text="加载筛选选项...">
        <el-select v-model="trendFilters.location" placeholder="工厂" clearable size="default" style="width: 140px" @change="onTrendLocationChange">
          <el-option v-for="l in trendFilterOptions.locations" :key="l" :label="l" :value="l" />
        </el-select>
        <el-select v-model="trendFilters.process" placeholder="工艺类型" clearable size="default" style="width: 150px; margin-left: 10px" :disabled="!trendFilters.location" @change="onTrendProcessChange">
          <el-option v-for="p in trendFilterOptions.processes" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="trendFilters.line_nr" placeholder="产线名称" clearable size="default" style="width: 160px; margin-left: 10px" :disabled="!trendFilters.process" @change="onTrendLineChange">
          <el-option v-for="ln in trendFilterOptions.lines" :key="ln" :label="ln" :value="ln" />
        </el-select>
        <el-select v-model="trendFilters.program_code" placeholder="项目编号" clearable filterable size="default" style="width: 180px; margin-left: 10px" :disabled="!trendFilters.process" @change="onTrendProjectChange">
          <el-option v-for="p in trendFilterOptions.projects" :key="p.code" :label="p.code" :value="p.code" />
        </el-select>
        <el-input v-model="selectedProjectName" placeholder="项目名称" readonly size="default" style="width: 260px; margin-left: 10px" />
        <el-button type="primary" size="default" style="margin-left: 12px" :disabled="!canQueryTrend" @click="loadTrend">查询</el-button>
      </div>

      <template v-if="trendData">
        <!-- 项目信息摘要卡 -->
        <div class="trend-summary-grid" v-if="trendData.timeline.length">
          <div class="trend-summary-item">
            <div class="trend-summary-label">项目</div>
            <div class="trend-summary-value">{{ trendData.project.program_code }}</div>
            <div class="trend-summary-sub" v-if="trendData.project.matched_codes && trendData.project.matched_codes.length > 1">
              合并: {{ trendData.project.matched_codes.join(' / ') }}
            </div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">工艺</div>
            <div class="trend-summary-value">{{ trendData.project.process }}</div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">工厂</div>
            <div class="trend-summary-value">{{ trendData.project.location || '-' }}</div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">客户</div>
            <div class="trend-summary-value">{{ trendData.project.customer || '-' }}</div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">版本数</div>
            <div class="trend-summary-value">{{ trendData.summary.version_count }}</div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">BOL 变化</div>
            <div class="trend-summary-value" :style="{ color: changeColor(trendData.summary.bol_overall_change) }">
              {{ formatChange(trendData.summary.bol_overall_change, ' min') }}
            </div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">CT 变化</div>
            <div class="trend-summary-value" :style="{ color: changeColor(trendData.summary.ct_change) }">
              {{ formatChange(trendData.summary.ct_change, ' s') }}
            </div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">HC 变化</div>
            <div class="trend-summary-value" :style="{ color: changeColor(trendData.summary.hc_change) }">
              {{ formatChange(trendData.summary.hc_change, ' 人', 1) }}
            </div>
          </div>
          <div class="trend-summary-item">
            <div class="trend-summary-label">LB 变化</div>
            <div class="trend-summary-value" :style="{ color: lbChangeColor(trendData.summary.lb_change) }">
              {{ formatChange(trendData.summary.lb_change != null ? trendData.summary.lb_change * 100 : null, '%', 2) }}
            </div>
          </div>
        </div>

        <!-- 4 个趋势折线图（2x2） -->
        <el-row :gutter="16" v-if="trendData.timeline.length">
          <el-col :xs="24" :md="12">
            <ChartCard title="BOL 变化趋势" subtitle="整体 BOL（min）· 来源 CN_IE_BOLOverView.BOL_Overall" :option="bolTrendOption" :height="320" />
          </el-col>
          <el-col :xs="24" :md="12">
            <ChartCard title="CT 变化趋势" subtitle="工艺 CT 合计（s）· 来源 CN_IE_BOLOverView_byProcess" :option="ctTrendOption" :height="320" />
          </el-col>
          <el-col :xs="24" :md="12">
            <ChartCard title="HC 变化趋势" subtitle="工艺 HC 合计（人）· 来源 CN_IE_BOLOverView_byProcess" :option="hcTrendOption" :height="320" />
          </el-col>
          <el-col :xs="24" :md="12">
            <ChartCard title="LB 变化趋势" subtitle="线平衡率均值（%）· 来源 CN_IE_BOLOverView_byProcess.LB_rate" :option="lbTrendOption" :height="320" />
          </el-col>
        </el-row>

        <!-- 履历明细表格 -->
        <div class="section-title" v-if="trendData.timeline.length">
          <span class="section-bar"></span>
          <span class="section-text">审批履历明细</span>
          <span class="section-hint">共 {{ trendData.timeline.length }} 个版本 · 按提交时间升序</span>
        </div>
        <el-table v-if="trendData.timeline.length" :data="sortedTrendTimeline" stripe border size="small" style="width: 100%; margin-top: 8px">
          <el-table-column prop="version" label="版本" width="70" />
          <el-table-column prop="program_code" label="项目编码" width="110" />
          <el-table-column prop="bol_nr" label="BOL编号" width="170" show-overflow-tooltip />
          <el-table-column prop="submit_date" label="提交日期" width="110" />
          <el-table-column label="提交人" width="180">
            <template #default="{ row }">
              <div class="user-cell">
                <span class="user-realname">{{ row.submit_user_realname || row.submit_user || '-' }}</span>
                <span class="user-username" v-if="row.submit_user_realname && row.submit_user">({{ row.submit_user }})</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="BOL (min)" width="110" align="right">
            <template #default="{ row }">
              <span class="num-cell">{{ row.bol_overall != null ? row.bol_overall.toFixed(2) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="CT (s)" width="100" align="right">
            <template #default="{ row }">
              <span class="num-cell">{{ row.ct != null ? row.ct.toFixed(2) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="HC (人)" width="100" align="right">
            <template #default="{ row }">
              <span class="num-cell">{{ row.hc != null ? row.hc.toFixed(1) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="LB (%)" width="100" align="right">
            <template #default="{ row }">
              <span class="num-cell" :style="{ color: row.lb != null && row.lb >= 0.85 ? 'var(--color-success)' : (row.lb != null && row.lb < 0.7 ? 'var(--color-danger)' : '') }">
                {{ row.lb != null ? (row.lb * 100).toFixed(2) + '%' : '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="bottleneck_station" label="瓶颈工位" width="100" />
          <el-table-column prop="location" label="工厂" width="70" />
          <el-table-column prop="line_nr" label="产线" width="100" show-overflow-tooltip />
        </el-table>

        <el-empty v-if="!trendData.timeline.length" description="该项目+工艺暂无审批通过的 BOL 变更记录" />
      </template>

      <el-empty v-else description="请选择工厂、工艺类型和项目编号后点击查询" />

      </div>
    </el-tab-pane>

    <!-- ===== Tab 3: 改善机会分析 ===== -->
    <el-tab-pane label="改善机会分析" name="lowlb">
      <div v-loading="lowLbLoading" element-loading-text="加载改善机会分析...">

      <!-- 筛选条 -->
      <div class="trend-filter-bar">
        <el-select v-model="lowLbFilters.location" placeholder="工厂" clearable size="default" style="width: 140px" @change="loadLowLbAnalysis">
          <el-option v-for="l in lowLbLocationOptions" :key="l" :label="l" :value="l" />
        </el-select>
        <el-select v-model="lowLbFilters.process" placeholder="工艺类型" clearable size="default" style="width: 150px; margin-left: 10px" @change="loadLowLbAnalysis">
          <el-option v-for="p in lowLbProcessOptions" :key="p" :label="p" :value="p" />
        </el-select>
        <el-input-number v-model="lowLbFilters.threshold" :min="0.5" :max="0.95" :step="0.05" :precision="2" size="default" style="width: 140px; margin-left: 10px" @change="loadLowLbAnalysis" />
        <span style="margin-left: 6px; color: var(--color-text-muted, #64748b); font-size: 12px;">LB 阈值</span>
      </div>

      <template v-if="lowLbData">
        <!-- 汇总指标卡 -->
        <div class="summary-grid" v-if="lowLbData.items.length">
          <div class="summary-item">
            <div class="summary-label">总项目数</div>
            <div class="summary-value">{{ lowLbData.summary.total_projects }}</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">低 LB 项目数</div>
            <div class="summary-value" style="color: var(--color-danger, #ef4444);">{{ lowLbData.summary.low_lb_projects }}</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">低 LB 总人数</div>
            <div class="summary-value">{{ lowLbData.summary.total_hc }}</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">潜在减人总数</div>
            <div class="summary-value" style="color: var(--color-success, #10b981);">{{ lowLbData.summary.total_potential_reduce }} 人</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">LB 阈值</div>
            <div class="summary-value">{{ (lowLbData.summary.threshold * 100).toFixed(0) }}%</div>
          </div>
        </div>

        <!-- 图表区（已合并：LB 最低排名与概览 Tab 的 Top 10 重复，此处仅保留潜在减人机会图） -->
        <el-row :gutter="16" v-if="lowLbData.items.length">
          <el-col :xs="24" :lg="24">
            <ChartCard
              title="潜在减人机会 Top15"
              subtitle="按潜在可缩减人数排序（保守方案）"
              :option="lowLbReduceOption"
              :height="380"
            />
          </el-col>
        </el-row>

        <!-- 改善机会明细表 -->
        <div class="section-title" v-if="lowLbData.items.length">
          <span class="section-bar"></span>
          <span class="section-text">改善机会明细</span>
          <span class="section-hint">共 {{ lowLbData.items.length }} 个项目 · 按 LB 升序 · 改善 LB 上限 91% · 仅显示圆整后可减 ≥1 人的项目</span>
        </div>
        <el-table v-if="lowLbData.items.length" :data="lowLbData.items" stripe border size="small" style="width: 100%; margin-top: 8px" :max-height="600">
          <el-table-column prop="program_code" label="项目编码" min-width="110" fixed />
          <el-table-column prop="program_name" label="项目名称" min-width="150" show-overflow-tooltip fixed />
          <el-table-column prop="customer" label="客户" min-width="100" show-overflow-tooltip />
          <el-table-column prop="process" label="工艺" min-width="80" />
          <el-table-column prop="location" label="工厂" min-width="70" />
          <el-table-column prop="line_nr" label="产线" min-width="110" show-overflow-tooltip />
          <el-table-column label="当前HC" min-width="80" align="right">
            <template #default="{ row }"><span class="num-cell">{{ row.hc }}</span></template>
          </el-table-column>
          <el-table-column label="当前LB" min-width="90" align="right">
            <template #default="{ row }">
              <span class="num-cell" :style="{ color: row.lb < 0.7 ? 'var(--color-danger, #ef4444)' : (row.lb < 0.8 ? 'var(--color-warning, #f59e0b)' : '') }">
                {{ row.lb_percent }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="bottleneck" label="瓶颈工位" min-width="100" show-overflow-tooltip />
          <el-table-column label="有效工作量" min-width="100" align="right">
            <template #default="{ row }"><span class="num-cell">{{ row.effective_work }}</span></template>
          </el-table-column>
          <el-table-column label="潜在减人" min-width="100" align="right">
            <template #default="{ row }">
              <span class="num-cell" style="color: var(--color-success, #10b981); font-weight: 600;">{{ row.potential_reduce }} 人</span>
            </template>
          </el-table-column>
          <el-table-column label="保守方案" min-width="170">
            <template #default="{ row }">
              <div v-if="row.conservative.feasible" class="plan-cell">
                <span class="plan-reduce">减 {{ row.conservative.reduce }} 人</span>
                <span class="plan-detail">→ HC {{ row.conservative.new_hc }}，需 LB {{ row.conservative.lb_needed_percent }}%</span>
              </div>
              <span v-else style="color: var(--color-text-muted, #64748b); font-size: 11px;">-</span>
            </template>
          </el-table-column>
          <el-table-column label="激进方案" min-width="170">
            <template #default="{ row }">
              <div v-if="row.aggressive.feasible" class="plan-cell">
                <span class="plan-reduce">减 {{ row.aggressive.reduce }} 人</span>
                <span class="plan-detail">→ HC {{ row.aggressive.new_hc }}，需 LB {{ row.aggressive.lb_needed_percent }}%</span>
              </div>
              <span v-else style="color: var(--color-text-muted, #64748b); font-size: 11px;">不可行（需 LB > 91%）</span>
            </template>
          </el-table-column>
          <el-table-column prop="update_time" label="数据日期" min-width="100" />
        </el-table>

        <el-empty v-if="!lowLbData.items.length" :description="`当前筛选条件下无 LB < ${(lowLbData.summary.threshold * 100).toFixed(0)}% 的项目`" />

      </template>

      </div>
    </el-tab-pane>

    <!-- ======================== TOP10 对比分析 Tab ======================== -->
    <el-tab-pane label="TOP10 对比分析" name="topcompare">
      <div v-loading="topCompareLoading" element-loading-text="加载 TOP10 对比分析...">

      <!-- 筛选条 -->
      <div class="trend-filter-bar">
        <el-select v-model="topCompareLocation" placeholder="工厂（空=全部）" clearable size="default" style="width: 160px" @change="loadTopCompare">
          <el-option v-for="p in topComparePlantOptions" :key="p" :label="p" :value="p" />
        </el-select>
      </div>

      <!-- 疑似提交异常汇总：对比数据接近 2 倍关系（偏差≈±50%）的项目 -->
      <el-alert
        v-if="topCompareAnomalies.length"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 12px"
        :title="`疑似提交异常 ${topCompareAnomalies.length} 项 · 对比数据接近 2 倍关系（偏差≈±50%），可能存在过程漏提交或重复提交，请核实后重新提交`"
      >
        <div v-for="(a, i) in topCompareAnomalies" :key="i" style="line-height: 1.9; font-size: 12px">
          ⚠ <b>{{ a.name }}</b>（{{ a.location }}）· {{ a.chart }} · {{ a.pair[0] }} vs {{ a.pair[1] }} — 接近 2 倍关系
        </div>
      </el-alert>

      <!-- 说明 -->
      <div class="section-title">
        <span class="section-bar"></span>
        <span class="section-text">审批BOL 与 QWS 报价对比</span>
        <span class="section-hint">每项目（合并同项目不同前缀编码）+工艺取最新 Approved 记录 · (BOL − QWS) / QWS × 100 · ⚠ = 疑似提交异常（接近 2 倍关系）</span>
      </div>
      <el-row :gutter="16" class="chart-row">
        <el-col :xs="24" :lg="12">
          <ChartCard title="审批 BOL vs QWS 报价 · 下降 TOP10" subtitle="绿 = 审批BOL 低于报价（改善）· (BOL − QWS) / QWS · ⚠ 疑似提交异常" :option="qwsDropOption" :height="340" />
        </el-col>
        <el-col :xs="24" :lg="12">
          <ChartCard title="审批 BOL vs QWS 报价 · 上升 TOP10" subtitle="红 = 审批BOL 高于报价（不利）· (BOL − QWS) / QWS · ⚠ 疑似提交异常" :option="qwsRiseOption" :height="340" />
        </el-col>
      </el-row>

      <div class="section-title">
        <span class="section-bar"></span>
        <span class="section-text">与上次审批环比</span>
        <span class="section-hint">同组最新两条 Approved 记录对比 · (最新 − 上次) / 上次 × 100 · ⚠ = 疑似提交异常（接近 2 倍关系）</span>
      </div>
      <el-row :gutter="16" class="chart-row">
        <el-col :xs="24" :lg="12">
          <ChartCard title="与上次审批环比 · 下降 TOP10" subtitle="绿 = 最新审批 BOL 较上次下降（改善）· (最新 − 上次) / 上次 · ⚠ 疑似提交异常" :option="momDropOption" :height="340" />
        </el-col>
        <el-col :xs="24" :lg="12">
          <ChartCard title="与上次审批环比 · 上升 TOP10" subtitle="红 = 最新审批 BOL 较上次上升（恶化）· (最新 − 上次) / 上次 · ⚠ 疑似提交异常" :option="momRiseOption" :height="340" />
        </el-col>
      </el-row>

      </div>
    </el-tab-pane>

    </el-tabs>
    </div>
  </div>
</template>

<style scoped>
/* 区块标题 */
.section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 24px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--color-border);
}

.section-bar {
  display: inline-block;
  width: 4px;
  height: 16px;
  background: var(--color-primary);
  border-radius: 2px;
}

.section-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
  letter-spacing: 0;
}

.section-hint {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-left: 8px;
}

/* 汇总指标卡 */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(9, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}

.summary-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 12px 14px;
  position: relative;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  transition: all var(--transition);
}

.summary-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--color-primary);
}

.summary-item:hover {
  border-color: var(--color-border-bright);
  box-shadow: var(--shadow);
}

.summary-label {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-bottom: 6px;
  font-weight: 500;
}

.summary-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1;
  letter-spacing: -0.02em;
}

.chart-row {
  margin-bottom: 16px;
}

/* 月度提交指标卡片（替代原按月趋势图） */
.monthly-metrics-card {
  height: 280px;
  background: #fff;
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: 8px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.monthly-metrics-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, #1f2937);
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border, #e5e7eb);
}
.monthly-metrics-row {
  display: flex;
  justify-content: space-around;
  align-items: center;
  flex: 1;
  gap: 16px;
}
.monthly-metric {
  text-align: center;
  flex: 1;
}
.monthly-metric-label {
  font-size: 12px;
  color: var(--color-text-muted, #6b7280);
  margin-bottom: 8px;
}
.monthly-metric-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--color-text, #1f2937);
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

/* 响应式：窄屏时汇总卡片改为 3 列 */
@media (max-width: 1200px) {
  .summary-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .section-hint {
    display: none;
  }
}

/* ===== BOL 变更审批履历 Tab 样式 ===== */
.bol-tabs {
  margin-top: 0;
}

.trend-filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 12px 0;
  margin-bottom: 8px;
}

.trend-summary-grid {
  display: grid;
  grid-template-columns: repeat(9, 1fr);
  gap: 10px;
  margin: 12px 0 16px;
}

.trend-summary-item {
  background: var(--color-bg-soft, #f8fafc);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: 8px;
  padding: 10px 12px;
  position: relative;
  overflow: hidden;
}

.trend-summary-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--gradient-primary, linear-gradient(90deg, #0ea5e9, #0284c7));
}

.trend-summary-label {
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.02em;
  margin-bottom: 4px;
}

.trend-summary-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text, #1e293b);
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}

.trend-summary-sub {
  margin-top: 4px;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted, #64748b);
  line-height: 1.3;
  word-break: break-all;
}

/* 提交人姓名单元格 */
.user-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.user-realname {
  font-size: 12px;
  color: var(--color-text, #1e293b);
  word-break: break-all;
}
.user-username {
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
}

/* 改善方案单元格 */
.plan-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.plan-reduce {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-success, #10b981);
}
.plan-detail {
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
}

@media (max-width: 1200px) {
  .trend-summary-grid {
    grid-template-columns: repeat(5, 1fr);
  }
}

@media (max-width: 768px) {
  .trend-summary-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .trend-filter-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .trend-filter-bar .el-select,
  .trend-filter-bar .el-input,
  .trend-filter-bar .el-button {
    width: 100% !important;
    margin-left: 0 !important;
  }
}
</style>

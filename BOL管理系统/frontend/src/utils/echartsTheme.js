// ECharts 浅蓝色简约科技主题
// 与全局 CSS 设计令牌保持一致：
//   主色 #0ea5e9（天蓝） / 强调 #f59e0b（琥珀）
//   语义色：success #10b981 / warning #f59e0b / danger #ef4444 / cyan #06b6d4 / purple #8b5cf6

// 主色调色板（用于多系列柱状图/折线图等）
// 以浅蓝为主，辅以青蓝、深蓝构成科技蓝谱系，再配琥珀/翠绿/紫等语义色
export const PALETTE = [
  '#0ea5e9', // 天蓝（主色）
  '#f59e0b', // 琥珀（强调）
  '#10b981', // 翠绿
  '#8b5cf6', // 紫
  '#ef4444', // 红
  '#06b6d4', // 青
  '#0284c7', // 深天蓝
  '#38bdf8', // 浅天蓝
  '#ec4899', // 粉
  '#14b8a6'  // 蓝绿
]

// BOL 值语义色（高/中/低）
export const BOL_COLORS = {
  high: '#dc2626',
  mid: '#d97706',
  low: '#059669'
}

// ============================================================
// 同比哑铃图（Achievable BOL YoY）专用色
// ============================================================
// 年份散点色板：旧年份 → 新年份 = 浅天蓝 → 深天蓝（主题蓝谱系，白描边保证浅色可辨）
export const YOY_YEAR_COLORS = ['#bae6fd', '#7dd3fc', '#38bdf8', '#0ea5e9', '#0284c7']

// 年份 → 散点颜色（把参与对比的年份按新旧映射到色板两端，最新年份最深）
export function yoyYearColor(yearsAsc, year) {
  const n = yearsAsc.length
  if (n <= 1) return YOY_YEAR_COLORS[YOY_YEAR_COLORS.length - 1]
  const yi = yearsAsc.indexOf(year)
  if (yi < 0) return YOY_YEAR_COLORS[YOY_YEAR_COLORS.length - 1]
  const idx = Math.round((yi / (n - 1)) * (YOY_YEAR_COLORS.length - 1))
  return YOY_YEAR_COLORS[idx]
}

// 连线语义色：后一年更大（恶化）= 红，后一年更小（改善）= 绿
export const YOY_CHANGE = {
  up: '#ef4444',   // 上升 = BOL 变大 = 恶化
  down: '#10b981'  // 下降 = BOL 变小 = 改善
}

// ============================================================
// 改善目标对比（工时哑铃图）专用色
// ============================================================
// 语义化配色（非同色系）：琥珀=预算基线 / 紫=改善目标 / 翠绿=达成，
// 三指标在哑铃图上对比时一眼可辨；连线退为中性灰蓝，不与散点争夺注意力
export const IMPROVE_HOURS = {
  budget: '#f59e0b',      // Budget 工时（琥珀 — 预算基线）
  target: '#8b5cf6',      // 改善目标工时（紫 — 目标）
  achievable: '#10b981',  // Achievable 工时（翠绿 — 达成）
  link: '#cbd5e1'         // 三点连线（中性灰蓝，弱化）
}

// ============================================================
// 图表规范常量（CHART_SPEC）—— 各页面图表统一引用
// 禁止在 option 构建器里散写柱宽/字号魔法数，保证全站图表视觉一致：
//   barMaxWidth:   柱最大宽度（类别数少时防止单柱过粗）
//   barCategoryGap: 类别内柱间距
//   gridStd:       标准网格（顶部留图例、底部留标签）
//   gridTall:      高图网格（X 轴标签旋转 40° + 轴名的长图）
//   gridCompact:   紧凑网格（水平条形图 / 小高度图）
//   labelAxis:     坐标轴与图例标签字号（统一 11，取代历史 10/11 混用）
//   labelTick:     数值标签字号
//   rotateThreshold: X 轴标签数超过该值时旋转 30-40°
// ============================================================
export const CHART_SPEC = {
  barMaxWidth: 22,
  barCategoryGap: '40%',
  gridStd: { top: 50, left: 50, right: 25, bottom: 45, containLabel: true },
  gridTall: { top: 55, left: 45, right: 25, bottom: 100, containLabel: true },
  gridCompact: { top: 15, left: 45, right: 50, bottom: 25, containLabel: true },
  labelAxis: 11,
  labelTick: 11,
  rotateThreshold: 8
}

// 柱形图柔性布局（防遮挡统一入口）：
// 禁止给 barWidth 写死百分比——百分比相对"类别槽位"而非按系列均分，
// 多系列并列时各系列柱宽之和可能超过槽位（如两系列各 60% = 120%），柱体直接相互遮挡；
// 且 ECharts 的 barMaxWidth 仅在未设置 barWidth 时生效，固定宽度会让上限失效。
// 正确做法：不设置 barWidth，交给 ECharts 自动按槽位均分柱宽——
//   类别越多 → 柱宽自动越细（永不遮挡）；类别越少 → 柱宽自动增粗；
// barMaxWidth 在类别稀少时封顶，防止两三根粗柱占满图面；
// barCategoryGap 控制相邻类别柱组间留白（直方图等需紧凑贴合的场景可调小）。
// 用法：在 bar 系列上展开 ...adaptiveBarLayout()，
//       直方图 ...adaptiveBarLayout({ categoryGap: '10%' })。
export function adaptiveBarLayout(opts = {}) {
  return {
    barMaxWidth: opts.maxWidth ?? CHART_SPEC.barMaxWidth,
    barCategoryGap: opts.categoryGap ?? CHART_SPEC.barCategoryGap
  }
}

// 图表数值标签显示策略：
// 1) 类别总量较少时，直接展示数值标签，降低“只看 hover 才知道数值”的操作成本；
// 2) 类别过多时，不展示所有标签，避免图像拥挤；
// 3) 细粒度图表可按业务场景放宽阈值（例如 12 个工厂仍可读）。
export function shouldShowInlineValueLabel(itemCount, denseThreshold = 10, moderateThreshold = 12) {
  const count = Number(itemCount || 0)
  if (!Number.isFinite(count) || count <= 0) return false
  if (count <= denseThreshold) return true
  return count <= moderateThreshold && moderateThreshold > denseThreshold
}

// 通用文本/网格颜色（浅色主题，深色文字 + 浅蓝边线）
export const AXIS = {
  text: '#3d5878',
  textDim: '#6b829e',
  line: '#e3ecf5',
  lineBright: '#c4d4e8'
}

// 统一图表标签规范：
// - 全站使用同一视觉语言：深蓝字 + 中等权重，避免某些图表标签过亮/过粗；
// - 仅在承载量合理时显示 inline label，密集图表保留 tooltip；
// - 根据图表类型分开阈值，保证不同密度维度都能看起来“恰到好处”。
export const CHART_LABEL_POLICY = {
  bar: {
    denseThreshold: 8,
    moderateThreshold: 11,
    style: { color: AXIS.text, fontSize: 10, fontWeight: 600, distance: 4 }
  },
  barCompact: {
    denseThreshold: 6,
    moderateThreshold: 9,
    style: { color: AXIS.text, fontSize: 9, fontWeight: 600, distance: 3 }
  },
  line: {
    denseThreshold: 10,
    moderateThreshold: 14,
    style: { color: AXIS.text, fontSize: 9, fontWeight: 600 }
  },
  heatmap: {
    denseThreshold: 20,
    moderateThreshold: 28,
    style: { color: '#1f2937', fontSize: 9, fontWeight: 500 }
  },
  scatter: {
    denseThreshold: 12,
    moderateThreshold: 16,
    style: { color: AXIS.text, fontSize: 9, fontWeight: 600, distance: 3 }
  },
  boxplot: {
    denseThreshold: 8,
    moderateThreshold: 11,
    style: { color: AXIS.text, fontSize: 8.5, fontWeight: 600, distance: 3 }
  },
  custom: {
    denseThreshold: 8,
    moderateThreshold: 11,
    style: { color: AXIS.text, fontSize: 8.5, fontWeight: 600, distance: 3 }
  }
}

export function buildValueLabelConfig(chartType = 'bar', itemCount, extra = {}) {
  const policy = CHART_LABEL_POLICY[chartType] || CHART_LABEL_POLICY.bar
  const show = shouldShowInlineValueLabel(itemCount, policy.denseThreshold, policy.moderateThreshold)
  const { show: forcedShow, ...rest } = extra || {}
  return {
    show: forcedShow ?? show,
    ...policy.style,
    ...rest
  }
}

// 图表字体回退链（DOM 不可读时使用，与 main.css --font-body 回退链一致）
const CHART_FONT_FALLBACK = "'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"

// 从 body 实际生效字体动态读取，保证图表文字与页面 DOM 字体统一
// （离线字体由 main.css @font-face 提供；中文经 unicode-range 回落到系统字体，
//  computed fontFamily 返回完整字体栈，ECharts 按栈依次匹配）
// 注意：模块求值时 main.css 可能尚未注入（main.js import 顺序所致），
// 故配合 baseOption.textStyle 的 getter 惰性求值，在每次图表渲染时解析
export function resolveChartFontFamily() {
  if (typeof document !== 'undefined' && document.body) {
    const ff = getComputedStyle(document.body).fontFamily
    if (ff && ff.trim()) return ff
  }
  return CHART_FONT_FALLBACK
}

// 构建 ECharts 通用配置（合并到 setOption 的 option 中）
export const baseOption = {
  textStyle: {
    color: AXIS.text,
    get fontFamily() {
      return resolveChartFontFamily()
    }
  },
  title: {
    textStyle: {
      color: '#0c1e35',
      fontSize: 14,
      fontWeight: 600
    },
    subtextStyle: {
      color: AXIS.text,
      fontSize: 12
    }
  },
  legend: {
    textStyle: { color: AXIS.text },
    pageTextStyle: { color: AXIS.text }
  },
  tooltip: {
    backgroundColor: 'rgba(255, 255, 255, 0.98)',
    borderColor: '#e3ecf5',
    borderWidth: 1,
    textStyle: { color: '#0c1e35', fontSize: 12 },
    // pointer-events:none 防止 axis tooltip DOM 悬停时拦截画布点击（下钻等交互依赖）
    extraCssText: 'box-shadow: 0 4px 16px rgba(14,165,233,0.12); pointer-events: none;'
  },
  grid: {
    left: 50,
    right: 24,
    top: 40,
    bottom: 36,
    containLabel: true
  },
  xAxis: {
    axisLine: { lineStyle: { color: AXIS.lineBright } },
    axisTick: { lineStyle: { color: AXIS.lineBright } },
    axisLabel: { color: AXIS.text, fontSize: 11 },
    splitLine: { show: false, lineStyle: { color: AXIS.line } }
  },
  yAxis: {
    axisLine: { lineStyle: { color: AXIS.lineBright } },
    axisTick: { lineStyle: { color: AXIS.lineBright } },
    axisLabel: { color: AXIS.text, fontSize: 11 },
    splitLine: { show: true, lineStyle: { color: AXIS.line, type: 'dashed' } }
  }
}

// 生成天蓝渐变（用于柱状图填充）
export function mintGradient(vertical = true) {
  const coords = vertical ? [0, 0, 0, 1] : [0, 0, 1, 0]
  return {
    type: 'linear',
    x: coords[0], y: coords[1], x2: coords[2], y2: coords[3],
    colorStops: [
      { offset: 0, color: '#38bdf8' },
      { offset: 1, color: '#0ea5e9' }
    ]
  }
}

// 生成琥珀渐变
export function amberGradient(vertical = true) {
  const coords = vertical ? [0, 0, 0, 1] : [0, 0, 1, 0]
  return {
    type: 'linear',
    x: coords[0], y: coords[1], x2: coords[2], y2: coords[3],
    colorStops: [
      { offset: 0, color: '#fbbf24' },
      { offset: 1, color: '#f59e0b' }
    ]
  }
}

// 危险红渐变
export function dangerGradient(vertical = true) {
  const coords = vertical ? [0, 0, 0, 1] : [0, 0, 1, 0]
  return {
    type: 'linear',
    x: coords[0], y: coords[1], x2: coords[2], y2: coords[3],
    colorStops: [
      { offset: 0, color: '#f87171' },
      { offset: 1, color: '#dc2626' }
    ]
  }
}

// 将十六进制颜色转换为 rgba（带透明度）
export function withAlpha(hex, alpha) {
  const h = hex.replace('#', '')
  const r = parseInt(h.substring(0, 2), 16)
  const g = parseInt(h.substring(2, 4), 16)
  const b = parseInt(h.substring(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// 简单聚合：按指定字段分组求和/计数/平均
// items: 数组；groupBy: 字段名；valueField: 字段名或函数；op: 'sum'|'count'|'avg'|'max'
export function aggregate(items, groupBy, valueField, op = 'count') {
  const map = new Map()
  const getKey = (item) => {
    if (typeof groupBy === 'function') return groupBy(item) || '其他'
    return item[groupBy] || '其他'
  }
  const getVal = (item) => {
    if (valueField == null) return 1
    if (typeof valueField === 'function') return Number(valueField(item)) || 0
    return Number(item[valueField]) || 0
  }
  items.forEach((item) => {
    const key = getKey(item)
    const val = getVal(item)
    if (!map.has(key)) {
      map.set(key, { sum: 0, count: 0, max: val })
    }
    const entry = map.get(key)
    entry.sum += val
    entry.count += 1
    entry.max = Math.max(entry.max, val)
  })
  const result = []
  map.forEach((entry, key) => {
    let value = 0
    if (op === 'sum') value = entry.sum
    else if (op === 'count') value = entry.count
    else if (op === 'avg') value = entry.count ? entry.sum / entry.count : 0
    else if (op === 'max') value = entry.max
    result.push({ name: key, value: Number(value.toFixed(2)) })
  })
  return result
}

// 取 Top N（按 value 降序），返回 [{ name, value }]
export function topN(items, n = 10) {
  return [...items].sort((a, b) => b.value - a.value).slice(0, n)
}

// 构建直方图分箱
// values: 数值数组；binCount: 分箱数
// 返回 { categories: ['0-10', '10-20', ...], counts: [3, 5, ...] }
export function histogram(values, binCount = 8) {
  const nums = values.map((v) => Number(v)).filter((n) => !Number.isNaN(n))
  if (nums.length === 0) return { categories: [], counts: [] }
  const min = Math.min(...nums)
  const max = Math.max(...nums)
  if (min === max) {
    return { categories: [`${min.toFixed(1)}`], counts: [nums.length] }
  }
  const step = (max - min) / binCount
  const categories = []
  const counts = new Array(binCount).fill(0)
  for (let i = 0; i < binCount; i += 1) {
    const lo = min + i * step
    const hi = min + (i + 1) * step
    categories.push(`${lo.toFixed(1)}-${hi.toFixed(1)}`)
  }
  nums.forEach((v) => {
    let idx = Math.floor((v - min) / step)
    if (idx >= binCount) idx = binCount - 1
    if (idx < 0) idx = 0
    counts[idx] += 1
  })
  return { categories, counts }
}

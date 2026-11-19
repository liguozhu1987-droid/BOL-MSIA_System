// 数值与日期格式化工具（多视图共享）

// BOL 值：保留 2 位小数；空值或 0 显示为 '-'
export function formatBol(value) {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  if (num === 0) return '-'
  return num.toFixed(2)
}

// 金额：保留 0 位小数，加 ¥ 前缀
export function formatCurrency(value) {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  return '¥' + Math.round(num).toLocaleString('zh-CN')
}

// 百分比：保留 1 位小数，加 % 后缀
export function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  return num.toFixed(1) + '%'
}

// 日期：YYYY-MM-DD
export function formatDate(value) {
  if (!value) return '-'
  const str = String(value)
  if (str.length >= 10) return str.slice(0, 10)
  return str
}

// 日期时间：YYYY-MM-DD HH:mm
export function formatDateTime(value) {
  if (!value) return '-'
  const str = String(value)
  if (str.length >= 16) return str.slice(0, 16).replace('T', ' ')
  if (str.length >= 10) return str.slice(0, 10)
  return str
}

// 根据 BOL 值返回颜色类名
export function bolColorClass(value) {
  const num = Number(value)
  if (Number.isNaN(num)) return ''
  if (num > 30) return 'bol-high'
  if (num >= 20) return 'bol-mid'
  return 'bol-low'
}

// 工厂名称标准化：将各种变体统一为短代码（CJ/BJ/SH/CQ/GZ/WH/CMC/YT）
const PLANT_ALIAS_MAP = {
  'cj': 'CJ', 'cj inalfa': 'CJ', 'cc': 'CJ', 'changchun': 'CJ',
  'bj': 'BJ', 'bj inalfa': 'BJ', 'beijing': 'BJ',
  'sh': 'SH', 'sh inalfa': 'SH', 'shanghai': 'SH',
  'cq': 'CQ', 'cq inalfa': 'CQ', 'chongqing': 'CQ',
  'gz': 'GZ', 'gz inalfa': 'GZ', 'guangzhou': 'GZ',
  'wh': 'WH', 'wh inalfa': 'WH', 'wuhan': 'WH',
  'cmc': 'CMC', 'cmc inalfa': 'CMC',
  'yt': 'YT', 'yt inalfa': 'YT',
}

export function normalizePlant(raw) {
  if (!raw) return ''
  const s = String(raw).trim()
  const base = s.split('_')[0].trim()
  return PLANT_ALIAS_MAP[base.toLowerCase()] || base
}

// ============================================================
// 对比数据异常检测（多视图共享）
// ============================================================
// 背景：两次提交数据接近 2 倍关系（偏差接近 ±50%）时，通常并非真实变化，
// 而是提交不规范所致 —— 例如双线生产 2 块玻璃的项目只提交了 1 块
//（如 T6373 IHE：18.99 vs 37.97，18.99 漏提交了一条线的过程）。
// 判定口径：较大值/较小值 ∈ [1.8, 2.2]（即约 2 倍，±10% 容差）
const NEAR_DOUBLE_LO = 1.8
const NEAR_DOUBLE_HI = 2.2

// 检测两个对比值是否接近 2 倍关系；命中返回 { ratio }，未命中返回 null
export function nearDoubleAnomaly(a, b) {
  const x = Number(a)
  const y = Number(b)
  if (!Number.isFinite(x) || !Number.isFinite(y) || x <= 0 || y <= 0) return null
  const ratio = Math.max(x, y) / Math.min(x, y)
  if (ratio >= NEAR_DOUBLE_LO && ratio <= NEAR_DOUBLE_HI) return { ratio }
  return null
}

// 异常提示文案（tooltip / 警告条共用）；说明倍数关系与核实建议
export function nearDoubleAnomalyText(a, b) {
  const hit = nearDoubleAnomaly(a, b)
  if (!hit) return ''
  const x = Number(a)
  const y = Number(b)
  const smaller = Math.min(x, y)
  const larger = Math.max(x, y)
  return `两次数据接近 2 倍关系（${smaller} ≈ ${larger} × 0.5），疑似存在过程漏提交或重复提交，请核实提交规范性`
}

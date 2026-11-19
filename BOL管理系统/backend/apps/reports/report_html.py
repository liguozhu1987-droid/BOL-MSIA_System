# -*- coding: utf-8 -*-
"""BOL 季度/年度分析报告 HTML 生成（移植自 报告生成脚本/gen_reports.py）

与参考报告（BOL_Annual_Report_2026.html / BOL_Quarterly_Report_2026Q2.html）
形式完全一致：同一 CSS、同一图表 JS、同一章节结构；差异仅在于：
  - 周期参数化（任意年份/季度）
  - 叙事文案改为数据驱动（原脚本中写死的事实改为从数据计算）
"""
import html
import json
from collections import defaultdict
from pathlib import Path

# ECharts 库（内联进报告 HTML，报告为完整 standalone 快照）
_ECH_PATH = Path(__file__).resolve().parent / 'echarts.min.js'

PLANT_CN = {'BJ': '北京', 'SH': '上海', 'CJ': '长春', 'CQ': '重庆', 'GZ': '广州',
            'WH': '武汉', 'CMC': 'CMC', 'YT': '烟台'}

MAIN_PLANTS = ['BJ', 'SH', 'CJ', 'CQ', 'GZ']


def esc(x):
    return html.escape(str(x)) if x else ''


def pcn(p):
    return PLANT_CN.get(p, p)


def plabel(pc, pn, suffix=''):
    """项目类目标签：代号·名称（名称为空时仅显示代号），用于图表类目/悬浮提示。"""
    return f"{pc}·{pn}{suffix}" if pn else f"{pc}{suffix}"


def jd(x):
    return json.dumps(x, ensure_ascii=False)


def _load_echarts():
    ech = _ECH_PATH.read_text(encoding='utf-8').strip()
    if ech.startswith('<script>'):
        ech = ech[len('<script>'):]
    if ech.endswith('</script>'):
        ech = ech[:-len('</script>')]
    return ech


# ══════════════════ CSS（与参考报告一致）══════════════════
CSS = """
  :root {
    --accent: #2e5aac; --accent2: #e07a5f; --success: #27ae60; --danger: #e74c3c;
    --ink: #1a1a2e; --muted: #6b7280; --rule: #d1d5db; --bg: #ffffff; --bg2: #f8fafc;
    --card: #ffffff; --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
    --radius: 8px;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { font-size: 15px; scroll-behavior: smooth; }
  body { font-family: 'Noto Sans CJK SC', 'PingFang SC', 'Microsoft YaHei', sans-serif; color: var(--ink); background: var(--bg2); line-height: 1.7; }
  .container { max-width: 1120px; margin: 0 auto; padding: 24px 20px 60px; }
  .report-header { background: linear-gradient(135deg, var(--accent) 0%, #1a3a6e 100%); color: #fff; padding: 40px 32px; border-radius: var(--radius); margin-bottom: 32px; }
  .report-header h1 { font-size: 1.8rem; font-weight: 700; margin-bottom: 8px; }
  .report-header .subtitle { font-size: 1rem; opacity: .85; }
  .report-header .meta { margin-top: 16px; font-size: .85rem; opacity: .7; }
  .section { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); padding: 28px 28px 20px; margin-bottom: 28px; }
  .section h2 { font-size: 1.35rem; color: var(--accent); border-bottom: 2px solid var(--accent); padding-bottom: 8px; margin-bottom: 20px; }
  .section h3 { font-size: 1.1rem; color: var(--ink); margin: 24px 0 14px; padding-left: 12px; border-left: 4px solid var(--accent); }
  .table-wrap { overflow-x: auto; margin: 12px 0 20px; border-radius: 6px; border: 1px solid var(--rule); }
  table { width: 100%; border-collapse: collapse; font-size: .88rem; }
  thead { position: sticky; top: 0; z-index: 2; }
  th { background: var(--accent); color: #fff; padding: 10px 14px; text-align: center; font-weight: 600; white-space: nowrap; }
  td { padding: 9px 14px; text-align: center; border-bottom: 1px solid var(--rule); }
  tbody tr:nth-child(even) { background: var(--bg2); }
  tbody tr:hover { background: #eef2ff; }
  td:first-child, th:first-child { text-align: left; font-weight: 500; }
  td.lft { text-align: left; font-weight: 500; }
  .chart-box { width: 100%; height: 430px; margin: 16px 0 8px; border: 1px solid var(--rule); border-radius: 6px; background: var(--bg); }
  .chart-box.sm { height: 380px; }
  .chart-legend-hint { font-size: .78rem; color: var(--muted); margin: 0 0 16px; padding-left: 4px; }
  .insight-box { background: #eef2ff; border-left: 4px solid var(--accent); padding: 14px 18px; margin: 14px 0; border-radius: 0 6px 6px 0; font-size: .9rem; line-height: 1.8; }
  .warn-box { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 14px 18px; margin: 14px 0; border-radius: 0 6px 6px 0; font-size: .9rem; line-height: 1.8; }
  .tag { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: .78rem; font-weight: 600; margin: 2px 4px 2px 0; white-space: nowrap; }
  .tag-best { background: #d1fae5; color: #065f46; }
  .tag-warn { background: #fef3c7; color: #92400e; }
  .tag-hot  { background: #fee2e2; color: #991b1b; }
  .tag-small { background: #f3f4f6; color: #6b7280; }
  .stat-row { display: flex; flex-wrap: wrap; gap: 16px; margin: 16px 0; }
  .stat-card { flex: 1; min-width: 160px; background: var(--bg2); border: 1px solid var(--rule); border-radius: 6px; padding: 16px; text-align: center; }
  .stat-card .num { font-size: 1.6rem; font-weight: 700; color: var(--accent); }
  .stat-card .num.red { color: var(--danger); }
  .stat-card .num.green { color: var(--success); }
  .stat-card .label { font-size: .82rem; color: var(--muted); margin-top: 4px; }
  .summary-list { list-style: none; padding: 0; }
  .summary-list li { padding: 6px 0 6px 18px; position: relative; }
  .summary-list li::before { content: ''; position: absolute; left: 0; top: 14px; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
  .report-footer { text-align: center; color: var(--muted); font-size: .8rem; padding: 24px 0 0; border-top: 1px solid var(--rule); margin-top: 20px; }
  .delta-down { color: var(--success); font-weight: 600; }
  .delta-up { color: var(--danger); font-weight: 600; }
  .empty-box { border: 2px dashed var(--rule); border-radius: 8px; padding: 28px; text-align: center; color: var(--muted); background: var(--bg2); font-size: .9rem; margin: 12px 0 20px; }
  @media (max-width: 768px) {
    .container { padding: 12px 10px 40px; }
    .report-header { padding: 24px 18px; }
    .report-header h1 { font-size: 1.3rem; }
    .section { padding: 18px 14px 14px; }
    .chart-box { height: 350px; }
    table { font-size: .8rem; }
    th, td { padding: 7px 8px; }
  }
  @media print {
    body { background: #fff; }
    .section { box-shadow: none; border: 1px solid #ddd; break-inside: auto; page-break-inside: auto; }
    .section h2, .section h3 { break-after: avoid; page-break-after: avoid; }
    .table-wrap { overflow: visible; }
    thead { position: static; display: table-header-group; }
    tr { break-inside: avoid; page-break-inside: avoid; }
    .chart-box { height: 300px; }
  }
"""

# ══════════════════ 图表JS（与参考报告一致）══════════════════
JS_CHART = """
function baseOpt(title, sub, cfg) {
  cfg = cfg || {};
  var opt = {
    title: { text: title, subtext: sub || '', left: 4, top: 2,
             textStyle: { fontSize: 15, color: '#1a1a2e' },
             subtextStyle: { fontSize: 11, color: '#6b7280' } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(46,90,172,.06)' } },
               textStyle: { fontSize: 12 }, confine: true, extraCssText: 'max-width:360px;white-space:normal;' },
    grid: { left: 62, right: 56, top: sub ? 84 : 62, bottom: cfg.bottom || 62,
            containLabel: true },
    labelLayout: { hideOverlap: true }
  };
  if (cfg.legend !== false) {
    opt.legend = { bottom: 0, left: 'center', itemGap: 18, itemWidth: 14, itemHeight: 9,
                   textStyle: { fontSize: 12, color: '#4b5563' } };
  }
  return opt;
}
function barChart(id, title, sub, cats, series, cfg) {
  cfg = cfg || {};
  var opt = baseOpt(title, sub, cfg);
  var rotate = cfg.rotate || (cats.length > 8);
  opt.xAxis = { type: 'category', data: cats,
                axisLabel: { fontSize: 11, interval: 0, rotate: rotate ? 38 : 0, margin: 12 },
                axisTick: { alignWithLabel: true } };
  opt.yAxis = { type: 'value', name: cfg.yName || '', nameTextStyle: { fontSize: 11 } };
  opt.series = series.map(function (s) {
    return { name: s.name, type: 'bar', data: s.data, barMaxWidth: 40,
      itemStyle: { color: s.color, borderRadius: [3, 3, 0, 0] },
      label: ((series.length === 1 && cfg.labels !== false) || s.label === true)
        ? { show: true, position: 'top', fontSize: 11, color: '#374151' } : undefined };
  });
  if (cfg.hl && cfg.hl.length && series.length === 1) {
    opt.series[0].data = opt.series[0].data.map(function (v, i) {
      return cfg.hl.indexOf(i) >= 0 ? { value: v, itemStyle: { color: '#1a3a6e' } } : v;
    });
  }
  initChart(id, opt);
}
function hBarChart(id, title, sub, cats, series, cfg) {
  cfg = cfg || {};
  var opt = baseOpt(title, sub, cfg);
  opt.grid = { left: 64, right: 76, top: sub ? 84 : 62, bottom: cfg.bottom || 62 };
  opt.xAxis = { type: 'value' };
  opt.yAxis = { type: 'category', data: cats, axisLabel: { fontSize: 12, margin: 12 } };
  opt.series = series.map(function (s) {
    return { name: s.name, type: 'bar', data: s.data, barMaxWidth: 24,
      itemStyle: { color: s.color, borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', fontSize: 11, color: '#374151' } };
  });
  initChart(id, opt);
}
function lineChart(id, title, sub, cats, series, ref) {
  var hasEnd = series.some(function (s) { return !!s.endLabel; });
  var opt = baseOpt(title, sub, { bottom: 66 });
  opt.grid.right = hasEnd ? 96 : 56;
  var rotate = cats.length > 10;
  opt.xAxis = { type: 'category', data: cats, boundaryGap: false,
                axisLabel: { fontSize: 11, rotate: rotate ? 38 : 0, margin: 12 } };
  opt.yAxis = { type: 'value', scale: true, name: '', nameTextStyle: { fontSize: 11 } };
  opt.series = series.map(function (s) {
    return { name: s.name, type: 'line', data: s.data, symbol: 'circle', symbolSize: 6,
      lineStyle: { width: 2.5 }, itemStyle: { color: s.color }, connectNulls: true,
      endLabel: { show: !!s.endLabel, formatter: '{a} {c}', fontSize: 11, color: s.color, distance: 8 } };
  });
  if (ref) {
    opt.series.push({ name: ref.label, type: 'line', data: [],
      markLine: { symbol: 'none', silent: true,
        lineStyle: { color: '#e74c3c', type: 'dashed' },
        label: { formatter: ref.label, position: 'insideStartTop', fontSize: 11 },
        data: [{ yAxis: ref.y }] } });
  }
  initChart(id, opt);
}
function stackChart(id, title, sub, cats, series) {
  var opt = baseOpt(title, sub);
  opt.xAxis = { type: 'category', data: cats, axisLabel: { fontSize: 12, interval: 0, margin: 12 } };
  opt.yAxis = { type: 'value', name: '项数', nameTextStyle: { fontSize: 11 } };
  opt.series = series.map(function (s) {
    return { name: s.name, type: 'bar', stack: 't', data: s.data, barMaxWidth: 48,
      itemStyle: { color: s.color },
      label: { show: true, fontSize: 10, color: '#fff',
               formatter: function (p) { return p.value > 0 ? p.value : ''; } } };
  });
  initChart(id, opt);
}
function crossChart(id, title, sub, cats, avg, mn, mx, unit) {
  var opt = baseOpt(title, sub);
  opt.legend.data = ['均值'];
  var rotate = cats.length > 4;
  // 顶部：含 subtext + 柱状图 top 标签留白；底部：x 轴 label（可能旋转 38°）+ legend
  opt.grid = { left: 62, right: 56, top: sub ? 96 : 74,
               bottom: rotate ? 92 : 72, containLabel: true };
  opt.xAxis = { type: 'category', data: cats,
                axisLabel: { fontSize: 12, interval: 0, margin: 10,
                             rotate: rotate ? 38 : 0, width: 100, overflow: 'truncate' } };
  // y 轴范围必须覆盖 I 型线的 min/max（custom 系列只带类别索引，不参与自动范围计算，
  // 否则 max 端点超出轴上限会被 clip 裁掉 → 图表显示不完整）
  var yLo = Math.min.apply(null, mn.concat(avg));
  var yHi = Math.max.apply(null, mx.concat(avg));
  opt.yAxis = { type: 'value', scale: true, name: unit || '', nameTextStyle: { fontSize: 11 },
                min: function (v) { return yLo - (yHi - yLo) * 0.06; },
                max: function (v) { return yHi + (yHi - yLo) * 0.1; } };
  var bars = avg.map(function (v) { return { value: v }; });
  opt.series = [
    { name: '均值', type: 'bar', data: bars, barMaxWidth: 36,
      itemStyle: { color: '#2e5aac', borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: 'top', fontSize: 11, color: '#1a1a2e',
               layout: { hideOverlap: true } } },
    { name: '', type: 'custom', silent: true, data: avg.map(function (v, i) { return [i]; }),
      clip: true,
      renderItem: function (params, api) {
        var i = params.dataIndex;
        var x = api.coord([i, 0])[0];
        var yMin = api.coord([i, mn[i]])[1];
        var yMax = api.coord([i, mx[i]])[1];
        // 横帽宽度固定为 box 宽度的 70%，防止超出类别边界
        var half = Math.max(6, Math.min(12, Math.round(api.size([1,0])[0] * 0.35)));
        var s = { stroke: '#94a3b8', lineWidth: 2 };
        return { type: 'group', children: [
          { type: 'line', shape: { x1: x, y1: yMin, x2: x, y2: yMax }, style: s },
          { type: 'line', shape: { x1: x - half, y1: yMin, x2: x + half, y2: yMin }, style: s },
          { type: 'line', shape: { x1: x - half, y1: yMax, x2: x + half, y2: yMax }, style: s }
        ] };
      }, z: 3 }
  ];
  initChart(id, opt);
}
function stripChart(id, title, sub, cats, vals2d, unit) {
  // 点图（strip plot）：每个点 = 单个项目真实 BOL；短横线 = 工厂均值。
  // 相比柱+I型线：散点自带 y 值，坐标轴范围自动覆盖全部数据（含极值），不会被裁剪。
  var opt = baseOpt(title, sub);
  opt.legend.data = ['项目 BOL', '工厂均值'];
  opt.legend.bottom = 0;
  opt.grid = { left: 62, right: 64, top: sub ? 96 : 74, bottom: 92, containLabel: true };
  opt.xAxis = { type: 'category', data: cats, boundaryGap: true,
                axisLabel: { fontSize: 11, interval: 0, margin: 10, width: 120, overflow: 'truncate' } };
  opt.yAxis = { type: 'value', name: unit || 'BOL (min)', scale: true,
                nameTextStyle: { fontSize: 11 },
                max: function (v) { return v.max * 1.06; },
                min: function (v) { return Math.max(0, v.min - (v.max - v.min) * 0.06); } };
  // 计算均值（供均值横线使用）
  var means = vals2d.map(function (vals) {
    return vals.reduce(function (s, v) { return s + v; }, 0) / vals.length;
  });
  // y 值域的 2% 作为“相近带”：带内相近点横向散开避免重叠（确定性抖动）
  var allV = vals2d.reduce(function (a, b) { return a.concat(b); }, []);
  var yLo = Math.min.apply(null, allV), yHi = Math.max.apply(null, allV);
  var band = (yHi - yLo) * 0.02;
  var pts = [];
  vals2d.forEach(function (vals, i) {
    var vs = vals.slice().sort(function (a, b) { return a - b; });
    var run = 0;  // 相近连续计数
    vs.forEach(function (v, j) {
      if (j > 0 && (v - vs[j - 1]) > band) run = 0; else run++;
      // 交替左右偏移，步进 0.14 类别宽，最大 ±0.28
      var off = run === 0 ? 0 : Math.ceil(run / 2) * 0.14 * (run % 2 ? 1 : -1);
      if (Math.abs(off) > 0.28) off = 0.28 * (off > 0 ? 1 : -1);
      pts.push([i + off, v]);
    });
  });
  opt.series = [
    { name: '项目 BOL', type: 'scatter', symbolSize: 7, clip: true, data: pts,
      itemStyle: { color: 'rgba(46,90,172,.55)', borderColor: '#2e5aac', borderWidth: 1 },
      tooltip: { valueFormatter: function (v) { return v[1] + ' min'; } } },
    { name: '工厂均值', type: 'custom', clip: true, z: 4,
      data: means.map(function (m, i) { return [i, m]; }),
      renderItem: function (params, api) {
        var i = params.dataIndex;
        var x = api.coord([i, api.value(1)])[0];
        var half = api.size([1, 0])[0] * 0.32;
        return { type: 'group', children: [
          { type: 'line', shape: { x1: x - half, y1: api.coord([i, api.value(1)])[1],
                                   x2: x + half, y2: api.coord([i, api.value(1)])[1] },
            style: { stroke: '#e07a5f', lineWidth: 3 } },
          { type: 'text',
            style: { x: x + half + 4, y: api.coord([i, api.value(1)])[1],
                     text: api.value(1).toFixed(1), fontSize: 10,
                     fill: '#b3552f', verticalAlign: 'middle' } }
        ] };
      } }
  ];
  initChart(id, opt);
}
function kpiUpdateChart(id, title, sub, plants, vals, cmc) {
  // BOL 年度更新率：垂直柱形图；工厂降序 + CMC 区域汇总独立系列固定最右（stack 占位同位显示）
  var hasCmc = cmc != null;
  var cats = plants.concat(hasCmc ? ['CMC'] : []);
  if (!cats.length) return;
  var opt = baseOpt(title, sub, { bottom: 44 });
  opt.grid = { left: 48, right: 24, top: sub ? 84 : 62, bottom: 44, containLabel: true };
  opt.xAxis = { type: 'category', data: cats,
                axisLabel: { fontSize: 11, interval: 0, margin: 10 } };
  opt.yAxis = { type: 'value', min: 0, max: 100,
                axisLabel: { formatter: '{value}%', fontSize: 10, color: '#6b7280' } };
  opt.series = [
    { name: '工厂', type: 'bar', stack: 'rate', barMaxWidth: 30,
      data: vals.concat(hasCmc ? [null] : []),
      itemStyle: { color: '#2e5aac', borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: 'top', fontSize: 11, color: '#374151', formatter: '{c}%',
               layout: { hideOverlap: true } } },
    { name: 'CMC 区域汇总', type: 'bar', stack: 'rate', barMaxWidth: 30,
      data: plants.map(function () { return null; }).concat(hasCmc ? [cmc] : []),
      itemStyle: { color: '#8e44ad', borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: 'top', fontSize: 11, fontWeight: 600, color: '#6b21a8',
               formatter: '{c}%', layout: { hideOverlap: true } } }
  ];
  initChart(id, opt);
}
function kpiTargetChart(id, title, sub, plants, vals, cmc, target) {
  // BOL 降低率 vs 改善目标：达成(绿)/未达成(红)双系列 + 琥珀虚线目标线；CMC 置尾
  var hasCmc = cmc != null;
  var cats = plants.concat(hasCmc ? ['CMC'] : []);
  if (!cats.length) return;
  var all = vals.concat(hasCmc ? [cmc] : []);
  var hit = all.map(function (v) { return v != null && v >= target ? v : null; });
  var miss = all.map(function (v) { return v != null && v < target ? v : null; });
  var opt = baseOpt(title, sub, { bottom: 44 });
  opt.grid = { left: 48, right: 24, top: sub ? 84 : 62, bottom: 44, containLabel: true };
  opt.xAxis = { type: 'category', data: cats,
                axisLabel: { fontSize: 11, interval: 0, margin: 10 } };
  opt.yAxis = { type: 'value', min: 0,
                axisLabel: { formatter: '{value}%', fontSize: 10, color: '#6b7280' } };
  opt.series = [
    { name: '达成（≥' + target + '%）', type: 'bar', stack: 'rate', barMaxWidth: 30, data: hit,
      itemStyle: { color: '#27ae60', borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: 'top', fontSize: 11, color: '#065f46', layout: { hideOverlap: true } },
      markLine: { silent: true, symbol: 'none',
                  lineStyle: { color: '#f59e0b', type: 'dashed', width: 2 },
                  label: { formatter: '改善目标 ' + target + '%', fontSize: 10, color: '#b45309',
                           position: 'insideEndTop' },
                  data: [{ yAxis: target }] } },
    { name: '未达成', type: 'bar', stack: 'rate', barMaxWidth: 30, data: miss,
      itemStyle: { color: '#e07a5f', borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: 'top', fontSize: 11, color: '#9a3412', layout: { hideOverlap: true } } }
  ];
  initChart(id, opt);
}
function kpiCaptureChart(id, title, sub, plants, vals, cmc) {
  // ACT CT 抓取率：水平条形图；工厂升序（自下而上递增）+ CMC 区域汇总固定最上
  var hasCmc = cmc != null;
  var cats = plants.concat(hasCmc ? ['CMC'] : []);
  if (!cats.length) return;
  var opt = baseOpt(title, sub, { bottom: 44 });
  opt.grid = { left: 52, right: 64, top: sub ? 84 : 62, bottom: 44, containLabel: true };
  opt.xAxis = { type: 'value', min: 0, max: 100,
                axisLabel: { formatter: '{value}%', fontSize: 10, color: '#6b7280' } };
  opt.yAxis = { type: 'category', data: cats, boundaryGap: true,
                axisLabel: { fontSize: 11, margin: 10 } };
  opt.series = [
    { name: '工厂', type: 'bar', stack: 'ct', barMaxWidth: 16,
      data: vals.concat(hasCmc ? [null] : []),
      itemStyle: { color: '#2e5aac', borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', fontSize: 11, color: '#374151', formatter: '{c}%' } },
    { name: 'CMC 区域汇总', type: 'bar', stack: 'ct', barMaxWidth: 16,
      data: plants.map(function () { return null; }).concat(hasCmc ? [cmc] : []),
      itemStyle: { color: '#8e44ad', borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', fontSize: 11, fontWeight: 600, color: '#6b21a8',
               formatter: '{c}%' } }
  ];
  initChart(id, opt);
}
function hoursChart(id, title, sub, plants, budget, target, achievable) {
  // 三工时哑铃图：Budget=黑色横线[48,4]、改善目标=绿色圆点10、Achievable=浅蓝三角9，相邻指标连线
  if (!plants.length) return;
  function pts(arr) {
    var out = [];
    arr.forEach(function (v, i) { if (v != null) out.push([i, v]); });
    return out;
  }
  var segs = [];
  plants.forEach(function (p, i) {
    var seq = [budget[i], target[i], achievable[i]];
    for (var k = 0; k < seq.length - 1; k++) {
      if (seq[k] != null && seq[k + 1] != null) segs.push([i, seq[k], seq[k + 1]]);
    }
  });
  var opt = baseOpt(title, sub, { bottom: 46 });
  opt.legend.data = ['Budget 工时', '改善目标工时', 'Achievable 工时'];
  opt.grid = { left: 72, right: 44, top: sub ? 84 : 62, bottom: 46, containLabel: true };
  opt.xAxis = { type: 'category', data: plants,
                axisLabel: { fontSize: 12, interval: 0, margin: 10 } };
  opt.yAxis = { type: 'value', name: '工时（小时）', scale: true,
                nameTextStyle: { fontSize: 11 },
                axisLabel: { fontSize: 10, color: '#6b7280' } };
  opt.tooltip = { trigger: 'item', confine: true, textStyle: { fontSize: 12 },
                  extraCssText: 'max-width:360px;white-space:normal;',
                  formatter: function (p) {
                    var i = p.data[0];
                    function fmt(v) { return v == null ? '无数据' : v.toLocaleString() + ' h'; }
                    return '<b>' + plants[i] + '</b> · 三工时年化汇总<br/>' +
                           'Budget 工时: <b>' + fmt(budget[i]) + '</b><br/>' +
                           '改善目标工时: <b>' + fmt(target[i]) + '</b><br/>' +
                           'Achievable 工时: <b>' + fmt(achievable[i]) + '</b>';
                  } };
  function sc(name, data, color, symbol, size, border) {
    return { name: name, type: 'scatter', z: 5, symbol: symbol, symbolSize: size,
             itemStyle: { color: color, borderColor: '#ffffff', borderWidth: border },
             data: data };
  }
  opt.series = [
    { name: '对比连线', type: 'custom', z: 3, silent: true,
      renderItem: function (params, api) {
        var x = api.value(0);
        var p1 = api.coord([x, api.value(1)]);
        var p2 = api.coord([x, api.value(2)]);
        return { type: 'line', shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] },
                 style: { stroke: '#94a3b8', lineWidth: 2, lineCap: 'round', opacity: 0.7 } };
      }, data: segs },
    sc('Budget 工时', pts(budget), '#1a1a2e', 'rect', [48, 4], 0),
    sc('改善目标工时', pts(target), '#10b981', 'circle', 10, 1.5),
    sc('Achievable 工时', pts(achievable), '#38bdf8', 'triangle', 9, 1.5)
  ];
  initChart(id, opt);
}
function rankBarChart(id, title, sub, cats, vals, color, isDrop, tips) {
  // 排名水平条形图（TOP10 环比类）：cats 已按 rank1 置顶排序；tips 为每行 tooltip HTML
  if (!cats.length) return;
  var opt = baseOpt(title, sub, { legend: false, bottom: 36 });
  opt.grid = { left: 8, right: 78, top: sub ? 84 : 62, bottom: 36, containLabel: true };
  opt.xAxis = { type: 'value',
                axisLabel: { formatter: '{value}%', fontSize: 10, color: '#6b7280' } };
  opt.yAxis = { type: 'category', data: cats,
                axisLabel: { fontSize: 11, color: '#374151' } };
  if (tips) {
    opt.tooltip = { trigger: 'item', confine: true, textStyle: { fontSize: 12 },
                    extraCssText: 'max-width:360px;white-space:normal;',
                    formatter: function (p) { return tips[p.dataIndex] || ''; } };
  }
  opt.series = [{ type: 'bar', barMaxWidth: 18,
    itemStyle: { color: color, borderRadius: isDrop ? [3, 0, 0, 3] : [0, 3, 3, 0] },
    label: { show: true, position: isDrop ? 'left' : 'right', fontSize: 11, color: '#374151',
             formatter: function (p) { return (p.value > 0 ? '+' : '') + p.value + '%'; } },
    data: vals }];
  initChart(id, opt);
}
function devDumbbellChart(id, title, sub, labels, devs, stds, acts, devPcts) {
  // ACT vs Std 哑铃图：Std 点落在 0 基准线，ACT 点落在差值处；连线红=偏高/绿=偏低
  if (!labels.length) return;
  var vMin = Math.min.apply(null, [0].concat(devs));
  var vMax = Math.max.apply(null, [0].concat(devs));
  var pad = (vMax - vMin) * 0.15 || Math.max(1, Math.abs(vMax) * 0.05);
  var opt = baseOpt(title, sub, { bottom: 96 });
  opt.legend.data = ['Std（基准 0）', 'ACT（差值）'];
  opt.grid = { left: 66, right: 30, top: sub ? 84 : 62, bottom: 96, containLabel: true };
  opt.xAxis = { type: 'category', data: labels,
                axisLabel: { fontSize: 10, color: '#6b7280', rotate: 42, interval: 0,
                             margin: 12, width: 150, overflow: 'truncate' } };
  opt.yAxis = { type: 'value', name: '差值 ACT − Std（秒）', min: Math.floor(vMin - pad),
                max: Math.ceil(vMax + pad), nameTextStyle: { fontSize: 11 },
                axisLabel: { fontSize: 10, color: '#6b7280' } };
  opt.tooltip = { trigger: 'item', confine: true, textStyle: { fontSize: 12 },
                  extraCssText: 'max-width:360px;white-space:normal;',
                  formatter: function (p) {
                    var i = p.data[0];
                    return '<b>' + labels[i] + '</b><br/>' +
                           'Std: <b>' + stds[i] + ' s</b> · ACT: <b>' + acts[i] + ' s</b><br/>' +
                           '偏差: <b style="color:' + (devs[i] > 0 ? '#e07a5f' : '#27ae60') + '">' +
                           (devs[i] > 0 ? '+' : '') + devs[i] + ' s（' + (devPcts[i] > 0 ? '+' : '') +
                           devPcts[i] + '%）</b>' +
                           (devs[i] > 0 ? '，偏高（慢于标准）' : '，偏低（快于标准，标准存在收紧机会）');
                  } };
  opt.series = [
    { name: '偏差连线', type: 'custom', z: 3,
      renderItem: function (params, api) {
        var x = api.value(0);
        var p1 = api.coord([x, 0]);
        var p2 = api.coord([x, api.value(1)]);
        var over = api.value(1) > 0;
        return { type: 'line', shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] },
                 style: { stroke: over ? '#e07a5f' : '#27ae60', lineWidth: 2.5, lineCap: 'round' } };
      },
      data: labels.map(function (l, i) { return [i, devs[i]]; }) },
    { name: 'Std（基准 0）', type: 'scatter', z: 5, symbolSize: 9,
      itemStyle: { color: '#94a3b8', borderColor: '#ffffff', borderWidth: 1 },
      data: labels.map(function (l, i) { return [i, 0]; }) },
    { name: 'ACT（差值）', type: 'scatter', z: 5, symbolSize: 10,
      itemStyle: { color: '#2e5aac', borderColor: '#ffffff', borderWidth: 1 },
      data: labels.map(function (l, i) { return [i, devs[i]]; }) }
  ];
  initChart(id, opt);
}
function sctActChart(id, title, sub, labels, scts, acts, gapPcts) {
  // 按工厂 SCT vs ACT 分组柱形图；|Gap%|>20% 的类目标红色加粗提示
  if (!labels.length) return;
  var opt = baseOpt(title, sub, { bottom: 96 });
  opt.grid = { left: 56, right: 24, top: sub ? 84 : 62, bottom: 96, containLabel: true };
  opt.xAxis = { type: 'category', data: labels,
                axisLabel: { fontSize: 10, interval: 0, margin: 12,
                             rotate: labels.length > 6 ? 38 : 0,
                             width: 140, overflow: 'truncate',
                             color: function (value, idx) {
                               return Math.abs(gapPcts[idx]) > 20 ? '#e74c3c' : '#6b7280';
                             },
                             fontWeight: function (value, idx) {
                               return Math.abs(gapPcts[idx]) > 20 ? 'bold' : 'normal';
                             } } };
  opt.yAxis = { type: 'value', name: 'CT (s)', scale: true, nameTextStyle: { fontSize: 11 },
                axisLabel: { fontSize: 10, color: '#6b7280' } };
  opt.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true,
                  textStyle: { fontSize: 12 },
                  extraCssText: 'max-width:360px;white-space:normal;',
                  formatter: function (params) {
                    var i = params[0].dataIndex;
                    return '<b>' + labels[i] + '</b><br/>' +
                           'SCT: ' + scts[i] + ' s · ACT: ' + acts[i] + ' s<br/>' +
                           'Gap: <b style="color:' + (gapPcts[i] > 0 ? '#27ae60' : '#e74c3c') + '">' +
                           (gapPcts[i] > 0 ? '+' : '') + gapPcts[i] + '%</b>' +
                           (gapPcts[i] > 0 ? '（ACT 快于标准，标准收紧机会）'
                                           : (Math.abs(gapPcts[i]) > 20 ? ' ⚠️ 实测明显慢于标准' : ''));
                  } };
  var showLbl = labels.length <= 12;
  function bs(name, data, color) {
    return { name: name, type: 'bar', data: data, barMaxWidth: 22,
             itemStyle: { color: color, borderRadius: [3, 3, 0, 0] },
             label: showLbl ? { show: true, position: 'top', fontSize: 10, color: '#374151',
                                layout: { hideOverlap: true } } : undefined };
  }
  opt.series = [bs('SCT', scts, '#94a3b8'), bs('ACT', acts, '#2e5aac')];
  initChart(id, opt);
}
function initChart(domId, opt) {
  var el = document.getElementById(domId);
  if (!el) return null;
  var chart = echarts.init(el);
  chart.setOption(opt);
  window.addEventListener('resize', function () { chart.resize(); });
  return chart;
}
"""

CONF_HIGH = '<span class="tag tag-best">高可信</span>'
CONF_MID = '<span class="tag tag-warn">中可信</span>'

_ECH = None


def _echarts_js():
    global _ECH
    if _ECH is None:
        _ECH = _load_echarts()
    return _ECH


def page(title, body, extra_js=''):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
{body}
</div>
<script>{_echarts_js()}</script>
<script>{JS_CHART}</script>
<script>
{extra_js}
</script>
</body>
</html>
"""


# ════════════════════════════════════════════════════════════════
# 季度报告
# ════════════════════════════════════════════════════════════════
WARN_DIV = ('<div style="margin-top:4px;padding:3px 6px;border-left:3px solid #f59e0b;'
            'background:rgba(245,158,11,.1);color:#92400e;font-size:11px">'
            '⚠ 数据异常提示：两次数据接近 2 倍关系（疑似漏提交或重复提交），请核实提交规范性</div>')


def _near_double(a, b):
    """接近 2 倍关系（比值 1.8~2.2）→ 疑似漏提交/重复提交（与前端 nearDoubleAnomaly 口径一致）"""
    if not a or not b or a <= 0 or b <= 0:
        return False
    ratio = a / b if a > b else b / a
    return 1.8 <= ratio <= 2.2


def build_quarter(Q):
    P = []
    js_parts = []
    fs = Q['approval_factory']
    appr_this = sum(fs['this'].values())
    appr_prev = sum(fs['prev'].values())
    lb_rate = Q['low_lb_count'] / Q['low_lb_total_projects'] * 100 if Q['low_lb_total_projects'] else 0
    deltas = [c['delta'] for c in Q['bol_changes'] if c['delta'] is not None]
    avg_d = sum(deltas) / len(deltas) if deltas else 0
    YL, TL, QL = Q['yoy_label'], Q['prev_label'], Q['this_label']
    yr, qr = Q['year'], Q['quarter']
    down_cnt = sum(1 for d in deltas if d < 0)
    up_cnt = sum(1 for d in deltas if d > 0)

    # 提报主力工厂（按本季审批数 Top3，动态计算）
    top3 = sorted(fs['this'].items(), key=lambda kv: -kv[1])[:3]
    top3_txt = '、'.join(f'{pcn(p)}（{c} 项）' for p, c in top3 if c > 0)
    top3_pct = round(sum(c for _, c in top3) / appr_this * 100) if appr_this else 0

    P.append(f"""
<div class="report-header">
  <h1>BOL 季度分析报告 · {yr} Q{qr}</h1>
  <div class="subtitle">KPI 总览 · BOL 变更动态 · 实测 CT 分析 · 数据洞察与改善建议 | 数据范围：{Q['qs']} ~ {Q['qe']}（完整自然季度）</div>
  <div class="meta">数据来源：IE KPI月度（HRDB）· 动态BOL审批记录（HRDB）· 实测CT瓶颈（HRDB）· 预算BOL/改善目标（CMC）· 高BOL跟踪（CMC） | 生成日期：{Q['gen_date']} | 分发对象：各工厂 IE / 生产管理</div>
</div>""")

    # ── 一、BOL KPI 总览 ──
    kpis = Q.get('ame_kpis') or {}
    upd = kpis.get('BOL Updates Rate') or {}
    red = kpis.get('BOL Reduction Rate') or {}
    cap = kpis.get('Acutal CT Rate') or {}
    kpi_month = upd.get('month') or red.get('month') or cap.get('month') or ''
    upd_month = upd.get('month')
    red_month = red.get('month')
    cap_month = cap.get('month')
    upd_items = sorted((upd.get('by_plant') or {}).items(), key=lambda kv: -kv[1])
    red_items = sorted((red.get('by_plant') or {}).items(), key=lambda kv: -kv[1])
    cap_items = sorted((cap.get('by_plant') or {}).items(), key=lambda kv: kv[1])
    imp_h = Q.get('improve_hours') or []
    imp_sorted = sorted(imp_h,
                        key=lambda x: -(x.get('budget') or x.get('target') or x.get('achievable') or 0))
    tot_b = sum(x['budget'] for x in imp_h if x.get('budget'))
    tot_t = sum(x['target'] for x in imp_h if x.get('target'))
    tot_a = sum(x['achievable'] for x in imp_h if x.get('achievable'))
    saving = round(tot_b - tot_a, 1) if tot_b and tot_a else None
    saving_pct = round((tot_b - tot_a) / tot_b * 100, 1) if tot_b and tot_a else None
    red_hit = [p for p, v in red_items if v >= 5.4]

    kpi_bullets = []
    if upd_items:
        kpi_bullets.append(
            f"<b>BOL 年度更新率</b>：{pcn(upd_items[0][0])} 最高（{upd_items[0][1]}%）、"
        f"{pcn(upd_items[-1][0])} 最低（{upd_items[-1][1]}%），五厂简单平均 {upd.get('avg_pct', 0)}%"
        + (f"，CMC 官方区域汇总 {upd.get('cmc_pct')}%。" if upd.get('cmc_pct') is not None else '。'))
    if red_items:
        hit_txt = '、'.join(f'{pcn(p)} {v}%' for p, v in red_items if v >= 5.4) or '无'
        miss_txt = '、'.join(f'{pcn(p)} {v}%' for p, v in red_items if v < 5.4)
        kpi_bullets.append(
        f"<b>BOL 降低率</b>：CMC 官方区域汇总 {red.get('cmc_pct', '—')}%（目标 5.4%），"
        f"五厂简单平均 {red.get('avg_pct', 0)}%；达成工厂：{hit_txt}"
        + (f"；未达成：{miss_txt}，需加大 BOL 改善力度。" if miss_txt else '。'))
    if cap_items:
        kpi_bullets.append(
            f"<b>ACT CT 抓取率</b>：{pcn(cap_items[-1][0])} 最高（{cap_items[-1][1]}%）、"
        f"{pcn(cap_items[0][0])} 最低（{cap_items[0][1]}%），五厂简单平均 {cap.get('avg_pct', 0)}%；"
        f"CMC 官方区域汇总 {cap.get('cmc_pct', '—')}%；"
            f"抓取率偏低的工厂需加强产线实测数据采集。")
    if saving is not None:
        kpi_bullets.append(
            f"<b>三工时对比</b>：Budget 合计 {tot_b:,.0f} h，改善目标合计 {tot_t:,.0f} h，"
            f"Achievable 合计 {tot_a:,.0f} h；Budget → Achievable 改善空间 <b>{saving:,.0f} h（{saving_pct}%）</b>。")

    P.append(f"""
<div class="section">
  <h2>一、BOL KPI 总览</h2>
  <div class="stat-row">
    <div class="stat-card"><div class="num">{f"{upd['cmc_pct']:.1f}%" if upd.get('cmc_pct') is not None else '—'}</div><div class="label">BOL 年度更新率（CMC 官方区域汇总{f' · {upd_month}月' if upd_month else ''}）</div></div>
    <div class="stat-card"><div class="num {'green' if red.get('cmc_pct', 0) >= 5.4 else 'red'}">{f"{red['cmc_pct']:.2f}%" if red.get('cmc_pct') is not None else '—'}</div><div class="label">BOL 降低率（CMC 官方区域汇总{f' · {red_month}月' if red_month else ''} · 工厂达成 {len(red_hit)}/{len(red_items)} · 目标 5.4%）</div></div>
    <div class="stat-card"><div class="num">{f"{cap['cmc_pct']:.1f}%" if cap.get('cmc_pct') is not None else '—'}</div><div class="label">ACT CT 抓取率（CMC 官方区域汇总{f' · {cap_month}月' if cap_month else ''}）</div></div>
    <div class="stat-card"><div class="num green">{f'{saving:,.0f} h' if saving is not None else '—'}</div><div class="label">三工时改善空间（ΣBudget − ΣAchievable{f' · {saving_pct}%' if saving_pct is not None else ''}）</div></div>
  </div>
  <h3>1.1 BOL 年度更新率（{yr} 官方 KPI{f' · {kpi_month}月' if kpi_month else ''}）</h3>
  <div class="chart-box sm" id="c-kpi-upd"></div>
  <div class="chart-legend-hint">数据源：HRDB CN_AME_KPI_monthlyHistory（BOL Updates Rate）；紫色柱 = CMC 区域汇总值。</div>
  <h3>1.2 各工厂达成率（vs 改善目标 5.4%）</h3>
  <div class="chart-box sm" id="c-kpi-red"></div>
  <div class="chart-legend-hint">数据源：HRDB BOL Reduction Rate（{red_month or '—'}月）；工厂柱为工厂值，CMC 置尾为官方区域汇总；绿 = 达成（≥5.4%）、红 = 未达成；琥珀虚线 = 改善目标 5.4%。</div>
  <h3>1.3 ACT CT 抓取率（按工厂）</h3>
  <div class="chart-box sm" id="c-kpi-cap"></div>
  <div class="chart-legend-hint">数据源：HRDB Acutal CT Rate（{cap_month or '—'}月）；自下而上递增排列；紫色条 = CMC 官方区域汇总值。</div>
  <h3>1.4 改善目标对比 · 各工厂三工时汇总</h3>
  <div class="chart-box" id="c-kpi-hours"></div>
  <div class="chart-legend-hint">■ 黑色横线 = Budget 工时 · ● 绿点 = 改善目标工时 · ▲ 浅蓝三角 = Achievable 工时（年化小时）；悬停查看各工厂三工时明细。</div>
  <div class="insight-box">
    <b>KPI 状态解读：</b>
    <ul class="summary-list">
      {''.join(f'<li>{b}</li>' for b in kpi_bullets) or '<li>暂无官方 KPI 月度数据。</li>'}
    </ul>
  </div>
</div>""")

    # 模块一图表 JS
    if upd_items:
        js_parts.append(
            f"kpiUpdateChart('c-kpi-upd', 'BOL 年度更新率', "
            f"'BOL Updates Rate · 柱值 = 年度更新率（官方 KPI{kpi_month}月）· CMC 为区域汇总', "
            f"{jd([pcn(p) for p, _ in upd_items])}, {jd([v for _, v in upd_items])}, {jd(upd.get('cmc_pct'))});")
    if red_items:
        js_parts.append(
            f"kpiTargetChart('c-kpi-red', '各工厂达成率（vs 改善目标 5.4%）', "
          f"'BOL Reduction Rate · {red_month or '—'}月官方KPI · 琥珀虚线为目标线 · ≥5.4% 为达成 · CMC 置尾', "
            f"{jd([pcn(p) for p, _ in red_items])}, {jd([v for _, v in red_items])}, "
            f"{jd(red.get('cmc_pct'))}, 5.4);")
    if cap_items:
        js_parts.append(
            f"kpiCaptureChart('c-kpi-cap', 'ACT CT 抓取率（按工厂）', "
          f"'Acutal CT Rate · {cap_month or '—'}月官方KPI · 自下而上递增 · CMC 区域汇总置顶', "
            f"{jd([pcn(p) for p, _ in cap_items])}, {jd([v for _, v in cap_items])}, {jd(cap.get('cmc_pct'))});")
    if imp_sorted:
        js_parts.append(
            f"hoursChart('c-kpi-hours', '改善目标对比 · 各工厂三工时汇总', "
            f"'按 Budget 工时降序 · 年化小时（volume × BOL / 60）', "
            f"{jd([pcn(x['plant']) for x in imp_sorted])}, {jd([x.get('budget') for x in imp_sorted])}, "
            f"{jd([x.get('target') for x in imp_sorted])}, {jd([x.get('achievable') for x in imp_sorted])});")

    # ── 二、BOL变更动态 ──
    # 本季三个月份（月度趋势仅显示最近一个季度）
    qm_list = [f'{yr}-{3 * (qr - 1) + i + 1:02d}' for i in range(3)]
    qm_cnt = [next((m['cnt'] for m in Q['approval_monthly'] if m['ym'] == ym), 0)
              for ym in qm_list]
    plants_all = sorted(set(fs['this']) | set(fs['prev']) | set(fs['yoy']),
                        key=lambda p: -fs['this'].get(p, 0))
    # 降幅前三位（动态）
    drops = sorted([c for c in Q['bol_changes'] if c['delta'] is not None and c['delta'] < 0],
                   key=lambda x: x['delta'])[:3]
    drop_txt = '、'.join(
        f"{pcn(c['plant'])} {c['program']}（{c['name'] or ''}，{c['process']}）{c['delta']:.2f} min"
        for c in drops) if drops else '本季无下降版本'
    n_new = len(Q['bol_changes']) - len(deltas)
    P.append(f"""
<div class="section">
  <h2>二、BOL 变更动态</h2>
  <h3>2.1 月度审批趋势（{QL}）</h3>
  <div class="chart-box sm" id="c-monthly"></div>
  <div class="chart-legend-hint">柱值 = 当月审批通过的 BOL 变更项数（项目×工艺）；{QL} 合计 {appr_this} 项（{TL} {appr_prev} 项，{('改善' if appr_this >= appr_prev else '回落') if appr_this or appr_prev else ''}）。</div>
  <h3>2.2 各工厂审批分布（环比 / 同比）</h3>
  <div class="chart-box sm" id="c-factory"></div>
  <div class="chart-legend-hint">按 {QL} 审批量降序排列；0 表示该季无审批记录。</div>
  <div class="insight-box">
    {top3_txt} 为本季提报主力，合计占 {top3_pct}%；其余工厂提报节奏需关注。
  </div>
  <h3>2.3 TOP10 对比分析（本季提交口径）</h3>""")
    # TOP10 四图（审批BOL vs QWS 报价 / 与上次审批环比 × 上升/下降）
    tc = Q.get('top_compare') or {}
    tc_defs = [
        ('qws', 'drop', 'c-tc-qws-drop', '审批 BOL vs QWS 报价 · 下降 TOP10',
         '绿 = 审批 BOL 低于报价（改善）· (BOL − QWS) / QWS'),
        ('qws', 'rise', 'c-tc-qws-rise', '审批 BOL vs QWS 报价 · 上升 TOP10',
         '红 = 审批 BOL 高于报价（不利）· (BOL − QWS) / QWS'),
        ('mom', 'drop', 'c-tc-mom-drop', '与上次审批环比 · 下降 TOP10',
         '绿 = 最新 BOL 较上次变小（改善）· (最新 − 上次) / 上次'),
        ('mom', 'rise', 'c-tc-mom-rise', '与上次审批环比 · 上升 TOP10',
         '红 = 最新 BOL 较上次变大（变差）· (最新 − 上次) / 上次'),
    ]

    def _tc_tip(r, mode):
        b = r['qws'] if mode == 'qws' else r['prev']
        bname = 'QWS 报价' if mode == 'qws' else '上次 BOL'
        return (f"<b>{esc(plabel(r['program'], r.get('name'), '/' + r['process']))}</b>（{pcn(r['plant'])}）<br>"
                f"{esc(r['name'] or '')}<br>本季 BOL: <b>{r['bol']:.2f}</b> min · "
                f"{bname}: <b>{b:.2f}</b> min<br>变化: <b>{r['change_pct']:+.1f}%</b>"
                + (WARN_DIV if r.get('anomaly') else ''))

    for mode, direction, div_id, title, sub in tc_defs:
        rows_tc = (tc.get(mode) or {}).get(direction) or []
        if rows_tc:
            P.append(f"""
  <div class="chart-box sm" id="{div_id}"></div>
  <div class="chart-legend-hint">{sub} · 口径：{QL} 提交审批数据（项目+工艺去重取最新）· ⚠ 疑似提交异常。</div>""")
            lst = rows_tc[::-1]   # rank1 置顶
            cats_tc = [f"{plabel(r['program'], r.get('name'), '/' + r['process'])}{' ⚠' if r.get('anomaly') else ''}"
                       for r in lst]
            vals_tc = [r['change_pct'] for r in lst]
            tips_tc = [_tc_tip(r, mode) for r in lst]
            color = '#27ae60' if direction == 'drop' else '#e07a5f'
            js_parts.append(
                f"rankBarChart('{div_id}', '{title}', '{sub}', {jd(cats_tc)}, {jd(vals_tc)}, "
                f"'{color}', {str(direction == 'drop').lower()}, {jd(tips_tc)});")
        else:
            P.append(f"""
  <div class="empty-box">本季无「{title}」数据。</div>""")
    anom_cnt = tc.get('anomaly_count') or 0
    if anom_cnt:
        P.append(f"""
  <div class="warn-box">
    <b>提交规范性预警：</b>TOP10 对比中发现 <b>{anom_cnt} 组</b>数据接近 2 倍关系（已在图表类目与悬浮提示中以 ⚠ 标注），疑似过程漏提交或重复提交，请相关工厂核实提交口径。
  </div>""")
    P.append(f"""
  <h3>2.4 本季 BOL 版本变化明细</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>项目</th><th>工厂</th><th>工艺</th><th>产线</th><th>当前BOL (min)</th><th>较上一版本</th><th>审批日期</th></tr></thead>
    <tbody>""")
    for c in sorted(Q['bol_changes'], key=lambda x: (x['delta'] is None, x['delta'] or 0)):
        nm = c['name'] or c['program']
        if c['delta'] is None:
            dv = '<span class="tag tag-small">首版录入</span>'
        elif c['delta'] < 0:
            dv = f'<span class="delta-down">▼ {abs(c["delta"]):.2f}</span>'
        else:
            dv = f'<span class="delta-up">▲ {c["delta"]:.2f}</span>'
        P.append(f"<tr><td class='lft'>{esc(nm)}<br><span style='color:#6b7280;font-size:.78rem'>{esc(c['program'])}</span></td>"
                 f"<td>{pcn(c['plant'])}</td><td>{esc(c['process'])}</td><td>{esc(c['line'])}</td>"
                 f"<td>{c['bol']:.2f}</td><td>{dv}</td><td>{c['date']}</td></tr>")
    # LB KPI 趋势数据准备（2.5）
    kpi = Q['kpi_lb']
    yms = Q['lb_trend_months']
    last_ym = yms[-1] if yms else ''
    lb_last = {k['plant']: k['v'] for k in kpi if k['ym'] == last_ym}
    lb_bullets = []
    ok_plants = [p for p in MAIN_PLANTS if (lb_last.get(p) or 0) * 100 >= 85]
    if ok_plants:
        lb_bullets.append(f"<b>{('、'.join(pcn(p) for p in ok_plants))}（"
                          + '、'.join(f"{(lb_last[p] or 0) * 100:.1f}%" for p in ok_plants)
                          + "）达标（≥85%）</b>。")
    for p in MAIN_PLANTS:
        vals = [next((k['v'] for k in kpi if k['ym'] == ym and k['plant'] == p), None) for ym in yms]
        vv = [v for v in vals if v is not None]
        if len(vv) >= 2:
            chg = (vv[-1] - vv[0]) * 100
            arrow = '改善' if chg > 0 else ('下滑' if chg < 0 else '持平')
            lb_bullets.append(f"{pcn(p)}：{vv[0] * 100:.1f} → {vv[-1] * 100:.1f}%（{chg:+.1f}pp，{arrow}）。")
    # 低LB改善机会数据准备（2.6）
    agg = Q['low_lb_agg_by_plant']
    agg_main = {p: v for p, v in agg.items() if p != 'CMC'}
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>环比结论（BOL 变小 = 改善 / 变大 = 变差）：</b>{len(deltas)} 项版本刷新中 <b>{down_cnt} 项下降（改善）、{up_cnt} 项上升（变差）</b>（平均 {'−' if avg_d < 0 else '+'}{abs(avg_d):.2f} min）。降幅前三位：{drop_txt}；其余 {n_new} 项为新项目首版录入，将于后续季度产生版本对比。
  </div>
  <h3>2.5 线平衡率（LB）KPI 趋势（近 3 月）</h3>
  <div class="chart-box sm" id="c-lb"></div>
  <div class="chart-legend-hint">数据源：IE KPI 月度（kpi_name='LB'）；红色虚线 = 85% 目标线；线端标注工厂名与最新值，其余数值见悬浮提示。</div>
  <div class="insight-box">
    <b>LB 改善情况：</b>
    <ul class="summary-list">
      {''.join(f'<li>{b}</li>' for b in lb_bullets) or '<li>暂无 LB KPI 月度数据。</li>'}
    </ul>
  </div>
  <h3>2.6 低 LB 改善机会（LB &lt; 85%）</h3>
  <div class="chart-box sm" id="c-lowlb"></div>
  <div class="chart-legend-hint">柱值 = 各工厂 LB&lt;85% 的项目数（提交审批数据口径）；理论上平衡率越低，改善空间越大。</div>
  <h3>2.6.1 改善机会 Top12（按 LB 升序）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>项目</th><th>工厂</th><th>工艺</th><th>产线</th><th>LB</th><th>瓶颈工位</th><th>数据时点</th></tr></thead>
    <tbody>""")
    for x in Q['low_lb_top12']:
        nm = x['name'] or x['program']
        tag = 'tag-hot' if x['lb_pct'] < 60 else 'tag-warn'
        P.append(f"<tr><td class='lft'>{esc(nm)}<br><span style='color:#6b7280;font-size:.78rem'>{esc(x['program'])} · {esc(x['line'])}</span></td>"
                 f"<td>{pcn(x['plant'])}</td><td>{esc(x['process'])}</td><td>{esc(x['line'])}</td>"
                 f"<td><span class='tag {tag}'>{x['lb_pct']:.1f}%</span></td><td>{esc(x['bn_station'])}</td>"
                 f"<td>{x['ut']}</td></tr>")
    lowest = Q.get('lowest_lb_item')
    lowest_txt = ''
    if lowest:
        lowest_txt = (f"最低 LB 为{pcn(lowest['plant'])} {lowest['program']}"
                      f"（{lowest['name'] or ''}，{lowest['process']}）{lowest['lb_pct']:.1f}%。")
    lbp_sorted = sorted(agg_main.items(), key=lambda x: x[1]['count'])
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>机会识别（全量 {Q['low_lb_count']} 个低LB项目，占 {lb_rate:.0f}%）：</b>{lowest_txt}理论上平衡率越低、线平衡改善空间越大；建议优先从 LB 最低的项目入手，通过瓶颈工位优化 / 工位重组 / ECRS 提升产线平衡率，改善完成后及时刷新 BOL 并提报审批。
    <br><span style="color:#6b7280;font-size:.82rem">注：按项目×工艺取最近审批版本；部分项目版本距今较久（见"数据时点"），改善前建议先刷新 BOL 版本复核。</span>
  </div>
</div>""")

    # ── 三、实测 CT 分析 ──
    P.append(f"""
<div class="section">
  <h2>三、实测 CT 分析</h2>
  <h3>3.1 瓶颈CT超标产线 Top10（&gt;120s）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>#</th><th>项目</th><th>工厂</th><th>产线</th><th>瓶颈CT (s)</th><th>超标幅度</th><th>数据时点</th></tr></thead>
    <tbody>""")
    for i, b in enumerate(Q['bn_top15'][:10]):
        over = (b['ct'] - 120) / 120 * 100
        P.append(f"<tr><td>{i + 1}</td><td class='lft'>{esc(b['pn'])} <span style='color:#6b7280'>({esc(b['pc'])})</span></td>"
                 f"<td>{pcn(b['plant'])}</td><td>{esc(b['line'])}</td>"
                 f"<td><b>{b['ct']:.1f}</b></td><td><span class='delta-up'>+{over:.0f}%</span></td>"
                 f"<td>{b['ut'][:10]}</td></tr>")
    gmax = Q['bn_top15'][0] if Q['bn_top15'] else None
    warn_li = []
    if gmax:
        warn_li.append(f"<li><b>{pcn(gmax['plant'])} {gmax['pc']}（{gmax['pn']}，{gmax['line']}）{gmax['ct']:.0f}s</b> = 阈值 {gmax['ct'] / 120:.1f} 倍、本季最高，建议列入专项治理并核查采集口径。</li>")
    P.append(f"""</tbody></table></div>
  <div class="warn-box">
    <b>异常提示（按超标幅度排序，数据异常需相应工厂核查采集口径）：</b>
    <ul class="summary-list">
      {''.join(warn_li) or '<li>本季无超标产线。</li>'}
    </ul>
  </div>
  <h3>3.2 ACT CT 趋势 TOP10 环比（近 3 月均值 vs 前 3 月均值）</h3>""")
    # 3.2 ACT CT 趋势 TOP10（下降=改善 / 上升=恶化）
    ctt = Q.get('ct_trend') or {}
    ctt_mom = ctt.get('mom') or {}
    ctt_periods = ctt.get('periods') or {}
    recent_txt = '、'.join(ctt_periods.get('recent') or [])
    prev_txt = '、'.join(ctt_periods.get('prev') or [])
    ctt_stats = ctt.get('stats') or {}

    def _ct_tip(r):
        warn = WARN_DIV if _near_double(r['recent_avg'], r['base_avg']) else ''
        return (f"<b>{esc(plabel(r['pc'], r.get('pn')))}/{esc(r['line'])}</b>（{pcn(r['plant'])}）<br>"
                f"{esc(r['pn'] or '')}<br>近3月均值: <b>{r['recent_avg']} s</b> · "
                f"前3月均值: <b>{r['base_avg']} s</b><br>"
                f"变化: <b>{r['change_pct']:+.1f}%</b>" + warn)

    ctt_insight = []
    for direction, div_id, color, chart_title, tip_name in [
        ('drop', 'c-ct-drop', '#27ae60', 'ACT CT 趋势 · 下降 TOP10（改善）', '下降'),
        ('rise', 'c-ct-rise', '#e07a5f', 'ACT CT 趋势 · 上升 TOP10（恶化）', '上升'),
    ]:
        rows_ct = ctt_mom.get(direction) or []
        if rows_ct:
            lst = rows_ct[::-1]   # rank1 置顶
            cats_ct = [f"{plabel(r['pc'], r.get('pn'), '/' + r['line'])}{' ⚠' if _near_double(r['recent_avg'], r['base_avg']) else ''}"
                       for r in lst]
            vals_ct = [r['change_pct'] for r in lst]
            tips_ct = [_ct_tip(r) for r in lst]
            P.append(f"""
  <div class="chart-box sm" id="{div_id}"></div>
  <div class="chart-legend-hint">口径：项目×产线粒度，近 3 月均值 vs 前 3 月均值（{prev_txt} → {recent_txt}）· ⚠ 疑似数据异常。</div>""")
            js_parts.append(
                f"rankBarChart('{div_id}', '{chart_title}', "
                f"'近3月均值 vs 前3月均值 · 项目/产线粒度', {jd(cats_ct)}, {jd(vals_ct)}, "
                f"'{color}', {str(direction == 'drop').lower()}, {jd(tips_ct)});")
            top_ct = rows_ct[0]
            ctt_insight.append(
                f"{tip_name}最大：{pcn(top_ct['plant'])} {plabel(top_ct['pc'], top_ct.get('pn'), '/' + top_ct['line'])}"
                f"（{top_ct['recent_avg']}s vs {top_ct['base_avg']}s，{top_ct['change_pct']:+.1f}%）")
        else:
            P.append(f"""
  <div class="empty-box">暂无{tip_name}趋势数据。</div>""")
    if ctt_insight:
        P.append(f"""
  <div class="insight-box">
    <b>趋势结论（{ctt_stats.get('computed', 0)} 个项目×产线完成环比计算）：</b>{'；'.join(ctt_insight)}。实测 CT 上升（恶化）的产线需排查瓶颈工位与采集状态；下降（改善）产线的经验可供跨厂借鉴。
  </div>""")
    # 3.3 ACT vs Std 哑铃图 TOP20
    at = Q.get('act_std_top20') or []
    ass = Q.get('act_std_stats') or {}
    P.append(f"""
  <h3>3.3 ACT vs Std 哑铃图 TOP20（按 |偏差%| 降序）</h3>""")
    if at:
        P.append("""
  <div class="chart-box" id="c-dev"></div>
  <div class="chart-legend-hint">纵轴 = 差值（ACT − Std，秒）· 灰点 = Std 基准（0）· 蓝点 = ACT 差值 · 连线红 = 偏高（慢于标准）/ 绿 = 偏低（快于标准，标准存在收紧机会）。</div>""")
        at_labels = [plabel(r['pc'], r.get('pn'), '/' + r['line']) for r in at]
        at_devs = [r['dev'] for r in at]
        at_stds = [r['std'] for r in at]
        at_acts = [r['act'] for r in at]
        at_pcts = [r['dev_pct'] for r in at]
        js_parts.append(
            f"devDumbbellChart('c-dev', 'ACT vs Std 哑铃图 TOP20（|偏差%|&gt;10%）', "
            f"'按 |偏差%| 降序 · 红 = ACT 高于标准 / 绿 = ACT 低于标准（标准收紧机会）', "
            f"{jd(at_labels)}, {jd(at_devs)}, {jd(at_stds)}, {jd(at_acts)}, {jd(at_pcts)});")
        P.append(f"""
  <div class="insight-box">
    <b>标准 vs 实际：</b>共匹配 {ass.get('matched', 0)} 组 SCT/ACT 对比，其中 {ass.get('over', 0)} 组偏差超过 ±10%（ACT 高于标准 {ass.get('above', 0)} 组 / 低于标准 {ass.get('below', 0)} 组）。ACT 低于标准（ACT&lt;SCT）的项目提示标准工时存在收紧空间（改善机会）；ACT 明显高于标准的项目需核查产线实际状态或标准合理性。
  </div>""")
    else:
        P.append(f"""
  <div class="empty-box">暂无 |偏差%|&gt;10% 的 ACT vs Std 对比数据（共匹配 {ass.get('matched', 0)} 组）。</div>""")
    # 3.4 按工厂 SCT vs ACT 对比（每工厂一图）
    sap = Q.get('sct_act_by_plant') or {}
    sa_plants = sorted(sap.keys())
    sa_summary = []   # (plant, 机会数, 需复核数)
    P.append(f"""
  <h3>3.4 按工厂 SCT vs ACT 对比</h3>
  <div class="chart-legend-hint">每个工厂一张图，按 |Gap%| 降序取前 20 条；Gap = (SCT − ACT) / SCT × 100%，<b>Gap &gt; 0（ACT 快于标准）提示标准收紧机会</b>；Gap &lt; −5%（ACT 超出标准 5% 以上）需分析原因并改善；红色类目 = |Gap%|&gt;20% 需重点复核。</div>""")
    for p in sa_plants:
        d_plant = sap[p] or {}
        items_p = [it for it in (d_plant.get('items') or []) if it.get('gap_pct') is not None][:20]
        act_only = d_plant.get('act_only') or 0
        if not items_p:
            if act_only:
                P.append(f"""
  <div class="empty-box">{pcn(p)}：{act_only} 条实测记录暂无 SCT 匹配（需补充标准工时提报）。</div>""")
            continue
        sa_labels = [plabel(it['pc'], it.get('pn'), '/' + it['line'] + '·' + it['process']) for it in items_p]
        sa_scts = [it['sct'] for it in items_p]
        sa_acts = [it['act'] for it in items_p]
        sa_gaps = [it['gap_pct'] for it in items_p]
        P.append(f"""
  <div class="chart-box sm" id="c-sa-{p}"></div>""")
        js_parts.append(
            f"sctActChart('c-sa-{p}', '{pcn(p)} · SCT vs ACT 对比', "
            f"'共 {len(items_p)} 组（另 {act_only} 条实测无 SCT 匹配）· 按 |Gap%| 降序前 {len(items_p)} 条', "
            f"{jd(sa_labels)}, {jd(sa_scts)}, {jd(sa_acts)}, {jd(sa_gaps)});")
        all_items = d_plant.get('items') or []
        opp_cnt = sum(1 for it in all_items if (it.get('gap_pct') or 0) > 0)
        over5_cnt = sum(1 for it in all_items
                         if it.get('gap_pct') is not None and it['gap_pct'] < -5)
        max_gap = max((it.get('gap_pct') or 0) for it in all_items) if all_items else 0
        sa_summary.append((p, opp_cnt, over5_cnt, len(all_items), max_gap))
    if sa_summary:
        sa_txt = '；'.join(
            f"{pcn(p)}：{o} 组（最大 +{g:.1f}%）" for p, o, _, _, g in sa_summary if o)
        so_txt = '；'.join(
            f"{pcn(p)}：{c} 组" for p, _, c, _, _ in sa_summary if c)
        P.append(f"""
  <div class="insight-box">
    <b>改善机会识别（ACT &lt; SCT，标准存在收紧空间）：</b>{sa_txt or '暂无'}。建议对上述项目复核标准工时（SCT），在下一轮 BOL 更新中收紧标准；同时补充无 SCT 匹配产线的标准提报，扩大可比范围。
    <br><b>实测 CT 治理（ACT 超出 SCT 5% 以上，需分析原因并改善）：</b>{so_txt or '暂无'}。实测明显慢于标准提示产线状态（工艺/设备/瓶颈工位）或标准合理性存在问题，建议逐组分析原因并制定改善措施，改善后复测验证。
  </div>""")
    P.append("""
</div>""")

    # ── 四、数据洞察与改善建议 ──
    # 跨模块汇总：SCT 收紧机会数（ACT<SCT）、实测CT治理数（ACT>SCT 5%）、BOL 环比改善/变差项数（按工厂）
    sap_all = Q.get('sct_act_by_plant') or {}
    sa_opp_cnt = {p: sum(1 for it in (d_p.get('items') or []) if (it.get('gap_pct') or 0) > 0)
                  for p, d_p in sap_all.items()}
    # 实测CT治理口径：ACT 超出 SCT 5% 以上（gap_pct = (SCT−ACT)/SCT×100 < −5）
    act_over5_cnt = {p: sum(1 for it in (d_p.get('items') or [])
                            if it.get('gap_pct') is not None and it['gap_pct'] < -5)
                     for p, d_p in sap_all.items()}
    act_over5_total = sum(act_over5_cnt.values())
    chg_by_plant = defaultdict(lambda: [0, 0])   # plant -> [BOL下降(改善)项, BOL上升(变差)项]
    for c in Q['bol_changes']:
        if c['delta'] is not None:
            chg_by_plant[c['plant']][0 if c['delta'] < 0 else 1] += 1
    tbl_plants = MAIN_PLANTS + [p for p in sorted(set(fs['this']) | set(chg_by_plant) | set(sa_opp_cnt))
                                if p not in MAIN_PLANTS]
    ct_anom_cnt = sum(1 for rows_d in ctt_mom.values()
                      for r in rows_d if _near_double(r['recent_avg'], r['base_avg']))
    sa_opp_total = sum(sa_opp_cnt.values())

    P.append(f"""
<div class="section">
  <h2>四、数据洞察与改善建议</h2>
  <h3>4.1 各工厂重点关注清单</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>工厂</th><th>本季审批</th><th>BOL环比（改善/变差）</th><th>低LB项目</th><th>最新LB</th><th>实测CT需治理（ACT&gt;SCT 5%）</th><th>SCT收紧机会</th><th>重点关注</th></tr></thead>
    <tbody>""")
    for p in tbl_plants:
        dn_c, up_c = chg_by_plant.get(p, [0, 0])
        chg_html = (f'<span class="delta-down">▼{dn_c}</span> / <span class="delta-up">▲{up_c}</span>'
                    if (dn_c or up_c) else '—')
        lbv = lb_last.get(p)
        items_f = []
        if act_over5_cnt.get(p, 0):
            items_f.append(f"实测CT治理（{act_over5_cnt[p]} 组 ACT&gt;SCT 5%）")
        if Q['low_lb_by_plant'].get(p, 0):
            items_f.append(f"线平衡改善（{Q['low_lb_by_plant'][p]} 项 LB&lt;85%）")
        if sa_opp_cnt.get(p, 0):
            items_f.append(f"标准收紧复核（{sa_opp_cnt[p]} 组 ACT&lt;SCT）")
        if up_c > dn_c and up_c:
            items_f.append(f"BOL 版本回升（{up_c} 项变大，需复核）")
        focus_p = '；'.join(items_f) if items_f else '整体平稳，保持维护节奏'
        P.append(f"<tr><td>{pcn(p)}</td><td>{fs['this'].get(p, 0)}</td><td>{chg_html}</td>"
                 f"<td>{Q['low_lb_by_plant'].get(p, 0)}</td>"
                 f"<td>{f'{lbv * 100:.1f}%' if lbv is not None else '—'}</td>"
                 f"<td>{act_over5_cnt.get(p, 0)}</td><td>{sa_opp_cnt.get(p, 0)}</td>"
                 f"<td class='lft'>{focus_p}</td></tr>")

    # 4.2 洞察文案（三大主题，数据驱动）
    ins_dq, ins_op, ins_cf = [], [], []
    # ① 数据异常识别（产线采集数据本身可能异常，需相应工厂核查改进）
    if anom_cnt or ct_anom_cnt:
        ins_dq.append(f"环比数据中 <b>{(anom_cnt or 0) + ct_anom_cnt}</b> 组出现接近 2 倍关系"
                      f"（TOP10 对比 {anom_cnt} 组、CT 趋势 {ct_anom_cnt} 组），疑似过程漏提交或重复提交，请相关工厂核实提交规范性。")
    if gmax and gmax['ct'] > 120:
        ins_dq.append(f"瓶颈 CT 本季最高 <b>{gmax['ct']:.0f}s</b>（{pcn(gmax['plant'])} {gmax['pc']}"
                      f"（{gmax['pn']}，{gmax['line']}）），需核查采集口径与产线实际状态。")
    # ② 改善机会识别（标准与实际对比、版本环比）
    if act_over5_total:
        worst = None   # (gap_pct, plant, item) 找 ACT 超出 SCT 比例最大的组
        for p, d_p in sap_all.items():
            for it in (d_p.get('items') or []):
                gp = it.get('gap_pct')
                if gp is not None and gp < -5 and (worst is None or gp < worst[0]):
                    worst = (gp, p, it)
        worst_txt = ''
        if worst:
            gp, wp, wi = worst
            worst_txt = (f"，其中{pcn(wp)} {wi['pc']}（{wi.get('pn') or ''}，{wi['line']}·{wi['process']}）"
                         f"ACT 超出 SCT 达 {abs(gp):.1f}% 为最大")
        ins_op.append(f"实测 CT 高于标准 5% 以上（ACT&gt;SCT×1.05）<b>{act_over5_total}</b> 组{worst_txt}，"
                      f"需分析原因（工艺 / 设备 / 瓶颈工位 / 标准合理性）并制定改善措施。")
    if deltas:
        ins_op.append(f"BOL 版本环比：<b>{down_cnt} 项下降（改善）/ {up_cnt} 项上升（变差）</b>，"
                      f"平均 {'−' if avg_d < 0 else '+'}{abs(avg_d):.2f} min；上升项目需复核变更原因（工艺变化 / 数据口径）。")
    if Q['low_lb_count']:
        ins_op.append(f"低线平衡（LB&lt;85%）项目 <b>{Q['low_lb_count']}</b> 个（占 {lb_rate:.0f}%），"
                      f"平衡率越低改善空间越大，建议从瓶颈工位优化 / 工位重组 / ECRS 入手。")
    if sa_opp_total:
        ins_op.append(f"ACT &lt; SCT（实测快于标准）<b>{sa_opp_total}</b> 组，提示标准工时存在收紧空间，"
                      f"建议在下一轮 BOL 更新中复核收紧。")
    # ③ 跨工厂对比（横向识别差异）
    if red_items:
        miss_cf = [p for p, v in red_items if v < 5.4]
        ins_cf.append(f"BOL 降低率：{len(red_hit)}/{len(red_items)} 家达成 5.4% 目标"
                      + (f"；{('、'.join(pcn(p) for p in miss_cf))} 未达成，需加大 BOL 更新与改善力度" if miss_cf else '') + '。')
    if cap_items:
        ins_cf.append(f"ACT CT 抓取率：{pcn(cap_items[-1][0])} 最高（{cap_items[-1][1]}%）、"
                      f"{pcn(cap_items[0][0])} 最低（{cap_items[0][1]}%），抓取率偏低工厂需加强产线实测数据采集。")
    if ok_plants:
        ins_cf.append(f"线平衡率：{('、'.join(pcn(p) for p in ok_plants))} 达标（≥85%），其工位排布经验可供其他工厂借鉴。")
    if top3_txt:
        ins_cf.append(f"提报活跃度：{top3_txt} 为本季提报主力（合计 {top3_pct}%），提报节奏偏慢的工厂需保持 BOL 更新频率。")

    P.append(f"""</tbody></table></div>
  <h3>4.2 数据洞察</h3>
  <div class="insight-box">
    <b>① 数据异常识别（数据质量）：</b>
    <ul class="summary-list">
      {''.join(f'<li>{b}</li>' for b in ins_dq) or '<li>本季未发现明显数据异常。</li>'}
    </ul>
    <b>② 改善机会识别（标准 vs 实际 / 版本环比）：</b>
    <ul class="summary-list">
      {''.join(f'<li>{b}</li>' for b in ins_op) or '<li>暂无可识别的改善机会。</li>'}
    </ul>
    <b>③ 跨工厂对比：</b>
    <ul class="summary-list">
      {''.join(f'<li>{b}</li>' for b in ins_cf) or '<li>暂无跨厂可比数据。</li>'}
    </ul>
  </div>
  <h3>4.3 改善建议</h3>
  <div class="insight-box">
    <ol class="summary-list">
      <li><b>数据质量整改</b>：接近 2 倍关系的异常数据与瓶颈 CT 异常项目，由对应工厂先核查采集口径（传感器 / 录入 / 提交流程），排除数据问题后再进入改善分析，避免异常数据误导改善方向。</li>
      <li><b>BOL 版本管理</b>：本季 BOL 上升（变差）项目逐项复核变更原因；降幅显著项目的改善经验（工艺优化 / 布局调整）建议在区域 IE 例会上分享推广。</li>
      <li><b>线平衡改善</b>：低 LB 项目优先从瓶颈工位入手（ECRS / 工位重组 / 自动化辅助），改善完成后及时刷新 BOL 并提报审批。</li>
      <li><b>实测 CT 治理</b>：ACT 超出 SCT 5% 以上（ACT&gt;SCT×1.05）的产线逐组分析原因（工艺 / 设备 / 瓶颈工位 / 标准合理性）并制定改善措施，改善后复测验证。</li>
      <li><b>标准工时收紧</b>：ACT&lt;SCT 项目在下一轮 BOL 更新中复核并收紧 SCT；无 SCT 匹配的实测产线补充标准提报，扩大可比范围。</li>
      <li><b>闭环跟踪</b>：以上异常项与改善机会建议录入高 BOL 跟踪模块，形成 OPEN → IN_PROGRESS → ACHIEVED → VERIFIED → CLOSED 闭环，下季度报告回顾进展。</li>
    </ol>
  </div>
</div>
<div class="report-footer">
  BOL 管理系统 · 季度分析报告（{yr} Q{qr}） | Generated by BOL 管理系统 | 数据截至 {Q['gen_date']} | 季度口径：自然季度（Q{qr} = 第 {3 * (qr - 1) + 1}-{3 * (qr - 1) + 3} 月）
</div>""")

    # ── 图表JS ──
    colors = {'BJ': '#2e5aac', 'SH': '#e07a5f', 'CQ': '#27ae60', 'CJ': '#8e44ad', 'GZ': '#eab308'}
    lb_series = []
    for p in ['BJ', 'SH', 'CQ', 'CJ', 'GZ']:
        vals = [next((round(k['v'] * 100, 1) for k in kpi if k['ym'] == ym and k['plant'] == p), None) for ym in yms]
        lb_series.append(f"{{name:'{pcn(p)}', data:{jd(vals)}, color:'{colors[p]}', endLabel:true}}")
    m_lab_q = [f"{int(m[5:])}月" for m in qm_list]
    lbp_cnt = sorted(agg_main.items(), key=lambda x: x[1]['count'])
    js = f"""
barChart('c-monthly', '月度 BOL 审批通过数（{QL}）', 'HRDB 动态BOL审批记录（Approved）· 仅展示本季度',
  {jd(m_lab_q)}, [{{name:'审批通过(项)', data:{jd(qm_cnt)}, color:'#2e5aac', label:true}}], {{bottom:44}});
barChart('c-factory', '各工厂审批分布对比', '按 {QL} 审批量降序',
  {jd([pcn(p) for p in plants_all])}, [
    {{name:'{YL}', data:{jd([fs['yoy'].get(p, 0) for p in plants_all])}, color:'#cbd5e1'}},
    {{name:'{TL}', data:{jd([fs['prev'].get(p, 0) for p in plants_all])}, color:'#94a3b8'}},
    {{name:'{QL}', data:{jd([fs['this'].get(p, 0) for p in plants_all])}, color:'#2e5aac', label:true}}]);
lineChart('c-lb', '各工厂 LB KPI 月度趋势', 'IE KPI 月度（%）',
  {jd([str(int(m[5:])) + '月' for m in yms])}, [{', '.join(lb_series)}], {{y:85, label:'目标 85%'}});
hBarChart('c-lowlb', '低LB项目数（按工厂）', 'LB<85%，共 {Q['low_lb_count']} 项 / {Q['low_lb_total_projects']} 项 · 平衡率越低改善空间越大',
  {jd([pcn(p) for p, _ in lbp_cnt])}, [
    {{name:'低LB项目数', data:{jd([v['count'] for _, v in lbp_cnt])}, color:'#94a3b8'}}]);
"""
    js_all = ';\n'.join(js_parts) + (';\n' + js if js_parts else js)
    return page(f'BOL 季度分析报告 · {yr} Q{qr}', ''.join(P), js_all)


# ════════════════════════════════════════════════════════════════
# 年度报告
# ════════════════════════════════════════════════════════════════
def build_year(Y):
    P = []
    procs = ['FA', 'IHE', 'IHR']
    yr, pyr = Y['year'], Y['prev_year']
    gen_date = Y['gen_date']
    data_end = Y['data_end']
    # 年度标题：当年生成显示 YTD 月份，次年生成显示全年
    if Y['ytd_month'] < 12:
        title_period = f'{yr}（1-{Y["ytd_month"]}月）'
    else:
        title_period = f'{yr}（全年）'

    # ---- 预计算：可信度分级的跨工厂可比组合 ----
    combo = defaultdict(dict)  # (process, roof) -> {plant: row}
    for r in Y['ach_won_by_roof_plant']:
        combo[(r['process'], r['roof'])][r['plant']] = r
    combos_show = []   # (key, plants(n>=3), level)
    combos_wait = []   # 样本积累中
    for key in sorted(combo, key=lambda k: -sum(x['n'] for x in combo[k].values())):
        plants_mid = [p for p, r in combo[key].items() if r['n'] >= 3]
        total = sum(r['n'] for r in combo[key].values())
        shown_total = sum(combo[key][p]['n'] for p in plants_mid)
        if len(plants_mid) >= 2 and shown_total >= 10:
            n5 = [p for p in plants_mid if combo[key][p]['n'] >= 5]
            level = 'high' if len(n5) >= 2 and len(n5) == len(plants_mid) else 'mid'
            combos_show.append((key, plants_mid, level))
        elif total >= 8:
            combos_wait.append((key, total))

    P.append(f"""
<div class="report-header">
  <h1>BOL 年度分析报告 · {title_period}</h1>
  <div class="subtitle">预算结构 · 跨工厂对标 · 改善目标达成 | 数据范围：{yr}-01-01 ~ {data_end}，对比 {pyr} 全年 / FY{pyr}</div>
  <div class="meta">数据来源：FY{yr} 预算BOL（CMC：Budget / Achievable / Target）· 动态BOL审批（HRDB）· 实测CT瓶颈（HRDB）· IE改善目标与KPI（HRDB） | 生成日期：{gen_date}</div>
</div>""")

    # ── 一、分析范围与数据口径 ──
    cov = defaultdict(dict)
    for r in Y['ach_coverage']:
        cov[r['plant']][r['process']] = r['projects']
    P.append(f"""
<div class="section">
  <h2>一、分析范围与数据口径</h2>
  <h3>1.1 FY{yr} Achievable BOL 覆盖范围（按工厂×工艺）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>工厂</th><th>FA 项目数</th><th>IHE 项目数</th><th>IHR 项目数</th><th>合计</th></tr></thead>
    <tbody>""")
    for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ', 'WH']:
        if p not in cov:
            continue
        c = cov[p]
        tot = sum(c.values())
        P.append(f"<tr><td>{pcn(p)}</td><td>{c.get('FA', '—')}</td><td>{c.get('IHE', '—')}</td>"
                 f"<td>{c.get('IHR', '—')}</td><td><b>{tot}</b></td></tr>")
    P.append(f"""</tbody></table></div>
  <h3>1.2 数据源与更新时点</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>数据域</th><th>来源</th><th>时间覆盖</th><th>本报告用途</th></tr></thead>
    <tbody>
      <tr><td class='lft'>预算BOL（Budget/Achievable/Target）</td><td>CMC 年度Excel导入</td><td>FY{pyr} / FY{yr}</td><td class='lft'>第二、三、四章结构分析</td></tr>
      <tr><td class='lft'>动态BOL审批记录</td><td>HRDB（事件驱动）</td><td>{pyr} ~ {yr}</td><td class='lft'>实际BOL、版本变化、QWS对比</td></tr>
      <tr><td class='lft'>实测CT瓶颈</td><td>HRDB（日更）</td><td>近13个月</td><td class='lft'>第十章稳定性趋势</td></tr>
      <tr><td class='lft'>改善目标 / IE KPI</td><td>HRDB（月更）</td><td>{yr}</td><td class='lft'>第七、十一章达成分析</td></tr>
    </tbody></table></div>
  <h3>1.3 可信度规则（本报告仅展示 ≥80% 可信度结论）</h3>
  <div class="insight-box">
    <ul class="summary-list">
      <li>{CONF_HIGH}：对比组合总样本 ≥10 且各工厂 ≥5 个项目 —— 结论可直接用于决策。</li>
      <li>{CONF_MID}：组合总样本 ≥10、个别工厂样本 3-4 个 —— 结论供参考，标注后展示。</li>
      <li>样本不足的组合<b>不展示对比结论</b>，仅在第 6 章末尾列明样本状态，待数据积累。</li>
      <li>爬坡期项目、口径存疑数据均显式标注，不参与结论。</li>
    </ul>
  </div>
</div>""")

    # ── 二、年度概览 ──
    appr_cur = sum(m['cnt'] for m in Y[f'approval_{yr}'])
    appr_prev = sum(m['cnt'] for m in Y[f'approval_{pyr}'])
    n_it = sum(1 for r in Y['improve_target_rows'] if r.get('target_ratio') is not None)
    n_ct_plants = len([p for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ'] if any(
        v for ym, d in Y['kpi_monthly'].items() for pp, v in d.items() if pp == p)]) or 5
    P.append(f"""
<div class="section">
  <h2>二、年度概览</h2>
  <div class="stat-row">
    <div class="stat-card"><div class="num">{appr_cur}</div><div class="label">{yr} 审批通过（{Y[f'unique_programs_{yr}']} 项目）｜{pyr} 全年 {appr_prev}（{Y[f'unique_programs_{pyr}']}）</div></div>
    <div class="stat-card"><div class="num">{Y['ach_won_projects']}</div><div class="label">FY{yr} WON 项目（Achievable 口径）</div></div>
    <div class="stat-card"><div class="num">{len(Y['improve_target_rows'])}</div><div class="label">年度改善目标项（{n_it} 项含目标比例）</div></div>
    <div class="stat-card"><div class="num">{len(Y['fy_pairs'])}</div><div class="label">FY{pyr}→{yr} 同项目可比对（项目×工艺）</div></div>
    <div class="stat-card"><div class="num">{n_ct_plants}</div><div class="label">实测CT监控工厂（BJ/SH/CJ/CQ/GZ）</div></div>
  </div>
  <div class="insight-box">
    <b>年度主线：</b>预算结构与执行端详见后续章节；同项目同比变化（第八章）与改善目标达成（第七章）为年度改善成效的两条主线。
  </div>
</div>""")

    # ── 三、预算BOL三类型结构 ──
    bp = {(r['fy'], r['process']): r for r in Y['budget_by_process']}
    at = {(r['fy'], r['type'], r['process']): r for r in Y['achtgt_by_process']}
    tgt = [round(at[(yr, 'TARGET', p)]['bol'], 1) if (yr, 'TARGET', p) in at else None for p in procs]
    ach = [round(at[(yr, 'ACHIEVABLE', p)]['bol'], 1) if (yr, 'ACHIEVABLE', p) in at else None for p in procs]
    bud = [round(bp[(yr, p)]['bud'], 1) if (yr, p) in bp else None for p in procs]
    P.append(f"""
<div class="section">
  <h2>三、预算 BOL 三类型结构（FY{yr}）</h2>
  <h3>3.1 按工艺的三类型对比</h3>
  <div class="chart-box sm" id="y-types"></div>
  <div class="chart-legend-hint">Target = 产能规划目标；Achievable = CT/HC 计算可达值；Budget = 年度预算值。柱值为项目均值（min/台）。</div>
  <h3>3.2 FY{pyr} → FY{yr} 预算对比</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>工艺</th><th>FY{pyr} 预算均值</th><th>FY{yr} 预算均值</th><th>变化</th><th>Target→Achievable 降本空间</th><th>FY{yr} 项目数</th></tr></thead>
    <tbody>""")
    budget_insight = []
    for i, p in enumerate(procs):
        if (pyr, p) not in bp or (yr, p) not in bp or not bp[(pyr, p)]['bud']:
            P.append(f"<tr><td>{p}</td><td>—</td><td>{bud[i] if bud[i] is not None else '—'}</td><td>—</td><td>—</td><td>{bp[(yr, p)]['n'] if (yr, p) in bp else '—'}</td></tr>")
            continue
        b_prev, b_cur = bp[(pyr, p)]['bud'], bp[(yr, p)]['bud']
        chg = (b_cur - b_prev) / b_prev * 100
        cls = 'delta-down' if chg < 0 else 'delta-up'
        arrow = '▼' if chg < 0 else '▲'
        gap_ta = (ach[i] - tgt[i]) if (ach[i] is not None and tgt[i] is not None) else None
        gap_txt = f"{gap_ta:.1f} min（{(gap_ta / tgt[i]) * 100:.0f}%）" if (gap_ta is not None and tgt[i]) else '—'
        P.append(f"<tr><td>{p}</td><td>{b_prev:.1f}</td><td>{b_cur:.1f}</td>"
                 f"<td><span class='{cls}'>{arrow} {abs(chg):.0f}%</span></td>"
                 f"<td>{gap_txt}</td><td>{bp[(yr, p)]['n']}</td></tr>")
        budget_insight.append(f"{p} 预算均值{arrow}{abs(chg):.0f}%（{b_prev:.1f}→{b_cur:.1f}）")
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>结构解读：</b>{'；'.join(budget_insight) if budget_insight else '本年无预算对比数据'}。三类型梯度（Target / Achievable / Budget）显示产能目标与当前可达水平的牵引关系，详见 3.1 图。
  </div>
</div>""")

    # ── 四、工艺×产品类型总览 ──
    roof_rows = [r for r in Y['ach_by_roof_won'] if r['n'] >= 5]
    n_hidden = len([r for r in Y['ach_by_roof_won'] if r['n'] < 5])
    P.append(f"""
<div class="section">
  <h2>四、工艺 × 产品类型 BOL 总览（FY{yr} · WON）</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>工艺</th><th>产品类型 (Roof Type)</th><th>项目数</th><th>可信度</th><th>均值 (min)</th><th>Min – Max (min)</th></tr></thead>
    <tbody>""")
    for r in roof_rows:
        conf = CONF_HIGH if r['n'] >= 10 else CONF_MID
        P.append(f"<tr><td>{r['process']}</td><td class='lft'>{esc(r['roof'])}</td><td>{r['n']}</td>"
                 f"<td>{conf}</td><td><b>{r['avg']:.1f}</b></td><td>{r['min']:.1f} – {r['max']:.1f}</td></tr>")
    # 产品复杂度梯度（按工艺排序的 Top 类型，动态）
    grad_parts = []
    by_proc = defaultdict(list)
    for r in roof_rows:
        by_proc[r['process']].append(r)
    for pr, rs in by_proc.items():
        rs_sorted = sorted(rs, key=lambda x: -x['avg'])
        grad_parts.append(pr + ' 中 ' + ' > '.join(
            f"{r['roof']}（{r['avg']:.1f}）" for r in rs_sorted[:4]))
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>产品复杂度梯度（仅列 n≥5 类型）：</b>{'；'.join(grad_parts) if grad_parts else '暂无 n≥5 的类型'}。另有 {n_hidden} 个小样本类型（n&lt;5）按可信度规则不展示结论。
  </div>
</div>""")

    # ── 五、跨工厂总览 ──
    ap = {(r['plant'], r['process']): r for r in Y['ach_by_plant_process']}
    cf = {'FA': [p for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ'] if (p, 'FA') in ap and ap[(p, 'FA')]['n'] >= 5],
          'IHE': [p for p in ['BJ', 'SH', 'CQ'] if (p, 'IHE') in ap and ap[(p, 'IHE')]['n'] >= 5],
          'IHR': [p for p in ['CJ', 'GZ'] if (p, 'IHR') in ap and ap[(p, 'IHR')]['n'] >= 5]}
    P.append(f"""
<div class="section">
  <h2>五、跨工厂 BOL 总览（FY{yr} Achievable，按工艺）</h2>
  <div class="chart-legend-hint">每个蓝点 = 单个项目 Achievable BOL，橙色横线 = 工厂均值（含极值全量展示，样本量见各工厂标注）；仅含 n≥5 的工厂。注：此为工厂整体水平，产品组合结构不同，精细对比见第六章。</div>""")
    for i, pr in enumerate(procs):
        pl = cf[pr]
        if not pl:
            continue
        lo_p = min(pl, key=lambda p: ap[(p, pr)]['avg'] or 0)
        hi_p = max(pl, key=lambda p: ap[(p, pr)]['avg'] or 0)
        note = (f"{pcn(hi_p)}（{ap[(hi_p, pr)]['avg']:.1f}，n={ap[(hi_p, pr)]['n']}）最高，"
                f"{pcn(lo_p)}（{ap[(lo_p, pr)]['avg']:.1f}，n={ap[(lo_p, pr)]['n']}）最低。")
        P.append(f"""
  <h3>5.{i + 1} {pr} 跨工厂总览</h3>
  <div class="chart-box sm" id="y-ov-{pr}"></div>
  <div class="insight-box" style="font-size:.86rem">{note}</div>""")
    P.append("</div>")

    # ── 六、跨工厂可比组合深度对比 ──
    P.append(f"""
<div class="section">
  <h2>六、跨工厂可比组合深度对比（工艺 × 产品类型）</h2>
  <div class="chart-legend-hint">同产品类型内的跨工厂对比，消除产品结构差异后可比性更强；仅展示 1.3 规则达标的组合，样本数标注于图中。</div>""")
    combo_insights = []
    findings = []
    for idx, (key, plants_ok, level) in enumerate(combos_show):
        pr, roof = key
        rows = [combo[key][p] for p in plants_ok]
        rows.sort(key=lambda r: r['avg'])
        lo, hi = rows[0], rows[-1]
        diff = (hi['avg'] - lo['avg']) / lo['avg'] * 100 if lo['avg'] else 0
        conf = CONF_HIGH if level == 'high' else CONF_MID
        shown_n = sum(r['n'] for r in rows)
        P.append(f"""
  <h3>6.{idx + 1} {pr} + {esc(roof)}</h3>
  <div class="chart-box sm" id="y-cb-{idx}"></div>""")
        ins = (f"{conf}｜样本 {shown_n} 项（{' / '.join(f'{pcn(r['plant'])} {r['n']}' for r in rows)}）："
               f"<b>{pcn(lo['plant'])} {lo['avg']:.2f} min 为标杆</b>，最高 {pcn(hi['plant'])} {hi['avg']:.2f} min，"
               f"差距 {diff:.1f}%（{hi['avg'] - lo['avg']:.2f} min/台）。")
        if diff < 2:
            ins += " 两厂水平高度一致，可作为跨工厂标准化的最佳实践组合。"
        P.append(f"""  <div class="insight-box" style="font-size:.86rem">{ins}</div>""")
        findings.append({'combo': f'{pr}+{roof}', 'n': shown_n,
                         'lo': f"{pcn(lo['plant'])} ({lo['avg']:.2f})",
                         'hi': f"{pcn(hi['plant'])} ({hi['avg']:.2f})",
                         'diff': diff, 'level': level})
        combo_insights.append((key, lo, hi, diff, level))
    P.append(f"""
  <h3>6.{len(combos_show) + 1} 高可信度发现汇总</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>组合</th><th>可比样本</th><th>标杆工厂(最低)</th><th>最高工厂</th><th>差距</th><th>可信度</th></tr></thead>
    <tbody>""")
    for fd in findings:
        conf = CONF_HIGH if fd['level'] == 'high' else CONF_MID
        P.append(f"<tr><td>{esc(fd['combo'])}</td><td>{fd['n']}</td><td>{fd['lo']}</td>"
                 f"<td>{fd['hi']}</td><td><b>{fd['diff']:.1f}%</b></td><td>{conf}</td></tr>")
    P.append(f"""</tbody></table></div>""")
    if combos_wait:
        wait_txt = '、'.join(f"{k[0]}+{esc(k[1])}（{t} 项）" for k, t in combos_wait)
        P.append(f"""
  <h3>6.{len(combos_show) + 2} 样本积累中的组合（不展示结论）</h3>
  <div class="warn-box">
    以下组合总样本不足 10 项或可比工厂样本 &lt;3，按可信度规则不做对比结论，仅提示样本状态：{wait_txt}。建议保持数据维护节奏，样本达标后自动进入下一期报告对比。
  </div>""")
    P.append("</div>")

    # ── 七、实际vs预算改善目标 ──
    itp = Y['improve_target_by_plant']
    order = [p for p in ['SH', 'BJ', 'CJ', 'CQ', 'GZ'] if p in itp]
    states = [('met', '已达标', '#27ae60'), ('near', '接近(≥60%)', '#7fb069'),
              ('improved', '优于预算', '#2e5aac'), ('behind', '落后', '#e67e22'), ('worse', '超预算', '#e74c3c')]
    seen = set()
    behind = []
    buckets = {'b1': 0, 'b2': 0, 'b3': 0, 'b4': 0}
    for r in Y['improve_target_rows']:
        if r.get('actual') is None or r.get('budget') is None:
            continue
        k = (r['plant'], r['program'], r['process'], r['budget'])
        if k in seen:
            continue
        seen.add(k)
        g = r.get('gap_pct')
        if g is None:
            continue
        if g <= -10:
            buckets['b1'] += 1
        elif g <= 0:
            buckets['b2'] += 1
        elif g <= 10:
            buckets['b3'] += 1
        else:
            buckets['b4'] += 1
        if r.get('state') == 'behind':
            behind.append(r)
    behind.sort(key=lambda x: -x['gap_pct'])
    n_no_actual = sum(1 for r in Y['improve_target_rows'] if r.get('actual') is None)
    n_dup = len(Y['improve_target_rows']) - len(seen)
    # 各厂达成状态摘要（动态）
    state_labels = {s: lab for s, lab, _c in states}
    plant_state_txt = '；'.join(
        f"{pcn(p)}（" + '、'.join(
            f"{state_labels[s]} {c}" for s, c in itp[p].items()) + "）"
        for p in order)
    behind_top_plant = max(itp.items(), key=lambda kv: kv[1].get('behind', 0), default=None)
    P.append(f"""
<div class="section">
  <h2>七、实际 vs 预算：年度改善目标达成</h2>
  <h3>7.1 各工厂达成状态分布</h3>
  <div class="chart-box sm" id="y-target"></div>
  <div class="chart-legend-hint">口径：improveTarget 预算 BOL × 最近审批实际 BOL（项目×工艺最新版本，已去重）。已达标 = 实际≤预算×(1−目标)；优于预算 = 无目标比例且实际&lt;预算。</div>
  <h3>7.2 实际 vs 预算偏差分布</h3>
  <div class="chart-box sm" id="y-bucket"></div>
  <div class="chart-legend-hint">去重后 {len(seen)} 个可比项（项目×工艺×预算值）按超预算幅度分桶。</div>
  <h3>7.3 落后项目 Top10（按超预算幅度）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>项目</th><th>工厂</th><th>工艺</th><th>预算BOL</th><th>实际BOL</th><th>超预算</th><th>状态</th></tr></thead>
    <tbody>""")
    for r in behind[:10]:
        P.append(f"<tr><td class='lft'>{esc(r['name'])}</td><td>{pcn(r['plant'])}</td>"
                 f"<td>{r['process']}</td><td>{r['budget']:.1f}</td><td>{r['actual']:.1f}</td>"
                 f"<td><span class='delta-up'>+{r['gap_pct']:.1f}%</span></td>"
                 f"<td><span class='tag tag-hot'>待核实</span></td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="warn-box">
    <b>口径与数据校验提示：</b>
    <ul class="summary-list">
      <li>{plant_state_txt}。{f'<b>{pcn(behind_top_plant[0])} {behind_top_plant[1].get("behind", 0)} 项落后为全厂最多</b>，需重点推动。' if behind_top_plant and behind_top_plant[1].get('behind') else ''}</li>
      <li>偏差分布：<b>{buckets['b2']} 项在预算内（−10%~0）</b>、{buckets['b3']} 项小幅超预算（0~10%）、{buckets['b4']} 项超 10% —— 偏差 &gt;10% 的项目建议逐项核实（含爬坡期与跨线匹配因素）后再定改善措施。</li>
      <li>实际值远低于预算的项目多为<b>新项目爬坡期数据</b>，不代表真实达成，已按口径规则标注，不纳入结论。</li>
      <li>{n_no_actual} 项暂无审批实际值（未提报 BOL），未纳入统计；原始明细含 {n_dup} 条重复行已去重。</li>
    </ul>
  </div>
</div>""")

    # ── 八、同项目变化 ──
    fy = Y['fy_by_process']
    fy_order = [p for p in procs if p in fy]
    fy_li = []
    for p in fy_order:
        v = fy[p]
        pct = v['avg_delta_pct']
        cls = 'delta-down' if pct < 0 else 'delta-up'
        fy_li.append(f"<li><b>{p}</b>：平均 <span class='{cls}'>{pct:+.1f}%</span>"
                     f"（{v['improved']} 改善 / {v['stable']} 持平 / {v['worse']} 恶化，n={v['n']}）。</li>")
    drop_txt = '、'.join(f"{x['program']} {x['process']} {x['delta']:.2f}" for x in Y['fy_top_drop'][:3])
    P.append(f"""
<div class="section">
  <h2>八、FY{pyr} → FY{yr} 同项目 Achievable 变化</h2>
  <div class="chart-box sm" id="y-fy"></div>
  <div class="chart-legend-hint">两财年均有的（项目×工艺）配对，n={len(Y['fy_pairs'])} 对；改善 = BOL 下降 &gt;0.5 min，恶化 = 上升 &gt;0.5 min。</div>
  <div class="insight-box">
    <b>趋势结论（样本量 {len(Y['fy_pairs'])} 对）：</b>
    <ul class="summary-list">
      {''.join(fy_li)}
      <li>降幅前三位：{drop_txt}。</li>
    </ul>
  </div>
</div>""")

    # ── 九、QWS报价覆盖 ──
    qs = Y['qws_summary']
    P.append(f"""
<div class="section">
  <h2>九、QWS 报价 vs 实际 BOL 覆盖</h2>
  <div class="chart-box sm" id="y-qws"></div>
  <div class="chart-legend-hint">口径：每个项目最近审批版本的全部工艺 BOL 合计 ÷ QWS 报价 BOL（n={qs['n']} 个有报价项目）。</div>
  <div class="insight-box">
    <b>覆盖结论（n={qs['n']}，整体可信）：</b>中位覆盖比 <b>{qs['median']}%</b>，{qs['b80_100']} 个项目（{qs['b80_100'] / qs['n'] * 100:.0f}%）落在 80-100% 区间 —— 实际 BOL 与报价口径整体高度对齐。
  </div>
  <div class="table-wrap"><table>
    <thead><tr><th>项目</th><th>实际BOL合计 (min)</th><th>QWS报价 (min)</th><th>覆盖比</th><th>状态</th></tr></thead>
    <tbody>""")
    for x in Y['qws_items'][:5]:
        P.append(f"<tr><td class='lft'>{esc(x['program'])}</td><td>{x['bol']:.1f}</td><td>{x['qws']:.1f}</td>"
                 f"<td><span class='delta-up'>{x['ratio']:.0f}%</span></td><td><span class='tag tag-hot'>口径待核实</span></td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="warn-box">
    覆盖比 &gt;100% 的 {qs['over']} 个项目（上表为前 5）多数疑为<b>报价范围与实际统计口径不一致</b>（如报价仅含单一工艺或未含新增工序），核实前不作为超支结论，仅作为商务与 IE 的对账清单。
  </div>
</div>""")

    # ── 十、实测CT年度稳定性 ──
    bn = Y['bn_monthly_by_plant']
    months = bn['months']
    ct_bullets = []
    for p in ['BJ', 'SH', 'CQ', 'CJ', 'GZ']:
        vals = [v for v in bn['series'].get(p, []) if v is not None]
        if len(vals) >= 2:
            lo, hi = min(vals), max(vals)
            ct_bullets.append(f"<b>{pcn(p)}</b>：{lo:.0f} ~ {hi:.0f}s 区间（首 {vals[0]:.0f}s → 末 {vals[-1]:.0f}s）。")
    P.append(f"""
<div class="section">
  <h2>十、实测CT 年度稳定性（{months[0] if months else ''} ~ {months[-1] if months else ''}）</h2>
  <div class="chart-box" id="y-ct"></div>
  <div class="chart-legend-hint">月度值 = 各工厂当月全部（项目×产线）瓶颈CT中位数；空点为当月无数据；线端标注工厂名与最新值。</div>
  <div class="insight-box">
    <ul class="summary-list">
      {''.join(f'<li>{b}</li>' for b in ct_bullets) or '<li>暂无实测CT月度数据。</li>'}
      <li>月度值骤变（如断崖式下降）的工厂，疑产线切换或采集配置变化，<b>口径确认前不解读为改善</b>。</li>
    </ul>
  </div>
</div>""")

    # ── 十一、KPI速览 ──
    km = Y['kpi_monthly']
    lm = Y['kpi_latest_month']
    red_kpi = km.get('BOL Reduction Rate', {}).get(lm, {})
    upd_kpi = km.get('BOL Updates Rate', {}).get(lm, {})
    ct_kpi = km.get('Acutal CT Rate', {}).get(lm, {})
    P.append(f"""
<div class="section">
  <h2>十一、IE KPI 达成速览（{lm}）</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>工厂</th><th>BOL Reduction Rate</th><th>BOL Updates Rate</th><th>Actual CT Rate</th><th>LB</th></tr></thead>
    <tbody>""")
    for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ']:
        red = red_kpi.get(p)
        upd = upd_kpi.get(p)
        ctr = ct_kpi.get(p)
        P.append(f"<tr><td>{pcn(p)}</td>"
                 f"<td>{f'{red * 100:.2f}%' if red is not None else '—'}</td>"
                 f"<td>{f'{upd * 100:.1f}%' if upd is not None else '—'}</td>"
                 f"<td>{f'{ctr * 100:.1f}%' if ctr is not None else '—'}</td>"
                 f"<td>—</td></tr>")
    red_vals = [v for v in red_kpi.values() if v is not None]
    upd_vals = [(p, v) for p, v in upd_kpi.items() if v is not None]
    upd_top = sorted(upd_vals, key=lambda kv: -kv[1])[:2]
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    BOL Reduction Rate 全厂 {min(red_vals) * 100:.1f}%-{max(red_vals) * 100:.1f}%（最高 {pcn(max(red_kpi.items(), key=lambda kv: kv[1] or 0)[0])} {max(red_vals) * 100:.2f}%）；BOL Updates Rate {('、'.join(f'{pcn(p)} {v * 100:.1f}%' for p, v in upd_top))} 领先，与季度报告审批活跃度相互印证。KPI 月度连续记录自 {lm} 前回溯，年度趋势判断待年末复核。
  </div>
</div>""")

    # ── 十二、综合洞察与建议 ──
    bench_lines = []
    for (key, lo, hi, diff, level) in combo_insights:
        if diff >= 2:
            bench_lines.append(
                f"<li><b>{key[0]}+{esc(key[1])}</b>：以{pcn(lo['plant'])}（{lo['avg']:.2f} min，n={lo['n']}）为标杆，"
                f"{pcn(hi['plant'])}（{hi['avg']:.2f}）单台收敛空间 {hi['avg'] - lo['avg']:.2f} min"
                f"（{CONF_HIGH if level == 'high' else CONF_MID}）。</li>")
    P.append(f"""
<div class="section">
  <h2>十二、综合洞察与改进建议</h2>
  <h3>12.1 核心洞察</h3>
  <div class="insight-box">
    <ul class="summary-list">
      <li><b>预算结构：</b>见第三章三类型结构变化（降本压力与产品复杂度迁移方向）。</li>
      <li><b>跨工厂：</b>剔除产品结构后（第六章）可比组合的标杆与差距；工厂整体均值差异（第五章）主要来自产品组合。</li>
      <li><b>目标达成：</b>第七章各厂达成状态分化，落后项最多的工厂为年度改善首要对象。</li>
      <li><b>同项目趋势：</b>第八章 FY{pyr}→{yr} 各工艺平均变化与改善/恶化分布。</li>
      <li><b>报价对齐：</b>第九章实际BOL/QWS 中位覆盖 {qs['median']}%，80-100% 区间占 {qs['b80_100'] / max(1, qs['n']) * 100:.0f}%。</li>
    </ul>
  </div>
  <h3>12.2 标杆与收敛空间（基于第六章高可信组合）</h3>
  <div class="insight-box">
    <ul class="summary-list">{''.join(bench_lines) or '<li>本年度暂无差距≥2%的高可信组合。</li>'}</ul>
  </div>
  <h3>12.3 下年度（FY{yr + 1}）行动建议</h3>
  <div class="warn-box">
    <ul class="summary-list">
      <li><b>对标专项：</b>第六章各组合落后工厂按"标杆值 + 产品结构校正"设定分阶段目标（先核产品类型/自动化差异，再定收敛幅度）。</li>
      <li><b>改善攻坚：</b>第七章落后项目最多的工厂，将落后目标与超标产线合并为工厂级改善清单，纳入跟踪模块按月复盘。</li>
      <li><b>预算编制：</b>FY{yr + 1} 以第四章产品类型均值（n≥5）为基准线，按工厂产品组合校正预算，减少结构性偏差。</li>
      <li><b>数据治理：</b>CT 口径骤变确认、爬坡期项目达成判定规则、QWS 覆盖比 &gt;100% 项目的报价口径对账、未提报项目催报机制。</li>
      <li><b>机制建设：</b>季度报告（异常识别）+ 年度报告（结构对标）固定节奏，季度跟踪年度目标完成率；第六章"样本积累中"组合达标后自动纳入对比。</li>
    </ul>
  </div>
</div>
<div class="report-footer">
  BOL 管理系统 · 年度分析报告（{title_period}） | Generated by BOL 管理系统 | 数据截至 {gen_date} | 年度口径：自然年 | 可信度规则见 1.3
</div>""")

    # ── 图表JS ──
    js = f"""
barChart('y-types', 'FY{yr} 三类型 BOL 均值（按工艺）', 'Target / Achievable（AchTgtBol）· Budget（BudgetBol）',
  {jd(procs)}, [
    {{name:'Target', data:{jd(tgt)}, color:'#1a3a6e', label:true}},
    {{name:'Achievable', data:{jd(ach)}, color:'#5b8bc9', label:true}},
    {{name:'Budget', data:{jd(bud)}, color:'#e07a5f', label:true}}]);
"""
    for pr in procs:
        pl = cf[pr]
        if not pl:
            continue
        js += f"""
stripChart('y-ov-{pr}', '{pr} 跨工厂总览（FY{yr} Achievable）', {jd('每个点 = 单个项目；橙色横线 = 工厂均值；仅含 n≥5 的工厂')},
  {jd([f"{pcn(p)}\\n(n={ap[(p, pr)]['n']})" for p in pl])},
  {jd([sorted(Y['ach_projects'].get((p, pr), [])) for p in pl])}, 'min');
"""
    for idx, (key, plants_ok, level) in enumerate(combos_show):
        rows = sorted([combo[key][p] for p in plants_ok], key=lambda r: r['avg'])
        js += f"""
crossChart('y-cb-{idx}', '{key[0]} + {key[1]} 跨工厂对比', {jd('样本：' + ', '.join(f"{pcn(r['plant'])} n={r['n']}" for r in rows))},
  {jd([f"{pcn(r['plant'])}\\n(n={r['n']})" for r in rows])}, {jd([r['avg'] for r in rows])},
  {jd([r['min'] for r in rows])}, {jd([r['max'] for r in rows])}, 'min');
"""
    t_series = []
    for sk, sn, sc in states:
        t_series.append(f"{{name:'{sn}', data:{jd([itp.get(p, {}).get(sk, 0) for p in order])}, color:'{sc}'}}")
    js += f"""
stackChart('y-target', '各工厂改善目标达成状态（{yr}）', 'improveTarget × 最近审批实际BOL（去重）',
  {jd([pcn(p) for p in order])}, [{', '.join(t_series)}]);
barChart('y-bucket', '实际 vs 预算偏差分布', '去重后可比项，按超预算幅度分桶',
  ['优于预算\\n(≤−10%)', '预算内\\n(−10%~0)', '小幅超出\\n(0~10%)', '超出>10%'], [
    {{name:'项目数', data:{jd([buckets['b1'], buckets['b2'], buckets['b3'], buckets['b4']])}, color:'#2e5aac'}}], {{yName:'项'}});
barChart('y-fy', 'FY{pyr}→FY{yr} 同项目变化方向（按工艺）', {jd('配对 n=' + str(len(Y['fy_pairs'])))},
  {jd(fy_order)}, [
    {{name:'改善(>0.5min)', data:{jd([fy[p]['improved'] for p in fy_order])}, color:'#27ae60', label:true}},
    {{name:'持平', data:{jd([fy[p]['stable'] for p in fy_order])}, color:'#94a3b8', label:true}},
    {{name:'恶化(>0.5min)', data:{jd([fy[p]['worse'] for p in fy_order])}, color:'#e74c3c', label:true}}], {{yName:'对'}});
barChart('y-qws', 'QWS 报价覆盖比分布', {jd(f"n={qs['n']} 个项目，中位 {qs['median']}%")},
  ['<50%', '50-80%', '80-100%', '>100%'], [
    {{name:'项目数', data:{jd([qs['under50'], qs['b50_80'], qs['b80_100'], qs['over']])}, color:'#2e5aac'}}], {{yName:'项'}});
"""
    ct_colors = {'BJ': '#2e5aac', 'SH': '#e07a5f', 'CQ': '#27ae60', 'GZ': '#eab308', 'CJ': '#8e44ad'}
    ct_series = []
    for p in ['BJ', 'SH', 'CQ', 'GZ', 'CJ']:
        ct_series.append(f"{{name:'{pcn(p)}', data:{jd(bn['series'].get(p))}, color:'{ct_colors[p]}', endLabel:true}}")
    js += f"""
lineChart('y-ct', '各工厂月度瓶颈CT中位数趋势', '{months[0] if months else ''} ~ {months[-1] if months else ''}（秒）', {jd(bn['months'])},
  [{', '.join(ct_series)}], {{y:120, label:'120s'}});
"""
    return page(f'BOL 年度分析报告 · {title_period}', ''.join(P), js)

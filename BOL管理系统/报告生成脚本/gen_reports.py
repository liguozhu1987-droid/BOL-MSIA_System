# -*- coding: utf-8 -*-
"""生成 BOL 季度/年度分析报告 (standalone HTML)
- 图表UI: 图例置底 + labelLayout防重叠 + 端点标签, 避免遮挡
- 可信度分级: 仅展示 ≥80% 可信度的对比结论 (n≥10且各厂≥5=高; 总量≥10且各厂≥3=中; 其余不展示)
"""
import html
import json
import os
from collections import defaultdict

TMP = r'c:\Users\ligu\.trae-cn\work\6a9391eb1284e4ca632072fe'
OUT = r'c:\WorkFile\D\OPEX\04-Digital_development\2026\IE系统完善开发\BOL管理系统'
GEN_DATE = '2026-08-30'

Q = json.load(open(os.path.join(TMP, 'quarter_data.json'), encoding='utf-8'))
Y = json.load(open(os.path.join(TMP, 'year_data.json'), encoding='utf-8'))
ECH = open(os.path.join(TMP, 'echarts.min.js'), encoding='utf-8').read().strip()
if ECH.startswith('<script>'):
    ECH = ECH[len('<script>'):]
if ECH.endswith('</script>'):
    ECH = ECH[:-len('</script>')]

PLANT_CN = {'BJ': '北京', 'SH': '上海', 'CJ': '长春', 'CQ': '重庆', 'GZ': '广州',
            'WH': '武汉', 'CMC': 'CMC', 'YT': '烟台'}


def esc(x):
    return html.escape(str(x)) if x else ''


# ══════════════════ CSS ══════════════════
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

# ══════════════════ 图表JS（防遮挡优化）══════════════════
JS_CHART = """
function baseOpt(title, sub, cfg) {
  cfg = cfg || {};
  var opt = {
    title: { text: title, subtext: sub || '', left: 4, top: 2,
             textStyle: { fontSize: 15, color: '#1a1a2e' },
             subtextStyle: { fontSize: 11, color: '#6b7280' } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(46,90,172,.06)' } },
               textStyle: { fontSize: 12 }, confine: true },
    grid: { left: 62, right: 56, top: sub ? 84 : 62, bottom: cfg.bottom || 62 },
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
function boxChart(id, title, sub, cats, data, refLine) {
  var opt = baseOpt(title, sub);
  opt.grid = { left: 62, right: 40, top: sub ? 84 : 62, bottom: 70 };
  opt.xAxis = { type: 'category', data: cats, boundaryGap: true,
                axisLabel: { fontSize: 11, interval: 0, margin: 12 } };
  opt.yAxis = { type: 'value', name: 'CT (s)', scale: true, nameTextStyle: { fontSize: 11 } };
  opt.series = [{
    name: '瓶颈CT分布', type: 'boxplot', data: data,
    itemStyle: { color: 'rgba(46,90,172,.18)', borderColor: '#2e5aac' },
    boxWidth: [26, 44]
  }, {
    name: '中位数', type: 'scatter', symbolSize: 0, silent: true,
    data: data.map(function (v, i) { return [i, v[2]]; }),
    label: { show: true, position: 'top', distance: 3, fontSize: 11,
             fontWeight: 600, color: '#12325f', formatter: '{c}' },
    tooltip: { show: false }
  }];
  if (refLine) {
    opt.series.push({ name: '120s 阈值', type: 'line', data: [],
      markLine: { symbol: 'none', silent: true,
        lineStyle: { color: '#e74c3c', type: 'dashed' },
        label: { formatter: '120s', position: 'insideEndTop', fontSize: 11 },
        data: [{ yAxis: 120 }] } });
  }
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
  opt.grid = { left: 62, right: 46, top: sub ? 84 : 62, bottom: 62 };
  opt.xAxis = { type: 'category', data: cats, axisLabel: { fontSize: 12, interval: 0, margin: 12 } };
  opt.yAxis = { type: 'value', scale: true, name: unit || '', nameTextStyle: { fontSize: 11 } };
  var bars = avg.map(function (v) { return { value: v }; });
  opt.series = [
    { name: '均值', type: 'bar', data: bars, barMaxWidth: 38,
      itemStyle: { color: '#2e5aac', borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: 'top', fontSize: 11, color: '#1a1a2e' } },
    { name: '', type: 'custom', silent: true, data: avg.map(function (v, i) { return [i]; }),
      renderItem: function (params, api) {
        var i = params.dataIndex;
        var x = api.coord([i, 0])[0];
        var yMin = api.coord([i, mn[i]])[1];
        var yMax = api.coord([i, mx[i]])[1];
        var s = { stroke: '#94a3b8', lineWidth: 2 };
        return { type: 'group', children: [
          { type: 'line', shape: { x1: x, y1: yMin, x2: x, y2: yMax }, style: s },
          { type: 'line', shape: { x1: x - 8, y1: yMin, x2: x + 8, y2: yMin }, style: s },
          { type: 'line', shape: { x1: x - 8, y1: yMax, x2: x + 8, y2: yMax }, style: s }
        ] };
      }, z: 3 }
  ];
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
<script>{ECH}</script>
<script>{JS_CHART}</script>
<script>
{extra_js}
</script>
</body>
</html>
"""


def jd(x):
    return json.dumps(x, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
# 季度报告
# ════════════════════════════════════════════════════════════════
def build_quarter():
    P = []
    fs = Q['approval_factory']
    appr_this = sum(fs['this'].values())
    appr_prev = sum(fs['prev'].values())
    bn_rate = Q['bn_over120_count'] / Q['bn_total_lines'] * 100
    lb_rate = Q['low_lb_count'] / Q['low_lb_total_projects'] * 100
    deltas = [c['delta'] for c in Q['bol_changes'] if c['delta'] is not None]
    avg_d = sum(deltas) / len(deltas) if deltas else 0
    tot_reduce = sum(v['reduce'] for v in Q['low_lb_agg_by_plant'].values())

    P.append(f"""
<div class="report-header">
  <h1>BOL 季度分析报告 · 2026 Q2</h1>
  <div class="subtitle">异常识别与 BOL 改善关注点 | 数据范围：2026-04-01 ~ 2026-06-30（最近完整自然季度）</div>
  <div class="meta">数据来源：动态BOL审批记录（HRDB）· 实测CT瓶颈（HRDB）· IE KPI月度（HRDB）· 高BOL跟踪（CMC） | 生成日期：{GEN_DATE} | 分发对象：各工厂 IE / 生产管理</div>
</div>""")

    # ── 一、季度概览 ──
    P.append(f"""
<div class="section">
  <h2>一、季度概览</h2>
  <div class="stat-row">
    <div class="stat-card"><div class="num">{appr_this}</div><div class="label">BOL审批通过（上季 {appr_prev}）</div></div>
    <div class="stat-card"><div class="num red">{Q['bn_over120_count']}</div><div class="label">瓶颈CT超标产线（&gt;120s / {Q['bn_total_lines']} 条，{bn_rate:.0f}%）</div></div>
    <div class="stat-card"><div class="num red">{Q['low_lb_count']}</div><div class="label">低LB项目（&lt;85%，占 {lb_rate:.0f}%）</div></div>
    <div class="stat-card"><div class="num green">{len(deltas)}</div><div class="label">BOL刷新版本全部下降（平均 −{abs(avg_d):.2f} min）</div></div>
    <div class="stat-card"><div class="num green">{tot_reduce}</div><div class="label">低LB项目保守减人潜力（人）</div></div>
  </div>
  <div class="insight-box">
    <b>本季要点：</b>
    <ul class="summary-list">
      <li>审批活跃度显著回升：Q2 通过 {appr_this} 项（Q1 仅 {appr_prev} 项），7-8 月延续高位（14 / 6 项），改善提报节奏已恢复正常。</li>
      <li>实测CT是本季最大异常来源：{Q['bn_over120_count']} 条产线瓶颈CT超 120s，北京超标 {Q['bn_over120_by_plant'].get('BJ', 0)} 条为最多，中位数 {Q['bn_box_by_plant']['BJ']['stats'][2]:.0f}s 全厂最高。</li>
      <li>线平衡率改善空间明确：{Q['low_lb_count']} 个项目 LB&lt;85%，保守方案合计可释放 <b>{tot_reduce} 人</b>；8月 LB KPI 仅广州（88.6%）达标。</li>
      <li>BOL 版本刷新 {len(deltas)} 项全部为下降方向，改善动作在本季审批中得到量化体现。</li>
    </ul>
  </div>
</div>""")

    # ── 二、BOL变更动态 ──
    m_lab = [m['ym'] for m in Q['approval_monthly']]
    m_val = [m['cnt'] for m in Q['approval_monthly']]
    hl = [i for i, l in enumerate(m_lab) if l in ('2026-04', '2026-05', '2026-06')]
    plants_all = sorted(set(fs['this']) | set(fs['prev']) | set(fs['yoy']),
                        key=lambda p: -fs['this'].get(p, 0))
    P.append(f"""
<div class="section">
  <h2>二、BOL 变更动态</h2>
  <h3>2.1 月度审批趋势（近 14 个月）</h3>
  <div class="chart-box" id="c-monthly"></div>
  <div class="chart-legend-hint">深蓝柱 = 本报告季度（2026 Q2）；柱值 = 当月审批通过的 BOL 变更项数（项目×工艺）。</div>
  <h3>2.2 各工厂审批分布（环比 / 同比）</h3>
  <div class="chart-box sm" id="c-factory"></div>
  <div class="chart-legend-hint">按 2026 Q2 审批量降序排列；0 表示该季无审批记录。</div>
  <div class="insight-box">
    上海（8 项）、长春（5 项）、北京（4 项）为本季提报主力，合计占 {round((fs['this'].get('SH', 0) + fs['this'].get('CJ', 0) + fs['this'].get('BJ', 0)) / appr_this * 100)}%；广州、重庆各 1 项，提报节奏需关注。
  </div>
  <h3>2.3 本季 BOL 版本变化明细</h3>
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
                 f"<td>{PLANT_CN.get(c['plant'], c['plant'])}</td><td>{esc(c['process'])}</td><td>{esc(c['line'])}</td>"
                 f"<td>{c['bol']:.2f}</td><td>{dv}</td><td>{c['date']}</td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>关键结论：</b>{len(deltas)} 项版本刷新<b>全部为下降</b>（平均 −{abs(avg_d):.2f} min）。降幅前三位：广州 T6876（Denza Z9 GT，FA）−4.94 min、长春 T6723（红旗 H6，FA）−2.83 min、上海 T6633（领克 09 EX11，FA）−1.55 min；其余 {len(Q['bol_changes']) - len(deltas)} 项为新项目首版录入，将于后续季度产生版本对比。
  </div>
</div>""")

    # ── 三、实测CT异常识别 ──
    bx = Q['bn_box_by_plant']
    bx_plants = [p for p in ['BJ', 'SH', 'CQ', 'CJ', 'GZ'] if p in bx]
    qmp, qmt = Q['bn_q_median_prev'], Q['bn_q_median_this']
    qoq_plants = [p for p in ['BJ', 'SH', 'CJ', 'GZ'] if p in qmp and p in qmt]
    P.append(f"""
<div class="section">
  <h2>三、实测CT异常识别</h2>
  <h3>3.1 各工厂瓶颈CT分布（本季最新快照）</h3>
  <div class="chart-box" id="c-box"></div>
  <div class="chart-legend-hint">箱体 = Min–Q1–中位–Q3–Max（每个（项目×产线）取本季最新一条），箱内数字 = 中位数；红色虚线 = 120s 异常阈值。</div>
  <h3>3.2 瓶颈CT超标产线 Top10（&gt;120s）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>#</th><th>项目</th><th>工厂</th><th>产线</th><th>瓶颈CT (s)</th><th>超标幅度</th><th>数据时点</th></tr></thead>
    <tbody>""")
    for i, b in enumerate(Q['bn_top15'][:10]):
        over = (b['ct'] - 120) / 120 * 100
        P.append(f"<tr><td>{i + 1}</td><td class='lft'>{esc(b['pn'])} <span style='color:#6b7280'>({esc(b['pc'])})</span></td>"
                 f"<td>{PLANT_CN.get(b['plant'], b['plant'])}</td><td>{esc(b['line'])}</td>"
                 f"<td><b>{b['ct']:.1f}</b></td><td><span class='delta-up'>+{over:.0f}%</span></td>"
                 f"<td>{b['ut'][:10]}</td></tr>")
    gmax = Q['bn_top15'][0]
    o120 = Q['bn_over120_by_plant']
    P.append(f"""</tbody></table></div>
  <div class="warn-box">
    <b>异常提示（按超标幅度排序）：</b>
    <ul class="summary-list">
      <li><b>广州 T6241（VS20，GZFA5）{gmax['ct']:.0f}s</b> = 阈值 2.9 倍、全网络最高，建议列入专项治理并核查采集口径。</li>
      <li><b>北京超标面最大（{o120.get('BJ', 0)} 条）</b>：V254（322s）、B02（283/221s）、B41V（211/170s）多项目多产线超标，中位数 {bx['BJ']['stats'][2]:.0f}s 全厂最高。</li>
      <li>重庆 0 条超标（全部产线 94-106s），稳定性最好；广州除 T6241 外整体最低（中位 {bx['GZ']['stats'][2]:.0f}s）。</li>
    </ul>
  </div>
  <h3>3.3 瓶颈CT中位数季度环比（Q1 → Q2）</h3>
  <div class="chart-box sm" id="c-qoq"></div>
  <div class="chart-legend-hint">口径：季度内全部瓶颈CT记录的中位数（按工厂）；重庆 Q1 无数据未纳入。</div>
  <div class="insight-box">
    <b>环比结论：</b>广州 {qmp.get('GZ')}s → {qmt.get('GZ')}s（<span class="delta-down">−{(1 - qmt['GZ'] / qmp['GZ']) * 100:.0f}%</span>，改善最大）；上海 106.2→105.1s 小幅改善；北京 134.3→140.6s（<span class="delta-up">+4.7%</span>）与长春 138.9→140.1s 双双走高，与其超标产线集中于 PU 线相互印证。
  </div>
</div>""")

    # ── 四、线平衡率KPI ──
    kpi = Q['kpi_lb']
    yms = ['2026-06', '2026-07', '2026-08']
    aug = {k['plant']: k['v'] for k in kpi if k['ym'] == '2026-08'}
    P.append(f"""
<div class="section">
  <h2>四、线平衡率（LB）KPI 趋势</h2>
  <div class="chart-box sm" id="c-lb"></div>
  <div class="chart-legend-hint">数据源：IE KPI 月度（kpi_name='LB'）；红色虚线 = 85% 目标线；线端标注工厂名与最新值，其余数值见悬浮提示。</div>
  <div class="insight-box">
    <ul class="summary-list">
      <li><b>广州（88.6%）唯一达标</b>且稳步上升（88.3→88.6→88.6%）。</li>
      <li><b>上海改善最快</b>：78.6 → 80.3 → 84.5%（+5.9pp），距目标线仅 0.5pp。</li>
      <li><b>长春连续下滑</b>（74.7 → 74.9 → 72.0%），全厂最低，与其 15 个低LB项目相互印证，需优先介入。</li>
      <li>北京 83-84% 企稳；重庆 76-77% 平稳偏低。</li>
    </ul>
  </div>
</div>""")

    # ── 五、低LB改善机会 ──
    agg = Q['low_lb_agg_by_plant']
    agg_main = {p: v for p, v in agg.items() if p != 'CMC'}
    tot_cons = sum(x['reduce_cons'] for x in Q['low_lb_top12'])
    P.append(f"""
<div class="section">
  <h2>五、低 LB 改善机会（LB &lt; 85%）</h2>
  <h3>5.1 各工厂项目数与保守减人潜力</h3>
  <div class="chart-box sm" id="c-lowlb"></div>
  <div class="chart-legend-hint">保守方案 = 减整人数且改善后 LB≤91%（与系统周报口径一致）；CMC 1 项（0 人）未展示。</div>
  <h3>5.2 改善机会 Top12（按 LB 升序）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>项目</th><th>工厂</th><th>工艺</th><th>HC</th><th>LB</th><th>瓶颈工位</th><th>保守可减(人)</th><th>激进可减(人)</th><th>数据时点</th></tr></thead>
    <tbody>""")
    for x in Q['low_lb_top12']:
        nm = x['name'] or x['program']
        tag = 'tag-hot' if x['lb_pct'] < 60 else 'tag-warn'
        P.append(f"<tr><td class='lft'>{esc(nm)}<br><span style='color:#6b7280;font-size:.78rem'>{esc(x['program'])} · {esc(x['line'])}</span></td>"
                 f"<td>{PLANT_CN.get(x['plant'], x['plant'])}</td><td>{esc(x['process'])}</td><td>{x['hc']:.0f}</td>"
                 f"<td><span class='tag {tag}'>{x['lb_pct']:.1f}%</span></td><td>{esc(x['bn_station'])}</td>"
                 f"<td><b>{x['reduce_cons']}</b></td><td>{x['reduce_agg']}</td><td>{x['ut']}</td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>机会量化（全量 {Q['low_lb_count']} 个低LB项目）：</b>保守方案合计可减 <b>{tot_reduce} 人</b>，其中北京 {agg.get('BJ', {}).get('reduce', 0)} 人（{agg.get('BJ', {}).get('count', 0)} 项）、上海 {agg.get('SH', {}).get('reduce', 0)} 人（{agg.get('SH', {}).get('count', 0)} 项）、长春 {agg.get('CJ', {}).get('reduce', 0)} 人、重庆 {agg.get('CQ', {}).get('reduce', 0)} 人。最低 LB 为长春 T6747（红旗 C801，FA）44.9%（HC 8，可减 3 人）。Top12 合计保守可减 {tot_cons} 人。
    <br><span style="color:#6b7280;font-size:.82rem">注：按项目×工艺取最近审批版本；部分项目版本距今较久（见"数据时点"），改善前建议先刷新 BOL 版本复核。</span>
  </div>
</div>""")

    # ── 六、高BOL跟踪闭环 ──
    P.append("""
<div class="section">
  <h2>六、高BOL跟踪闭环进展</h2>""")
    if not Q['tracking_status']:
        P.append("""
  <div class="empty-box">
    当前跟踪模块（CMC · CN_IE_BOL_HighBolTracking）暂无记录。<br>
    建议将第三章超标产线与第五章低LB项目中的高优先级项录入跟踪模块，形成 OPEN → IN_PROGRESS → ACHIEVED → VERIFIED → CLOSED 闭环；<br>
    录入后，本章节将展示状态漏斗、本季新增/达成项与成本收益（cost_gap = bol_gap × 年产量 × 工时单价）。
  </div>""")
    P.append("</div>")

    # ── 七、各工厂关注点 ──
    top_by_plant = {}
    for b in Q['bn_top15']:
        top_by_plant.setdefault(b['plant'], b)
    focus = {
        'BJ': f'瓶颈CT治理（V254/B02/B41V 多线超标，环比+4.7%）；低LB减人潜力最大（{agg.get("BJ", {}).get("reduce", 0)} 人）',
        'SH': f'低LB项目最多（29 项，可减 {agg.get("SH", {}).get("reduce", 0)} 人）；LB KPI 距目标仅 0.5pp，保持改善节奏',
        'CJ': 'LB KPI 72.0% 全厂最低且连续下滑；T6747 LB 44.9% 列专项；CT 环比 +0.9%',
        'CQ': 'CT 与 KPI 整体平稳（BOL Reduction 2.57% 领先），可输出标杆经验；关注 12 个低LB项目',
        'GZ': 'T6241（353s）极端超标专项治理；CT 环比 −24% 改善最大；LB 88.6% 唯一达标',
    }
    P.append(f"""
<div class="section">
  <h2>七、各工厂重点关注清单</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>工厂</th><th>超标产线</th><th>最高瓶颈CT</th><th>低LB项目</th><th>保守可减(人)</th><th>8月LB KPI</th><th>CT环比</th><th>本季审批</th><th>重点关注</th></tr></thead>
    <tbody>""")
    for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ']:
        mx = top_by_plant.get(p)
        mxs = f"{mx['ct']:.0f}s（{mx['pc']} {mx['line']}）" if mx else '—'
        lbv = aug.get(p)
        qd = None
        if p in qmp and p in qmt:
            qd = (qmt[p] - qmp[p]) / qmp[p] * 100
        qds = f'<span class="{"delta-up" if qd > 0 else "delta-down"}">{"+" if qd > 0 else ""}{qd:.1f}%</span>' if qd is not None else '—'
        P.append(f"<tr><td>{PLANT_CN.get(p, p)}</td><td>{o120.get(p, 0)}</td><td class='lft'>{mxs}</td>"
                 f"<td>{Q['low_lb_by_plant'].get(p, 0)}</td><td>{agg.get(p, {}).get('reduce', 0)}</td>"
                 f"<td>{f'{lbv * 100:.1f}%' if lbv else '—'}</td><td>{qds}</td><td>{fs['this'].get(p, 0)}</td>"
                 f"<td class='lft'>{focus[p]}</td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>下季度行动建议：</b>
    <ul class="summary-list">
      <li><b>北京</b>：V254/B02/B41V 超标产线制定瓶颈工位改善计划（目标：中位数回落至 120s 以内），并启动 {agg.get('BJ', {}).get('reduce', 0)} 人减人方案的前 5 项验证。</li>
      <li><b>长春</b>：LB 下滑趋势 Q3 内扭转——优先复核 T6747 等低LB项目排产与人力配置，必要时重新进行线平衡。</li>
      <li><b>上海</b>：29 个低LB项目按"保守可减人数"排序，季度内完成 Top5 改善验证，冲击 85% 达标。</li>
      <li><b>广州</b>：T6241 专项治理方案落地；保持 CT 改善趋势并输出 LB 达标经验。</li>
      <li>各工厂改善完成后在系统及时提报审批，保持 Q2 以来的提报节奏（月均 6 项以上）。</li>
    </ul>
  </div>
</div>
<div class="report-footer">
  BOL 管理系统 · 季度分析报告（模版示例：2026 Q2） | Generated by Trae Work | 数据截至 {GEN_DATE} | 季度口径：自然季度（Q2 = 4-6月）
</div>""")

    # ── 图表JS ──
    colors = {'BJ': '#2e5aac', 'SH': '#e07a5f', 'CQ': '#27ae60', 'CJ': '#8e44ad', 'GZ': '#eab308'}
    lb_series = []
    for p in ['BJ', 'SH', 'CQ', 'CJ', 'GZ']:
        vals = [next((round(k['v'] * 100, 1) for k in kpi if k['ym'] == ym and k['plant'] == p), None) for ym in yms]
        lb_series.append(f"{{name:'{PLANT_CN[p]}', data:{jd(vals)}, color:'{colors[p]}', endLabel:true}}")
    lbp_sorted = sorted(agg_main.items(), key=lambda x: x[1]['reduce'])
    js = f"""
barChart('c-monthly', '月度 BOL 审批通过数', 'HRDB 动态BOL审批记录（Approved）',
  {jd(m_lab)}, [{{name:'审批通过(项)', data:{jd(m_val)}, color:'#2e5aac'}}], {{hl:{jd(hl)}, bottom:88}});
barChart('c-factory', '各工厂审批分布对比', '按 2026 Q2 审批量降序',
  {jd([PLANT_CN.get(p, p) for p in plants_all])}, [
    {{name:'2025 Q2', data:{jd([fs['yoy'].get(p, 0) for p in plants_all])}, color:'#cbd5e1'}},
    {{name:'2026 Q1', data:{jd([fs['prev'].get(p, 0) for p in plants_all])}, color:'#94a3b8'}},
    {{name:'2026 Q2', data:{jd([fs['this'].get(p, 0) for p in plants_all])}, color:'#2e5aac', label:true}}]);
boxChart('c-box', '各工厂瓶颈CT分布（2026 Q2 最新快照）', 'n = 产线数（项目×产线本季最新值）',
  {jd([f"{PLANT_CN[p]} (n={bx[p]['n']})" for p in bx_plants])},
  {jd([bx[p]['stats'] for p in bx_plants])}, true);
barChart('c-qoq', '瓶颈CT中位数：Q1 vs Q2', '季度内全部记录中位数（秒）',
  {jd([PLANT_CN[p] for p in qoq_plants])}, [
    {{name:'2026 Q1', data:{jd([qmp[p] for p in qoq_plants])}, color:'#94a3b8'}},
    {{name:'2026 Q2', data:{jd([qmt[p] for p in qoq_plants])}, color:'#2e5aac', label:true}}]);
lineChart('c-lb', '各工厂 LB KPI 月度趋势（2026）', 'IE KPI 月度（%）',
  {jd([str(int(m[5:])) + '月' for m in yms])}, [{', '.join(lb_series)}], {{y:85, label:'目标 85%'}});
hBarChart('c-lowlb', '低LB项目数与保守减人潜力（按工厂）', 'LB<85%，共 {Q['low_lb_count']} 项 / {Q['low_lb_total_projects']} 项',
  {jd([PLANT_CN.get(p, p) for p, _ in lbp_sorted])}, [
    {{name:'低LB项目数', data:{jd([v['count'] for _, v in lbp_sorted])}, color:'#94a3b8'}},
    {{name:'保守可减(人)', data:{jd([v['reduce'] for _, v in lbp_sorted])}, color:'#e07a5f'}}]);
"""
    return page('BOL 季度分析报告 · 2026 Q2', ''.join(P), js)


# ════════════════════════════════════════════════════════════════
# 年度报告
# ════════════════════════════════════════════════════════════════
def build_year():
    P = []
    procs = ['FA', 'IHE', 'IHR']

    # ---- 预计算：可信度分级的跨工厂可比组合 ----
    combo = defaultdict(dict)  # (process, roof) -> {plant: row}
    for r in Y['ach26_won_by_roof_plant']:
        combo[(r['process'], r['roof'])][r['plant']] = r
    combos_show = []   # (key, plants(n>=5), level)
    combos_wait = []   # 样本积累中
    for key in sorted(combo, key=lambda k: -sum(x['n'] for x in combo[k].values())):
        plants_mid = [p for p, r in combo[key].items() if r['n'] >= 3]   # 中可信门槛
        total = sum(r['n'] for r in combo[key].values())
        shown_total = sum(combo[key][p]['n'] for p in plants_mid)
        if len(plants_mid) >= 2 and shown_total >= 10:
            # 高可信: 至少2个工厂n≥5且全部展示工厂n≥5
            n5 = [p for p in plants_mid if combo[key][p]['n'] >= 5]
            level = 'high' if len(n5) >= 2 and len(n5) == len(plants_mid) else 'mid'
            combos_show.append((key, plants_mid, level))
        elif total >= 8:
            combos_wait.append((key, total))

    P.append(f"""
<div class="report-header">
  <h1>BOL 年度分析报告 · 2026（1-8月）</h1>
  <div class="subtitle">预算结构 · 跨工厂对标 · 改善目标达成 | 数据范围：2026-01-01 ~ 2026-08-30，对比 2025 全年 / FY2025</div>
  <div class="meta">数据来源：FY2026 预算BOL（CMC：Budget / Achievable / Target）· 动态BOL审批（HRDB）· 实测CT瓶颈（HRDB）· IE改善目标与KPI（HRDB） | 生成日期：{GEN_DATE}</div>
</div>""")

    # ── 一、分析范围与数据口径 ──
    cov = defaultdict(dict)
    for r in Y['ach26_coverage']:
        cov[r['plant']][r['process']] = r['projects']
    P.append(f"""
<div class="section">
  <h2>一、分析范围与数据口径</h2>
  <h3>1.1 FY2026 Achievable BOL 覆盖范围（按工厂×工艺）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>工厂</th><th>FA 项目数</th><th>IHE 项目数</th><th>IHR 项目数</th><th>合计</th></tr></thead>
    <tbody>""")
    for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ', 'WH']:
        if p not in cov:
            continue
        c = cov[p]
        tot = sum(c.values())
        P.append(f"<tr><td>{PLANT_CN[p]}</td><td>{c.get('FA', '—')}</td><td>{c.get('IHE', '—')}</td>"
                 f"<td>{c.get('IHR', '—')}</td><td><b>{tot}</b></td></tr>")
    P.append(f"""</tbody></table></div>
  <h3>1.2 数据源与更新时点</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>数据域</th><th>来源</th><th>时间覆盖</th><th>本报告用途</th></tr></thead>
    <tbody>
      <tr><td class='lft'>预算BOL（Budget/Achievable/Target）</td><td>CMC 年度Excel导入</td><td>FY2025 / FY2026</td><td class='lft'>第二、三、四章结构分析</td></tr>
      <tr><td class='lft'>动态BOL审批记录</td><td>HRDB（事件驱动）</td><td>2024-09 ~ 2026-08</td><td class='lft'>实际BOL、版本变化、QWS对比</td></tr>
      <tr><td class='lft'>实测CT瓶颈</td><td>HRDB（日更）</td><td>2025-08 ~ 2026-08</td><td class='lft'>第十章稳定性趋势</td></tr>
      <tr><td class='lft'>改善目标 / IE KPI</td><td>HRDB（月更）</td><td>2026</td><td class='lft'>第七、十一章达成分析</td></tr>
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
    appr26 = sum(m['cnt'] for m in Y['approval_2026'])
    appr25 = sum(m['cnt'] for m in Y['approval_2025'])
    n_it = sum(1 for r in Y['improve_target_rows'] if r.get('target_ratio') is not None)
    P.append(f"""
<div class="section">
  <h2>二、年度概览</h2>
  <div class="stat-row">
    <div class="stat-card"><div class="num">{appr26}</div><div class="label">2026 审批通过（{Y['unique_programs_2026']} 项目）｜2025 全年 {appr25}（{Y['unique_programs_2025']}）</div></div>
    <div class="stat-card"><div class="num">{Y['ach26_won_projects']}</div><div class="label">FY2026 WON 项目（Achievable 口径）</div></div>
    <div class="stat-card"><div class="num">133</div><div class="label">年度改善目标项（{n_it} 项含目标比例）</div></div>
    <div class="stat-card"><div class="num">{len(Y['fy2526_pairs'])}</div><div class="label">FY25→26 同项目可比对（项目×工艺）</div></div>
    <div class="stat-card"><div class="num">5</div><div class="label">实测CT监控工厂（BJ/SH/CJ/CQ/GZ）</div></div>
  </div>
  <div class="insight-box">
    <b>年度主线：</b>预算端 FA 收紧 21%、IHE/IHR 上调；执行端跨工厂差异显著（重庆 FA Achievable 均值为北京 2.2 倍）；FY25→26 同项目 IHR 平均降 3.6% 改善最快；改善目标达成分化（上海领先、北京 30 项落后）。
  </div>
</div>""")

    # ── 三、预算BOL三类型结构 ──
    bp = {(r['fy'], r['process']): r for r in Y['budget_by_process']}
    at = {(r['fy'], r['type'], r['process']): r for r in Y['achtgt_by_process']}
    tgt26 = [round(at[(2026, 'TARGET', p)]['bol'], 1) for p in procs]
    ach26 = [round(at[(2026, 'ACHIEVABLE', p)]['bol'], 1) for p in procs]
    bud26 = [round(bp[(2026, p)]['bud'], 1) for p in procs]
    P.append(f"""
<div class="section">
  <h2>三、预算 BOL 三类型结构（FY2026）</h2>
  <h3>3.1 按工艺的三类型对比</h3>
  <div class="chart-box sm" id="y-types"></div>
  <div class="chart-legend-hint">Target = 产能规划目标；Achievable = CT/HC 计算可达值；Budget = 年度预算值。柱值为项目均值（min/台）。</div>
  <h3>3.2 FY2025 → FY2026 预算对比</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>工艺</th><th>FY2025 预算均值</th><th>FY2026 预算均值</th><th>变化</th><th>Target→Achievable 降本空间</th><th>FY2026 项目数</th></tr></thead>
    <tbody>""")
    for i, p in enumerate(procs):
        b25, b26 = bp[(2025, p)]['bud'], bp[(2026, p)]['bud']
        chg = (b26 - b25) / b25 * 100
        cls = 'delta-down' if chg < 0 else 'delta-up'
        arrow = '▼' if chg < 0 else '▲'
        gap_ta = ach26[i] - tgt26[i]
        P.append(f"<tr><td>{p}</td><td>{b25:.1f}</td><td>{b26:.1f}</td>"
                 f"<td><span class='{cls}'>{arrow} {abs(chg):.0f}%</span></td>"
                 f"<td>{gap_ta:.1f} min（{(gap_ta / tgt26[i]) * 100:.0f}%）</td><td>{bp[(2026, p)]['n']}</td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>结构解读：</b>FA 预算均值下调 21% 为本财年降本主战场；IHE（+24%）与 IHR（+55%）上调反映大尺寸/复合工艺新产品占比上升。三类型梯度（FA：Target {tgt26[0]} &lt; Achievable {ach26[0]}）显示产能目标严于当前可达水平，牵引方向明确；IHR 的 Achievable（{ach26[2]}）已低于 Target（{tgt26[2]}），为三工艺中唯一"可达优于目标"的板块。
  </div>
</div>""")

    # ── 四、工艺×产品类型总览 ──
    roof_rows = [r for r in Y['ach26_by_roof_won'] if r['n'] >= 5]
    n_hidden = len([r for r in Y['ach26_by_roof_won'] if r['n'] < 5])
    P.append(f"""
<div class="section">
  <h2>四、工艺 × 产品类型 BOL 总览（FY2026 · WON）</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>工艺</th><th>产品类型 (Roof Type)</th><th>项目数</th><th>可信度</th><th>均值 (min)</th><th>Min – Max (min)</th></tr></thead>
    <tbody>""")
    for r in roof_rows:
        conf = CONF_HIGH if r['n'] >= 10 else CONF_MID
        P.append(f"<tr><td>{r['process']}</td><td class='lft'>{esc(r['roof'])}</td><td>{r['n']}</td>"
                 f"<td>{conf}</td><td><b>{r['avg']:.1f}</b></td><td>{r['min']:.1f} – {r['max']:.1f}</td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="insight-box">
    <b>产品复杂度梯度（仅列 n≥5 类型）：</b>FA 中 TLES multi（72.1）&gt; BLTS（35.3）&gt; Fixed panel（28.1）&gt; Rollo（18.5）；IHE 中 Fixed panel（30.6）比 BLTS（16.0）高 91%；IHR Rollo（13.1）样本 8 个。另有 {n_hidden} 个小样本类型（n&lt;5，如 FA TLTS、IHE TLTS 等）按可信度规则不展示结论。
  </div>
</div>""")

    # ── 五、跨工厂总览 ──
    ap = {(r['plant'], r['process']): r for r in Y['ach26_by_plant_process']}
    cf = {'FA': [p for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ'] if (p, 'FA') in ap and ap[(p, 'FA')]['n'] >= 5],
          'IHE': [p for p in ['BJ', 'SH', 'CQ'] if (p, 'IHE') in ap and ap[(p, 'IHE')]['n'] >= 5],
          'IHR': [p for p in ['CJ', 'GZ'] if (p, 'IHR') in ap and ap[(p, 'IHR')]['n'] >= 5]}
    P.append("""
<div class="section">
  <h2>五、跨工厂 BOL 总览（FY2026 Achievable，按工艺）</h2>
  <div class="chart-legend-hint">蓝色柱 = 项目均值，灰色 I 型线 = Min-Max 范围；仅含 n≥5 的工厂（武汉 FA n=1、重庆 IHE n=4 未纳入，见 1.3 规则）。注：此为工厂整体水平，产品组合结构不同，精细对比见第六章。</div>""")
    cross_overview_notes = {
        'FA': '重庆（66.7，n=11）显著最高，北京（30.0，n=27）/广州（25.3，n=10）最低，上海/长春居中（43.6/43.0）。',
        'IHE': '北京（18.2，n=25）与上海（18.5，n=23）高度一致；重庆（29.9）因 n=4 未纳入图示，差异待第六章组合级验证。',
        'IHR': '长春（12.91，n=8）与广州（12.94，n=8）均值几乎一致，广州离散度更大（Max 19.4 vs 13.4）。',
    }
    for i, pr in enumerate(procs):
        pl = cf[pr]
        P.append(f"""
  <h3>5.{i + 1} {pr} 跨工厂总览</h3>
  <div class="chart-box sm" id="y-ov-{pr}"></div>
  <div class="insight-box" style="font-size:.86rem">{cross_overview_notes[pr]}</div>""")
    P.append("</div>")

    # ── 六、跨工厂可比组合深度对比 ──
    P.append("""
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
        diff = (hi['avg'] - lo['avg']) / lo['avg'] * 100
        conf = CONF_HIGH if level == 'high' else CONF_MID
        shown_n = sum(r['n'] for r in rows)
        P.append(f"""
  <h3>6.{idx + 1} {pr} + {esc(roof)}</h3>
  <div class="chart-box sm" id="y-cb-{idx}"></div>""")
        ins = (f"{conf}｜样本 {shown_n} 项（{' / '.join(f'{PLANT_CN[r['plant']]} {r['n']}' for r in rows)}）："
               f"<b>{PLANT_CN[lo['plant']]} {lo['avg']:.2f} min 为标杆</b>，最高 {PLANT_CN[hi['plant']]} {hi['avg']:.2f} min，"
               f"差距 {diff:.1f}%（{hi['avg'] - lo['avg']:.2f} min/台）。")
        if diff < 2:
            ins += " 两厂水平高度一致，可作为跨工厂标准化的最佳实践组合。"
        P.append(f"""  <div class="insight-box" style="font-size:.86rem">{ins}</div>""")
        findings.append({'combo': f'{pr}+{roof}', 'n': shown_n,
                         'lo': f"{PLANT_CN[lo['plant']]} ({lo['avg']:.2f})",
                         'hi': f"{PLANT_CN[hi['plant']]} ({hi['avg']:.2f})",
                         'diff': diff, 'level': level})
        combo_insights.append((key, lo, hi, diff, level))
    # 高可信度发现表
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
        P.append(f"<tr><td class='lft'>{esc(r['name'])}</td><td>{PLANT_CN.get(r['plant'], r['plant'])}</td>"
                 f"<td>{r['process']}</td><td>{r['budget']:.1f}</td><td>{r['actual']:.1f}</td>"
                 f"<td><span class='delta-up'>+{r['gap_pct']:.1f}%</span></td>"
                 f"<td><span class='tag tag-hot'>待核实</span></td></tr>")
    P.append(f"""</tbody></table></div>
  <div class="warn-box">
    <b>口径与数据校验提示：</b>
    <ul class="summary-list">
      <li>上海领先（达标 7 + 优于预算 11，落后仅 4）；<b>北京 30 项落后为全厂最多</b>，需重点推动。</li>
      <li>偏差分布：<b>{buckets['b2']} 项在预算内（−10%~0）</b>、{buckets['b3']} 项小幅超预算（0~10%）、{buckets['b4']} 项超 10% —— 偏差 &gt;10% 的项目建议逐项核实（含爬坡期与跨线匹配因素）后再定改善措施。</li>
      <li>长春 IHR 多个"达标"项实际值远低于预算（0.11~3.61 min），为<b>新项目爬坡期数据</b>，不代表真实达成；T6840 IHE（+220.9%）疑跨产线版本匹配偏差——两者均已隔离标注，不纳入结论。</li>
      <li>{n_no_actual} 项暂无审批实际值（未提报 BOL），未纳入统计；原始明细含 {n_dup} 条重复行已去重。</li>
    </ul>
  </div>
</div>""")

    # ── 八、FY25→26 同项目变化 ──
    fy = Y['fy2526_by_process']
    fy_order = [p for p in procs if p in fy]
    P.append(f"""
<div class="section">
  <h2>八、FY2025 → FY2026 同项目 Achievable 变化</h2>
  <div class="chart-box sm" id="y-fy"></div>
  <div class="chart-legend-hint">两财年均有的（项目×工艺）配对，n={len(Y['fy2526_pairs'])} 对；改善 = BOL 下降 &gt;0.5 min，恶化 = 上升 &gt;0.5 min。</div>
  <div class="insight-box">
    <b>趋势结论（样本量充分，{len(Y['fy2526_pairs'])} 对）：</b>
    <ul class="summary-list">
      <li><b>IHR 改善最快</b>：平均 −3.6%（8 改善 / 6 持平 / 0 恶化，n=14）。</li>
      <li><b>FA 总量最大但略升</b>：平均 +1.1%（12 改善 / 28 持平 / 6 恶化，n=46）——上升主要由 T6875（+17.7）、T7215（+12.4）、T6580（+10.0）三个新平台项目驱动。</li>
      <li><b>IHE 基本持平</b>：−0.2%（5 / 18 / 3，n=26）。</li>
      <li>降幅前三位：T7155 FA −4.57、T6723 FA −4.24、T6764 IHE −3.31 min —— 与第七章改善目标达成相互印证。</li>
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
    P.append(f"""
<div class="section">
  <h2>十、实测CT 年度稳定性（2025-08 ~ 2026-08）</h2>
  <div class="chart-box" id="y-ct"></div>
  <div class="chart-legend-hint">月度值 = 各工厂当月全部（项目×产线）瓶颈CT中位数；空点为当月无数据；线端标注工厂名与最新值。</div>
  <div class="insight-box">
    <ul class="summary-list">
      <li><b>广州持续改善</b>：82.9 → 57.0s（−31%），趋势最健康（T6241 极端值不影响中位数）。</li>
      <li><b>上海最稳定</b>：13 个月稳定于 104-115s 窄幅区间；重庆（有数据月份）稳定于 100s 附近。</li>
      <li><b>北京高位波动</b>（90-179s），与其超标产线集中一致（见季度报告第三章），需按产线专项分解。</li>
      <li><b>长春 6 月后骤降</b>（199 → 37 → 26s）：疑产线切换或采集配置变化，<b>口径确认前不解读为改善</b>。</li>
    </ul>
  </div>
</div>""")

    # ── 十一、KPI速览 ──
    km = Y['kpi_monthly']
    aug_kpi = km.get('BOL Reduction Rate', {}).get('2026-08', {})
    upd_kpi = km.get('BOL Updates Rate', {}).get('2026-08', {})
    ct_kpi = km.get('Acutal CT Rate', {}).get('2026-08', {})
    P.append(f"""
<div class="section">
  <h2>十一、IE KPI 达成速览（2026-08）</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>工厂</th><th>BOL Reduction Rate</th><th>BOL Updates Rate</th><th>Actual CT Rate</th><th>LB</th></tr></thead>
    <tbody>""")
    for p in ['BJ', 'SH', 'CJ', 'CQ', 'GZ']:
        red = aug_kpi.get(p)
        upd = upd_kpi.get(p)
        ctr = ct_kpi.get(p)
        lbv = next((k['v'] for k in Q['kpi_lb'] if k['ym'] == '2026-08' and k['plant'] == p), None)
        P.append(f"<tr><td>{PLANT_CN[p]}</td>"
                 f"<td>{f'{red * 100:.2f}%' if red is not None else '—'}</td>"
                 f"<td>{f'{upd * 100:.1f}%' if upd is not None else '—'}</td>"
                 f"<td>{f'{ctr * 100:.1f}%' if ctr is not None else '—'}</td>"
                 f"<td>{f'{lbv * 100:.1f}%' if lbv else '—'}</td></tr>")
    P.append("""</tbody></table></div>
  <div class="insight-box">
    BOL Reduction Rate 全厂 0.1%-2.6%（最高重庆 2.57%），距年度 7% 级目标差距明显，下半年需加速；BOL Updates Rate 上海 72.9% / 长春 70.0% 领先，北京 23.5%、广州 9.1% 偏低，与季度报告审批活跃度相互印证。KPI 月度连续记录自 2026-06 起，年度趋势判断待年末复核。
  </div>
</div>""")

    # ── 十二、综合洞察与建议 ──
    bench_lines = []
    for (key, lo, hi, diff, level) in combo_insights:
        if diff >= 2:
            bench_lines.append(
                f"<li><b>{key[0]}+{esc(key[1])}</b>：以{PLANT_CN[lo['plant']]}（{lo['avg']:.2f} min，n={lo['n']}）为标杆，"
                f"{PLANT_CN[hi['plant']]}（{hi['avg']:.2f}）单台收敛空间 {hi['avg'] - lo['avg']:.2f} min"
                f"（{CONF_HIGH if level == 'high' else CONF_MID}）。</li>")
    P.append(f"""
<div class="section">
  <h2>十二、综合洞察与改进建议</h2>
  <h3>12.1 核心洞察</h3>
  <div class="insight-box">
    <ul class="summary-list">
      <li><b>预算结构：</b>FA 降 21% / IHE 升 24% / IHR 升 55% —— 降本压力集中于 FA，新产品复杂度向 IHE/IHR 迁移（第三章）。</li>
      <li><b>跨工厂：</b>剔除产品结构后，北京在 FA+BLTS 与 IHE+BLTS 两大高样本组合中均为或接近标杆（第六章）；工厂整体均值差异（第五章）主要来自产品组合。</li>
      <li><b>目标达成：</b>上海"达标+优于预算"18 项居首；北京 30 项落后 + 瓶颈CT高位，为年度改善首要工厂（第七章）。</li>
      <li><b>同项目趋势：</b>FY25→26 IHR −3.6% 改善最快、FA +1.1% 略升（三个新平台项目驱动）（第八章）。</li>
      <li><b>报价对齐：</b>实际BOL/QWS 中位覆盖 99.6%，80-100% 区间占 74%，整体对齐良好（第九章）。</li>
    </ul>
  </div>
  <h3>12.2 标杆与收敛空间（基于第六章高可信组合）</h3>
  <div class="insight-box">
    <ul class="summary-list">{''.join(bench_lines)}</ul>
  </div>
  <h3>12.3 下年度（FY2027）行动建议</h3>
  <div class="warn-box">
    <ul class="summary-list">
      <li><b>对标专项：</b>第六章各组合落后工厂按"标杆值 + 产品结构校正"设定分阶段目标（先核产品类型/自动化差异，再定收敛幅度）。</li>
      <li><b>北京改善攻坚：</b>将 30 项落后目标与超标产线合并为工厂级改善清单，纳入跟踪模块按月复盘。</li>
      <li><b>预算编制：</b>FY2027 以第四章产品类型均值（n≥5）为基准线，按工厂产品组合校正预算，减少结构性偏差。</li>
      <li><b>数据治理：</b>长春 7-8 月 CT 口径确认、爬坡期项目达成判定规则、QWS 覆盖比 &gt;100% 项目的报价口径对账、未提报项目催报机制。</li>
      <li><b>机制建设：</b>季度报告（异常识别）+ 年度报告（结构对标）固定节奏，季度跟踪年度目标完成率；第六章"样本积累中"组合达标后自动纳入对比。</li>
    </ul>
  </div>
</div>
<div class="report-footer">
  BOL 管理系统 · 年度分析报告（模版示例：2026 年 1-8 月） | Generated by Trae Work | 数据截至 {GEN_DATE} | 年度口径：自然年 | 可信度规则见 1.3
</div>""")

    # ── 图表JS ──
    js = f"""
barChart('y-types', 'FY2026 三类型 BOL 均值（按工艺）', 'Target / Achievable（AchTgtBol）· Budget（BudgetBol）',
  {jd(procs)}, [
    {{name:'Target', data:{jd(tgt26)}, color:'#1a3a6e', label:true}},
    {{name:'Achievable', data:{jd(ach26)}, color:'#5b8bc9', label:true}},
    {{name:'Budget', data:{jd(bud26)}, color:'#e07a5f', label:true}}]);
"""
    for pr in procs:
        pl = cf[pr]
        js += f"""
crossChart('y-ov-{pr}', '{pr} 跨工厂总览（FY2026 Achievable）', {jd('样本：' + ', '.join(f"{PLANT_CN[p]} n={ap[(p, pr)]['n']}" for p in pl))},
  {jd([PLANT_CN[p] for p in pl])}, {jd([round(ap[(p, pr)]['avg'], 1) for p in pl])},
  {jd([round(ap[(p, pr)]['min'], 1) for p in pl])}, {jd([round(ap[(p, pr)]['max'], 1) for p in pl])}, 'min');
"""
    for idx, (key, plants_ok, level) in enumerate(combos_show):
        rows = sorted([combo[key][p] for p in plants_ok], key=lambda r: r['avg'])
        js += f"""
crossChart('y-cb-{idx}', '{key[0]} + {key[1]} 跨工厂对比', {jd('样本：' + ', '.join(f"{PLANT_CN[r['plant']]} n={r['n']}" for r in rows))},
  {jd([f"{PLANT_CN[r['plant']]}\\n(n={r['n']})" for r in rows])}, {jd([r['avg'] for r in rows])},
  {jd([r['min'] for r in rows])}, {jd([r['max'] for r in rows])}, 'min');
"""
    t_series = []
    for sk, sn, sc in states:
        t_series.append(f"{{name:'{sn}', data:{jd([itp.get(p, {}).get(sk, 0) for p in order])}, color:'{sc}'}}")
    js += f"""
stackChart('y-target', '各工厂改善目标达成状态（2026）', 'improveTarget × 最近审批实际BOL（去重）',
  {jd([PLANT_CN[p] for p in order])}, [{', '.join(t_series)}]);
barChart('y-bucket', '实际 vs 预算偏差分布', '去重后可比项，按超预算幅度分桶',
  ['优于预算\n(≤−10%)', '预算内\n(−10%~0)', '小幅超出\n(0~10%)', '超出>10%'], [
    {{name:'项目数', data:{jd([buckets['b1'], buckets['b2'], buckets['b3'], buckets['b4']])}, color:'#2e5aac'}}], {{yName:'项'}});
barChart('y-fy', 'FY2025→FY2026 同项目变化方向（按工艺）', {jd('配对 n=' + str(len(Y['fy2526_pairs'])))},
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
        ct_series.append(f"{{name:'{PLANT_CN[p]}', data:{jd(bn['series'].get(p))}, color:'{ct_colors[p]}', endLabel:true}}")
    js += f"""
lineChart('y-ct', '各工厂月度瓶颈CT中位数趋势', '2025-08 ~ 2026-08（秒）', {jd(bn['months'])},
  [{', '.join(ct_series)}], {{y:120, label:'120s'}});
"""
    return page('BOL 年度分析报告 · 2026（1-8月）', ''.join(P), js)


if __name__ == '__main__':
    qf = os.path.join(OUT, 'BOL_Quarterly_Report_2026Q2.html')
    yf = os.path.join(OUT, 'BOL_Annual_Report_2026.html')
    with open(qf, 'w', encoding='utf-8') as f:
        f.write(build_quarter())
    with open(yf, 'w', encoding='utf-8') as f:
        f.write(build_year())
    print('written:', qf, os.path.getsize(qf))
    print('written:', yf, os.path.getsize(yf))

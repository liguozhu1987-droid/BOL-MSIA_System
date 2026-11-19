# -*- coding: utf-8 -*-
"""改善机会分析周报 HTML 报告生成器

生成图文并茂的 HTML 报告，用于邮件推送。

数据来源：
  - BolOverView（BOL更新记录）
  - BolOverViewByProcess（按工艺拆分的BOL详情）
  - BottleNeckCt（瓶颈工位CT）

数据计算逻辑与 LowLbAnalysisView 一致：
  - 仅统计 final_approve_status='Approved' 的记录
  - 按 (program_code, process) 分组，取 update_time 最新的一条
  - CT/HC 取 sum，LB 取 avg
  - 有效工作量 = HC * LB
  - 潜在减人 = HC - 有效工作量/0.85
  - 保守方案：减 floor(潜在减人) 人，需 LB ≤ 91% 才可行
  - 激进方案：最大可减 = HC - ceil(有效工作量/0.91)

HTML 样式说明：
  - 浅蓝色科技风（主色 #0ea5e9，深色 #0284c7，浅色 #38bdf8）
  - 所有 CSS 内联（邮件兼容，Outlook 友好）
  - 不使用 flex/grid/JavaScript 等现代特性
"""
import math
import datetime
from decimal import Decimal
from collections import defaultdict

from apps.dynamic_bol.models import BolOverView, BolOverViewByProcess, FineUser
from apps.actual_ct.models import RealCtExtract, BottleNeckCt
from bol_platform.plant_utils import normalize_plant


# 改善机会目标线平衡率
TARGET_LB = Decimal('0.85')
# 改善后 LB 上限：91%（超过 91% 因人机配合工位难以实现）
MAX_ACHIEVABLE_LB = Decimal('0.91')


# ============================================================
# 数据收集函数
# ============================================================
def _collect_low_lb_items():
    """收集 LB < 0.85 的项目列表（与 LowLbAnalysisView 一致的计算逻辑）

    使用 values() 而非完整对象，减少内存占用。

    Returns:
        items: 排序后的项目列表（按 LB 升序），每项含 hc/lb/改善机会等字段
        total_projects: 项目总数（含 LB ≥ 阈值的项目）
    """
    # 1. 查询所有审批通过的 BOL 编号 + 项目名称 + 客户
    bol_qs = BolOverView.objects.filter(final_approve_status='Approved')
    bol_meta = {}
    bol_nrs = []
    for b in bol_qs.values('bol_nr', 'program_name', 'customer'):
        bol_nrs.append(b['bol_nr'])
        # 同一 bol_nr 可能有多条，取第一条非空
        if b['bol_nr'] not in bol_meta:
            bol_meta[b['bol_nr']] = {
                'program_name': b['program_name'] or '',
                'customer': b['customer'] or '',
            }
        else:
            if not bol_meta[b['bol_nr']]['program_name'] and b['program_name']:
                bol_meta[b['bol_nr']]['program_name'] = b['program_name']
            if not bol_meta[b['bol_nr']]['customer'] and b['customer']:
                bol_meta[b['bol_nr']]['customer'] = b['customer']

    if not bol_nrs:
        return [], 0

    # 2. 查询 byProcess 详细数据，按 bol_nr 聚合：CT/HC 取 sum，LB 取 avg
    bp_qs = BolOverViewByProcess.objects.filter(bol_nr__in=bol_nrs)
    bp_agg = defaultdict(lambda: {
        'ct_sum': Decimal(0), 'hc_sum': Decimal(0),
        'lb_list': [], 'bottleneck': '',
        'program_code': '', 'process': '', 'line_nr': '',
        'location': '', 'update_time': None,
        'version': '', 'bol_nr': '',
    })
    for bp in bp_qs:
        key = bp.bol_nr
        bp_agg[key]['program_code'] = bp.program_code
        bp_agg[key]['process'] = bp.process
        bp_agg[key]['line_nr'] = bp.line_nr
        bp_agg[key]['location'] = bp.location
        bp_agg[key]['version'] = bp.version or ''
        bp_agg[key]['bol_nr'] = bp.bol_nr
        if bp.update_time and (not bp_agg[key]['update_time'] or bp.update_time > bp_agg[key]['update_time']):
            bp_agg[key]['update_time'] = bp.update_time
        if bp.ct is not None:
            bp_agg[key]['ct_sum'] += bp.ct
        if bp.hc is not None:
            bp_agg[key]['hc_sum'] += bp.hc
        if bp.lb_rate is not None:
            bp_agg[key]['lb_list'].append(bp.lb_rate)
        if bp.bottle_neck_station and not bp_agg[key]['bottleneck']:
            bp_agg[key]['bottleneck'] = bp.bottle_neck_station

    # 3. 按 (program_code, process) 分组，取 update_time 最新的一条
    proj_latest = {}
    for bol_nr, agg in bp_agg.items():
        pc = agg['program_code']
        proc = agg['process']
        if not pc or not proc:
            continue
        key = (pc, proc)
        existing = proj_latest.get(key)
        if not existing or (agg['update_time'] and (not existing['update_time'] or agg['update_time'] > existing['update_time'])):
            lb_list = agg['lb_list']
            lb_avg = (sum(lb_list) / len(lb_list)) if lb_list else None
            meta = bol_meta.get(bol_nr, {})
            proj_latest[key] = {
                'program_code': pc,
                'program_name': meta.get('program_name', ''),
                'customer': meta.get('customer', ''),
                'process': proc,
                'line_nr': agg['line_nr'],
                'location': agg['location'],
                'version': agg['version'],
                'ct': float(agg['ct_sum']),
                'hc': float(agg['hc_sum']),
                'lb': float(lb_avg) if lb_avg is not None else None,
                'bottleneck': agg['bottleneck'],
                'update_time': agg['update_time'],
            }

    # 4. 筛选 LB < 阈值的项目，计算改善机会
    max_lb_float = float(MAX_ACHIEVABLE_LB)
    threshold_float = float(TARGET_LB)
    items = []
    for key, v in proj_latest.items():
        lb = v['lb']
        hc = v['hc']
        if lb is None or hc is None or hc <= 0 or lb <= 0:
            continue
        if lb >= threshold_float:
            continue

        # 有效工作量 = HC * LB
        effective_work = hc * lb
        # 若 LB 提升至目标值，所需 HC
        hc_at_target = effective_work / threshold_float
        # 潜在减人（小数）
        potential_reduce = hc - hc_at_target

        # 保守方案：减 floor(潜在减人) 人，需达到的 LB 不超过 91%
        reduce_conservative = math.floor(potential_reduce) if potential_reduce >= 1 else 0
        hc_conservative = hc - reduce_conservative
        lb_needed_conservative = (effective_work / hc_conservative) if hc_conservative > 0 else None
        conservative_feasible = (
            reduce_conservative > 0
            and lb_needed_conservative is not None
            and lb_needed_conservative <= max_lb_float
        )

        # 激进方案：在 LB ≤ 91% 前提下，最大可减人数
        min_hc_at_max_lb = math.ceil(effective_work / max_lb_float)
        reduce_aggressive = int(hc - min_hc_at_max_lb) if min_hc_at_max_lb < hc else 0
        hc_aggressive = hc - reduce_aggressive
        lb_needed_aggressive = (effective_work / hc_aggressive) if hc_aggressive > 0 else None
        aggressive_feasible = (
            reduce_aggressive > 0
            and lb_needed_aggressive is not None
            and lb_needed_aggressive <= max_lb_float
            and hc_aggressive > 0
        )

        items.append({
            'program_code': v['program_code'],
            'program_name': v['program_name'],
            'customer': v['customer'],
            'process': v['process'],
            'line_nr': v['line_nr'],
            'location': normalize_plant(v['location']) if v['location'] else '',
            'hc': round(hc, 2),
            'lb': round(lb, 4),
            'lb_percent': round(lb * 100, 2),
            'ct': round(v['ct'], 2),
            'bottleneck': v['bottleneck'],
            'effective_work': round(effective_work, 2),
            'potential_reduce': round(potential_reduce, 2),
            'conservative_reduce': reduce_conservative,
            'conservative_feasible': conservative_feasible,
            'aggressive_reduce': reduce_aggressive,
            'aggressive_feasible': aggressive_feasible,
            'update_time': v['update_time'].strftime('%Y-%m-%d') if v['update_time'] else '',
        })

    # 按 LB 升序排列（LB 最低的在前）
    items.sort(key=lambda x: x['lb'])
    return items, len(proj_latest)


def _collect_approval_dynamics():
    """收集最近7天的BOL审批动态

    Returns:
        dict: {
            'approved_count': 审批通过数,
            'rejected_count': 审批驳回数,
            'by_process': [(process, count), ...],  # 审批通过项目按工艺分布
        }
    """
    now = datetime.datetime.now()
    seven_days_ago = now - datetime.timedelta(days=7)

    qs = BolOverView.objects.filter(submit_date__gte=seven_days_ago)
    approved_qs = qs.filter(final_approve_status='Approved')
    rejected_count = qs.filter(final_approve_status='Rejected').count()
    approved_count = approved_qs.count()

    # 按 process 分组统计审批通过的项目数（Python 层聚合，避免引入额外 ORM 注解）
    process_counter = defaultdict(int)
    for r in approved_qs.values('process'):
        proc = r['process'] or '未知'
        process_counter[proc] += 1

    by_process = sorted(process_counter.items(), key=lambda x: -x[1])
    return {
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'by_process': by_process,
    }


def _collect_abnormal_ct():
    """收集瓶颈CT超过120秒的异常项目（Top10）

    BottleNeckCt 表可能很大，使用切片限制结果集。

    Returns:
        list: 异常项目列表，每项含 project_name/line_nr/company/cycle_time_bottleneck
    """
    # 先过滤 > 120 的记录，再按 cycle_time_bottleneck 降序取前 10
    qs = BottleNeckCt.objects.filter(
        cycle_time_bottleneck__gt=120
    ).order_by('-cycle_time_bottleneck')[:10]
    items = []
    for r in qs.values('project_name', 'project_code', 'line_nr', 'company', 'cycle_time_bottleneck'):
        items.append({
            'project_name': r['project_name'] or r['project_code'] or '',
            'line_nr': r['line_nr'] or '',
            'company': normalize_plant(r['company']) if r['company'] else '',
            'cycle_time_bottleneck': float(r['cycle_time_bottleneck']) if r['cycle_time_bottleneck'] else 0.0,
        })
    return items


# ============================================================
# HTML 渲染辅助函数
# ============================================================
def _lb_color(lb_percent):
    """根据 LB 百分比返回颜色

    LB < 70%: 红色 #ef4444
    70%-85%: 橙色 #f59e0b
    """
    if lb_percent < 70:
        return '#ef4444'
    return '#f59e0b'


def _escape(text):
    """HTML 转义，防止项目名称等含特殊字符破坏 HTML 结构"""
    if not text:
        return ''
    text = str(text)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text


def generate_improvement_report_html():
    """生成改善机会分析周报 HTML

    生成邮件兼容的 HTML 字符串，包含：
      1. 报告头部（标题/日期范围/生成时间）
      2. 概览汇总卡片（4 个指标）
      3. 改善机会 Top10 表格
      4. BOL 审批动态（近 7 天）
      5. 实测 CT 异常项目
      6. 改善建议总结

    Returns:
        str: HTML 字符串
    """
    # === 数据收集 ===
    items, total_projects = _collect_low_lb_items()
    approval = _collect_approval_dynamics()
    abnormal_ct = _collect_abnormal_ct()

    # 汇总统计
    low_lb_count = len(items)
    total_hc = sum(it['hc'] for it in items)
    total_potential_reduce = sum(it['potential_reduce'] for it in items)
    top10 = items[:10]

    # 日期范围
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # === HTML 拼装 ===
    html_parts = []
    html_parts.append(
        '<!DOCTYPE html>'
        '<html lang="zh-CN">'
        '<head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>BOL管理系统 - 改善机会分析周报</title>'
        '</head>'
        '<body style="margin:0;padding:0;background-color:#f1f5f9;'
        'font-family:\'Microsoft YaHei\',\'Segoe UI\',Arial,sans-serif;'
        'color:#0f172a;font-size:14px;line-height:1.6;">'
    )

    # 主容器：max-width 800px 居中
    html_parts.append(
        '<div style="max-width:800px;margin:0 auto;padding:20px;background-color:#ffffff;">'
    )

    # === 1. 报告头部 ===
    html_parts.append(
        '<div style="background-color:#0ea5e9;background-image:linear-gradient(135deg,#0ea5e9 0%,#0284c7 100%);'
        'padding:24px;color:#ffffff;border-radius:8px 8px 0 0;">'
        '<h1 style="margin:0 0 8px 0;font-size:22px;font-weight:bold;">BOL 管理系统 - 改善机会分析周报</h1>'
        '<div style="font-size:13px;color:#f0f9ff;">'
        f'<span>报告周期：{week_ago.strftime("%Y-%m-%d")} ~ {today.strftime("%Y-%m-%d")}</span>'
        '&nbsp;&nbsp;|&nbsp;&nbsp;'
        f'<span>生成时间：{now_str}</span>'
        '</div>'
        '</div>'
    )

    # === 2. 概览汇总卡片 ===
    html_parts.append(
        '<div style="margin:16px 0;">'
        '<h2 style="font-size:16px;color:#0284c7;border-left:4px solid #0ea5e9;'
        'padding-left:8px;margin:0 0 12px 0;">概览汇总</h2>'
        '<table style="width:100%;border-collapse:separate;border-spacing:8px 0;">'
        '<tr>'
        f'<td style="width:25%;background-color:#0ea5e9;padding:14px 10px;text-align:center;border-radius:6px;">'
        f'<div style="color:#ffffff;font-size:12px;margin-bottom:4px;">总项目数</div>'
        f'<div style="color:#ffffff;font-size:22px;font-weight:bold;">{total_projects}</div>'
        '</td>'
        f'<td style="width:25%;background-color:#ef4444;padding:14px 10px;text-align:center;border-radius:6px;">'
        f'<div style="color:#ffffff;font-size:12px;margin-bottom:4px;">低LB项目数</div>'
        f'<div style="color:#ffffff;font-size:22px;font-weight:bold;">{low_lb_count}</div>'
        '</td>'
        f'<td style="width:25%;background-color:#f59e0b;padding:14px 10px;text-align:center;border-radius:6px;">'
        f'<div style="color:#ffffff;font-size:12px;margin-bottom:4px;">低LB总人数</div>'
        f'<div style="color:#ffffff;font-size:22px;font-weight:bold;">{round(total_hc, 1)}</div>'
        '</td>'
        f'<td style="width:25%;background-color:#10b981;padding:14px 10px;text-align:center;border-radius:6px;">'
        f'<div style="color:#ffffff;font-size:12px;margin-bottom:4px;">潜在减人总数</div>'
        f'<div style="color:#ffffff;font-size:22px;font-weight:bold;">{round(total_potential_reduce, 1)}</div>'
        '</td>'
        '</tr>'
        '</table>'
        '</div>'
    )

    # === 3. 改善机会 Top10 表格 ===
    html_parts.append(
        '<div style="margin:20px 0;">'
        '<h2 style="font-size:16px;color:#0284c7;border-left:4px solid #0ea5e9;'
        'padding-left:8px;margin:0 0 12px 0;">改善机会 Top10（LB 最低）</h2>'
        '<table style="width:100%;border-collapse:collapse;font-size:12px;background-color:#ffffff;">'
        '<thead>'
        '<tr style="background-color:#0284c7;color:#ffffff;">'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:left;width:7%;">项目编码</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:left;width:14%;">项目名称</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:left;width:8%;">客户</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:left;width:5%;">工艺</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:5%;">工厂</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:6%;">产线</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:6%;">当前HC</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:7%;">当前LB</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:left;width:9%;">瓶颈工位</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:8%;">有效工作量</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:8%;">潜在减人</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:8%;">保守方案</th>'
        '<th style="padding:8px 6px;border:1px solid #0284c7;text-align:center;width:8%;">激进方案</th>'
        '</tr>'
        '</thead>'
        '<tbody>'
    )

    if top10:
        for idx, it in enumerate(top10):
            # 斑马纹
            bg = '#f8fafc' if idx % 2 == 1 else '#ffffff'
            lb_pct = it['lb_percent']
            lb_color = _lb_color(lb_pct)
            # 保守方案：可行显示绿色，不可行显示灰色
            cons_color = '#10b981' if it['conservative_feasible'] else '#94a3b8'
            cons_text = f"-{it['conservative_reduce']}人" + ('' if it['conservative_feasible'] else '(不可行)')
            # 激进方案
            aggr_color = '#10b981' if it['aggressive_feasible'] else '#94a3b8'
            aggr_text = f"-{it['aggressive_reduce']}人" + ('' if it['aggressive_feasible'] else '(不可行)')

            html_parts.append(
                f'<tr style="background-color:{bg};">'
                f'<td style="padding:6px;border:1px solid #e2e8f0;">{_escape(it["program_code"])}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;">{_escape(it["program_name"]) or "-"}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;">{_escape(it["customer"]) or "-"}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;">{_escape(it["process"])}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;">{_escape(it["location"]) or "-"}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;">{_escape(it["line_nr"]) or "-"}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;">{it["hc"]}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;color:{lb_color};font-weight:bold;">{lb_pct}%</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;">{_escape(it["bottleneck"]) or "-"}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;">{it["effective_work"]}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;color:#10b981;font-weight:bold;">{it["potential_reduce"]}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;color:{cons_color};">{cons_text}</td>'
                f'<td style="padding:6px;border:1px solid #e2e8f0;text-align:center;color:{aggr_color};">{aggr_text}</td>'
                f'</tr>'
            )
    else:
        html_parts.append(
            '<tr><td colspan="13" style="padding:16px;text-align:center;color:#94a3b8;">'
            '暂无低 LB 项目数据</td></tr>'
        )

    html_parts.append('</tbody></table></div>')

    # === 4. BOL 审批动态 ===
    # 4.1 审批数量统计卡片
    html_parts.append(
        '<div style="margin:20px 0;">'
        '<h2 style="font-size:16px;color:#0284c7;border-left:4px solid #0ea5e9;'
        'padding-left:8px;margin:0 0 12px 0;">BOL 审批动态（近 7 天）</h2>'
        '<table style="width:100%;border-collapse:collapse;margin-bottom:12px;">'
        '<tr>'
        f'<td style="width:50%;background-color:#10b981;padding:12px;text-align:center;border-radius:6px 0 0 6px;">'
        f'<div style="color:#ffffff;font-size:12px;">审批通过</div>'
        f'<div style="color:#ffffff;font-size:20px;font-weight:bold;">{approval["approved_count"]}</div>'
        '</td>'
        f'<td style="width:50%;background-color:#ef4444;padding:12px;text-align:center;border-radius:0 6px 6px 0;">'
        f'<div style="color:#ffffff;font-size:12px;">审批驳回</div>'
        f'<div style="color:#ffffff;font-size:20px;font-weight:bold;">{approval["rejected_count"]}</div>'
        '</td>'
        '</tr>'
        '</table>'
    )

    # 4.2 按工艺分布表格
    html_parts.append(
        '<div style="font-size:13px;color:#475569;margin:8px 0;">按工艺分布（审批通过项目数）：</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
        '<thead>'
        '<tr style="background-color:#0284c7;color:#ffffff;">'
        '<th style="padding:6px 10px;border:1px solid #0284c7;text-align:left;width:70%;">工艺</th>'
        '<th style="padding:6px 10px;border:1px solid #0284c7;text-align:center;width:30%;">通过数</th>'
        '</tr>'
        '</thead>'
        '<tbody>'
    )

    if approval['by_process']:
        for idx, (proc, count) in enumerate(approval['by_process'][:10]):
            bg = '#f8fafc' if idx % 2 == 1 else '#ffffff'
            html_parts.append(
                f'<tr style="background-color:{bg};">'
                f'<td style="padding:6px 10px;border:1px solid #e2e8f0;">{_escape(proc)}</td>'
                f'<td style="padding:6px 10px;border:1px solid #e2e8f0;text-align:center;">{count}</td>'
                f'</tr>'
            )
    else:
        html_parts.append(
            '<tr><td colspan="2" style="padding:12px;text-align:center;color:#94a3b8;">'
            '本周无审批通过记录</td></tr>'
        )

    html_parts.append('</tbody></table></div>')

    # === 5. 实测 CT 异常项目 ===
    html_parts.append(
        '<div style="margin:20px 0;">'
        '<h2 style="font-size:16px;color:#0284c7;border-left:4px solid #0ea5e9;'
        'padding-left:8px;margin:0 0 12px 0;">实测 CT 异常项目（瓶颈 CT &gt; 120s）</h2>'
        '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
        '<thead>'
        '<tr style="background-color:#0284c7;color:#ffffff;">'
        '<th style="padding:8px 10px;border:1px solid #0284c7;text-align:left;width:50%;">项目名称</th>'
        '<th style="padding:8px 10px;border:1px solid #0284c7;text-align:center;width:15%;">工厂</th>'
        '<th style="padding:8px 10px;border:1px solid #0284c7;text-align:center;width:20%;">产线</th>'
        '<th style="padding:8px 10px;border:1px solid #0284c7;text-align:center;width:15%;">瓶颈CT</th>'
        '</tr>'
        '</thead>'
        '<tbody>'
    )

    if abnormal_ct:
        for idx, ct in enumerate(abnormal_ct):
            bg = '#f8fafc' if idx % 2 == 1 else '#ffffff'
            ct_val = ct['cycle_time_bottleneck']
            # >150s 红色，120-150s 橙色
            ct_color = '#ef4444' if ct_val > 150 else '#f59e0b'
            html_parts.append(
                f'<tr style="background-color:{bg};">'
                f'<td style="padding:6px 10px;border:1px solid #e2e8f0;">{_escape(ct["project_name"])}</td>'
                f'<td style="padding:6px 10px;border:1px solid #e2e8f0;text-align:center;">{_escape(ct["company"]) or "-"}</td>'
                f'<td style="padding:6px 10px;border:1px solid #e2e8f0;text-align:center;">{_escape(ct["line_nr"])}</td>'
                f'<td style="padding:6px 10px;border:1px solid #e2e8f0;text-align:center;color:{ct_color};font-weight:bold;">{ct_val:.2f}s</td>'
                f'</tr>'
            )
    else:
        html_parts.append(
            '<tr><td colspan="4" style="padding:12px;text-align:center;color:#94a3b8;">'
            '暂无瓶颈 CT 异常项目</td></tr>'
        )

    html_parts.append('</tbody></table></div>')

    # === 6. 改善建议总结 ===
    suggestions = []
    if low_lb_count > 0:
        suggestions.append(
            f'当前共有 <strong style="color:#ef4444;">{low_lb_count}</strong> 个项目 LB 低于 85%，'
            f'潜在可减人 <strong style="color:#10b981;">{round(total_potential_reduce, 1)}</strong> 人，'
            '建议优先改善 LB 低于 70% 的项目。'
        )
    if top10:
        lowest = top10[0]
        suggestions.append(
            f'LB 最低的项目为 <strong>{_escape(lowest["program_name"]) or _escape(lowest["program_code"])}</strong>'
            f'（{_escape(lowest["process"])}），当前 LB 仅 '
            f'<strong style="color:#ef4444;">{lowest["lb_percent"]}%</strong>，'
            '建议立即开展线平衡优化。'
        )
    if approval['rejected_count'] > 0:
        suggestions.append(
            f'本周共有 <strong style="color:#f59e0b;">{approval["rejected_count"]}</strong> 条 BOL 申请被驳回，'
            '建议核查驳回原因并跟进。'
        )
    if abnormal_ct:
        suggestions.append(
            f'共识别 <strong style="color:#ef4444;">{len(abnormal_ct)}</strong> 个项目瓶颈 CT 超过 120s，'
            '建议优先排查瓶颈工位并制定改善方案。'
        )
    if not suggestions:
        suggestions.append('当前各项指标正常，建议继续保持监控。')

    sug_html = ''.join(f'<li style="margin-bottom:8px;">{s}</li>' for s in suggestions)
    html_parts.append(
        '<div style="margin:20px 0;background-color:#f0f9ff;border:1px solid #bae6fd;'
        'border-radius:6px;padding:14px 18px;">'
        '<h2 style="font-size:16px;color:#0284c7;margin:0 0 10px 0;">改善建议总结</h2>'
        f'<ul style="margin:0;padding-left:20px;color:#0c4a6e;">{sug_html}</ul>'
        '</div>'
    )

    # === 报告页脚 ===
    html_parts.append(
        '<div style="margin-top:20px;padding-top:12px;border-top:1px solid #e2e8f0;'
        'font-size:11px;color:#94a3b8;text-align:center;">'
        '本报告由 BOL 管理系统自动生成 | '
        '数据来源：HRDB（CN_IE_BOLOverView / CN_IE_BOLOverView_byProcess / CN_IE_CT_bottleNeck_list）'
        '</div>'
    )

    # 关闭主容器和 HTML
    html_parts.append('</div></body></html>')

    return ''.join(html_parts)

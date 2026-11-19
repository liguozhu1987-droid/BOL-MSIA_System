# -*- coding: utf-8 -*-
"""BOL系统 季度/年度报告 数据提取脚本
季度: Q2 2026 (2026-04-01 ~ 2026-06-30) 最近完整自然季度
年度: 2026 YTD (截至最新数据) 对比 2025
输出: quarter_data.json / year_data.json
"""
import configparser
import datetime as dt
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pyodbc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from apps.analytics.bol_aggregation import aggregate_bol_rows

CFG = configparser.ConfigParser()
CFG.read(r'c:\WorkFile\D\OPEX\04-Digital_development\2026\IE系统完善开发\BOL管理系统\backend\db_config.ini', encoding='utf-8')

CONN_STR = (
    f"DRIVER={{{CFG['database']['driver']}}};"
    f"SERVER={CFG['database']['host']};"
    f"UID={CFG['database']['user']};"
    f"PWD={CFG['database']['password']};"
    f"DATABASE=HRDB;TrustServerCertificate=yes;Encrypt=no;"
)

TODAY = dt.date(2026, 8, 30)

# ── 工厂标准化 (复制 plant_utils 逻辑) ─────────────────────────
PLANT_ALIASES = {
    'CJ': ['cj', 'cj inalfa', 'cc', 'changchun'],
    'BJ': ['bj', 'bj inalfa', 'beijing'],
    'SH': ['sh', 'sh inalfa', 'shanghai'],
    'CQ': ['cq', 'cq inalfa', 'chongqing'],
    'GZ': ['gz', 'gz inalfa', 'guangzhou'],
    'WH': ['wh', 'wh inalfa', 'wuhan'],
    'CMC': ['cmc', 'cmc inalfa'],
    'YT': ['yt', 'yt inalfa'],
}
_ALIAS = {}
for _std, _al in PLANT_ALIASES.items():
    for _a in _al:
        _ALIAS[_a] = _std
PLANT_NAME = {'BJ': 'Beijing', 'SH': 'Shanghai', 'CJ': 'Changchun',
              'CQ': 'Chongqing', 'GZ': 'Guangzhou', 'WH': 'Wuhan',
              'CMC': 'CMC', 'YT': 'Yantai'}


def norm_plant(raw):
    if not raw:
        return ''
    base = str(raw).strip().split('_')[0].strip()
    return _ALIAS.get(base.lower(), base)


def f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def d2s(x):
    return x.strftime('%Y-%m-%d') if x else None


def dt2s(x):
    return x.strftime('%Y-%m-%d %H:%M') if x else None


def median_ad(vals):
    vs = sorted(vals)
    n = len(vs)
    if n == 0:
        return None
    if n % 2:
        return vs[n // 2]
    return (vs[n // 2 - 1] + vs[n // 2]) / 2


def quartiles(vals):
    """返回 min/q1/median/q3/max"""
    vs = sorted(vals)
    n = len(vs)
    if n == 0:
        return None
    med = median_ad(vs)
    half = n // 2
    lower = vs[:half]
    upper = vs[half + (n % 2):]
    q1 = median_ad(lower) if lower else vs[0]
    q3 = median_ad(upper) if upper else vs[-1]
    return [vs[0], q1, med, q3, vs[-1]]


# ════════════════════════════════════════════════════════════════
def main():
    cn = pyodbc.connect(CONN_STR, timeout=20)
    cur = cn.cursor()

    def use(db):
        cur.execute(f"USE {db}")

    def rows(sql):
        return cur.execute(sql).fetchall()

    # ============================================================
    # A. 季度报告数据 —— Q2 2026 (2026-04-01 ~ 2026-06-30)
    # ============================================================
    Q = quarter_data = {}
    QS, QE = '2026-04-01', '2026-07-01'          # 本季 [QS, QE)
    PS, PE = '2026-01-01', '2026-04-01'          # 上季 Q1 2026
    YS, YE = '2025-04-01', '2025-07-01'          # 去年同季 Q2 2025

    use('HRDB')

    # A1. 近15个月月度审批通过数 (2025-06 ~ 2026-08)
    r = rows(f"""
        SELECT YEAR(submitDate), MONTH(submitDate), COUNT(*) FROM CN_IE_BOLOverView
        WHERE final_approve_status='Approved' AND submitDate >= '2025-06-01'
        GROUP BY YEAR(submitDate), MONTH(submitDate) ORDER BY 1,2
    """)
    Q['approval_monthly'] = [{'ym': f'{a}-{b:02d}', 'cnt': c} for a, b, c in r]

    # A2. 本季/上季/去年同季 按工厂审批数
    def appr_by_factory(s, e):
        r = rows(f"""
            SELECT location, COUNT(*) FROM CN_IE_BOLOverView
            WHERE final_approve_status='Approved' AND submitDate >= '{s}' AND submitDate < '{e}'
            GROUP BY location
        """)
        agg = defaultdict(int)
        for loc, c in r:
            agg[norm_plant(loc)] += c
        return dict(agg)

    Q['approval_factory'] = {
        'this': appr_by_factory(QS, QE),
        'prev': appr_by_factory(PS, PE),
        'yoy': appr_by_factory(YS, YE),
    }

    # A3. 本季审批明细（含BOL变化方向计算）
    r = rows(f"""
        SELECT bol_nr, programCode, programName, location, process, version,
               BOL_Overall, qwsBOL, gap_BOL, submitDate, customer, newProject, lineNr
        FROM CN_IE_BOLOverView
        WHERE final_approve_status='Approved'
    """)
    history = defaultdict(list)   # (prog, process) -> [(date, bol, meta)]
    for (bn, pc, pn, loc, proc, ver, bo, qb, gb, sd, cust, np_, ln) in r:
        if sd is None:
            continue
        history[(pc, proc)].append({
            'date': sd, 'bol': f(bo), 'bol_nr': bn, 'name': pn, 'loc': norm_plant(loc),
            'ver': ver, 'qws': f(qb), 'gap': f(gb), 'cust': cust, 'new': np_, 'line': ln,
        })
    for k in history:
        history[k].sort(key=lambda x: x['date'])

    quarter_changes = []
    for (pc, proc), lst in history.items():
        for i, rec in enumerate(lst):
            if QS <= rec['date'].strftime('%Y-%m-%d') < QE:
                prev = lst[i - 1]['bol'] if i > 0 else None
                quarter_changes.append({
                    'program': pc, 'name': rec['name'], 'plant': rec['loc'],
                    'process': proc, 'line': rec['line'], 'customer': rec['cust'],
                    'bol': rec['bol'], 'prev_bol': prev,
                    'delta': (rec['bol'] - prev) if (rec['bol'] is not None and prev is not None) else None,
                    'date': d2s(rec['date']), 'qws': rec['qws'], 'new': rec['new'] == 'Y',
                })
    Q['bol_changes'] = quarter_changes

    # A4. 瓶颈CT：Q2内每个(项目,产线)最新一条
    r = rows(f"""
        SELECT projectCode, projectName, lineNr, company, cycleTime_bottleNeck, updateTime
        FROM CN_IE_CT_bottleNeck_list
        WHERE updateTime >= '{QS}' AND updateTime < '{QE}'
    """)
    bn_latest = {}
    for (pc, pn, ln, comp, ct, ut) in r:
        if ct is None:
            continue
        key = (pc, ln)
        if key not in bn_latest or ut > bn_latest[key]['ut']:
            bn_latest[key] = {'ut': ut, 'pc': pc, 'pn': pn, 'line': ln,
                              'plant': norm_plant(comp), 'ct': f(ct)}
    bn_list = [v for v in bn_latest.values()]
    bn_list.sort(key=lambda x: -x['ct'])
    Q['bn_total_lines'] = len(bn_list)
    Q['bn_over120_count'] = sum(1 for x in bn_list if x['ct'] > 120)
    Q['bn_top15'] = bn_list[:15]
    Q['bn_over120_by_plant'] = dict(sorted(
        {p: sum(1 for x in bn_list if x['plant'] == p and x['ct'] > 120)
         for p in {x['plant'] for x in bn_list}}.items()))

    by_plant_ct = defaultdict(list)
    for x in bn_list:
        by_plant_ct[x['plant']].append(x['ct'])
    Q['bn_box_by_plant'] = {
        p: {'n': len(v), 'stats': quartiles(v), 'mean': round(sum(v) / len(v), 1)}
        for p, v in sorted(by_plant_ct.items()) if len(v) >= 3
    }

    # A5. 低LB改善机会（复用周报逻辑: LB<0.85, 按(program,process)取最新）
    r = rows("""
        SELECT BOL_Nr, programCode, programName, customer FROM CN_IE_BOLOverView
        WHERE final_approve_status='Approved'
    """)
    bol_meta = {}
    for bn, pc, pn, cust in r:
        if bn not in bol_meta:
            bol_meta[bn] = {'name': pn or '', 'cust': cust or ''}
        else:
            if not bol_meta[bn]['name'] and pn:
                bol_meta[bn]['name'] = pn
            if not bol_meta[bn]['cust'] and cust:
                bol_meta[bn]['cust'] = cust

    r = rows("""
        SELECT BOL_Nr, programCode, process, lineNr, location, CT, HC, LB_rate,
               bottleNeckStation, updateTime FROM CN_IE_BOLOverView_byProcess
    """)
    bp_agg = defaultdict(lambda: {'ct': 0.0, 'hc': 0.0, 'lbs': [], 'ut': None,
                                  'pc': '', 'proc': '', 'line': '', 'loc': '', 'bn': ''})
    for (bn, pc, proc, ln, loc, ct, hc, lb, bns, ut) in r:
        a = bp_agg[bn]
        a['pc'], a['proc'], a['line'], a['loc'] = pc, proc, ln, loc
        if bns and not a['bn']:
            a['bn'] = bns
        if ct is not None:
            a['ct'] += float(ct)
        if hc is not None:
            a['hc'] += float(hc)
        if lb is not None:
            a['lbs'].append(float(lb))
        if ut and (a['ut'] is None or ut > a['ut']):
            a['ut'] = ut

    proj_latest = {}
    for bn, a in bp_agg.items():
        if not a['pc'] or not a['proc']:
            continue
        key = (a['pc'], a['proc'])
        ex = proj_latest.get(key)
        if not ex or (a['ut'] and (ex['ut'] is None or a['ut'] > ex['ut'])):
            a = dict(a)
            a['bol_nr'] = bn
            proj_latest[key] = a

    TARGET_LB, MAX_LB = 0.85, 0.91
    low_items = []
    for (pc, proc), a in proj_latest.items():
        lb = statistics.mean(a['lbs']) if a['lbs'] else None
        hc = a['hc']
        if lb is None or hc <= 0 or lb <= 0 or lb >= TARGET_LB:
            continue
        eff = hc * lb
        hc_target = eff / TARGET_LB
        pot = hc - hc_target
        red_cons = math.floor(pot) if pot >= 1 else 0
        hc_cons = hc - red_cons
        feas_c = red_cons > 0 and hc_cons > 0 and (eff / hc_cons) <= MAX_LB
        min_hc = math.ceil(eff / MAX_LB)
        red_agg = int(hc - min_hc) if min_hc < hc else 0
        low_items.append({
            'program': pc, 'name': bol_meta.get(a.get('bol_nr'), {}).get('name', ''),
            'customer': bol_meta.get(a.get('bol_nr'), {}).get('cust', ''), 'process': proc,
            'plant': norm_plant(a['loc']), 'line': a['line'], 'hc': round(hc, 1),
            'lb': round(lb, 4), 'lb_pct': round(lb * 100, 1), 'ct': round(a['ct'], 1),
            'bn_station': a['bn'], 'potential': round(pot, 1),
            'reduce_cons': red_cons, 'feas_c': feas_c, 'reduce_agg': red_agg,
            'ut': d2s(a['ut']),
        })
    low_items.sort(key=lambda x: x['lb'])
    Q['low_lb_total_projects'] = len(proj_latest)
    Q['low_lb_count'] = len(low_items)
    Q['low_lb_top12'] = low_items[:12]
    Q['low_lb_by_plant'] = dict(sorted(
        {p: sum(1 for x in low_items if x['plant'] == p) for p in {x['plant'] for x in low_items}}.items()))
    # A9. 低LB项目按工厂汇总：保守可减人数合计 / 潜力合计
    agg_lp = defaultdict(lambda: {'count': 0, 'reduce': 0, 'potential': 0.0})
    for x in low_items:
        agg_lp[x['plant']]['count'] += 1
        agg_lp[x['plant']]['reduce'] += x['reduce_cons']
        agg_lp[x['plant']]['potential'] += x['potential']
    Q['low_lb_agg_by_plant'] = {p: {'count': v['count'], 'reduce': v['reduce'],
                                     'potential': round(v['potential'], 1)}
                                for p, v in sorted(agg_lp.items(), key=lambda kv: -kv[1]['reduce'])}

    # A6. KPI月度 LB（近月各工厂线平衡率KPI）
    r = rows("""
        SELECT year, month, location, kpi_value FROM CN_AME_KPI_monthlyHistory
        WHERE kpi_name='LB' AND year*100+month >= 202601 ORDER BY year, month
    """)
    Q['kpi_lb'] = [{'ym': f'{y}-{m:02d}', 'plant': norm_plant(loc), 'v': f(v)}
                   for y, m, loc, v in r]

    # A7. 瓶颈CT季度环比中位数（Q1 vs Q2，按工厂，全部记录口径）
    def bn_quarter_median(s, e):
        r = rows(f"""
            SELECT company, cycleTime_bottleNeck FROM CN_IE_CT_bottleNeck_list
            WHERE updateTime >= '{s}' AND updateTime < '{e}' AND cycleTime_bottleNeck IS NOT NULL
        """)
        agg = defaultdict(list)
        for comp, ct in r:
            agg[norm_plant(comp)].append(float(ct))
        return {p: round(median_ad(v), 1) for p, v in sorted(agg.items()) if v}
    Q['bn_q_median_prev'] = bn_quarter_median('2026-01-01', '2026-04-01')
    Q['bn_q_median_this'] = bn_quarter_median(QS, QE)

    # A8. 高BOL跟踪闭环 (CMC)
    use('CMC')
    try:
        r = rows("SELECT status, COUNT(*), SUM(cost_gap) FROM CN_IE_BOL_HighBolTracking GROUP BY status")
        Q['tracking_status'] = [{'status': s, 'cnt': c, 'cost': f(sg) or 0} for s, c, sg in r]
        r = rows(f"""
            SELECT COUNT(*) FROM CN_IE_BOL_HighBolTracking
            WHERE created_at >= '{QS}' AND created_at < '{QE}'
        """)
        Q['tracking_new_in_q'] = r[0][0]
        r = rows(f"""
            SELECT COUNT(*), SUM(cost_gap) FROM CN_IE_BOL_HighBolTracking
            WHERE achieved_at >= '{QS}' AND achieved_at < '{QE}'
        """)
        Q['tracking_achieved_in_q'] = {'cnt': r[0][0], 'cost': f(r[0][1]) or 0}
        r = rows("""
            SELECT program_code, program_name, location, process, current_bol, target_bol,
                   bol_gap, cost_gap, priority, status, owner_name,
                   CONVERT(varchar(10), target_date, 120), progress
            FROM CN_IE_BOL_HighBolTracking
            WHERE status IN ('OPEN', 'IN_PROGRESS', 'REOPENED')
            ORDER BY cost_gap DESC
        """)
        Q['tracking_open_list'] = [
            {'program': a, 'name': b, 'plant': norm_plant(c), 'process': d,
             'cur': f(e), 'tgt': f(g2), 'gap': f(h), 'cost': f(i) or 0, 'pri': j,
             'status': k, 'owner': l, 'due': m, 'prog': n}
            for a, b, c, d, e, g2, h, i, j, k, l, m, n in r]
    except Exception as e:
        Q['tracking_error'] = str(e)

    with open(r'c:\Users\ligu\.trae-cn\work\6a9391eb1284e4ca632072fe\quarter_data.json', 'w', encoding='utf-8') as fp:
        json.dump(Q, fp, ensure_ascii=False, indent=1, default=str)

    # ============================================================
    # B. 年度报告数据 —— 2026 YTD vs 2025
    # ============================================================
    Y = year_data = {}

    # B1. 月度审批量 2025 vs 2026 + 月度平均BOL_Overall
    use('HRDB')
    for yr in (2025, 2026):
        r = rows(f"""
            SELECT MONTH(submitDate), COUNT(*), AVG(BOL_Overall) FROM CN_IE_BOLOverView
            WHERE final_approve_status='Approved' AND YEAR(submitDate)={yr}
            GROUP BY MONTH(submitDate) ORDER BY 1
        """)
        Y[f'approval_{yr}'] = [{'m': m, 'cnt': c, 'avg_bol': round(f(a) or 0, 2)} for m, c, a in r]
        r = rows(f"""
            SELECT COUNT(DISTINCT programCode) FROM CN_IE_BOLOverView
            WHERE final_approve_status='Approved' AND YEAR(submitDate)={yr}
        """)
        Y[f'unique_programs_{yr}'] = r[0][0]

    # B2. 预算BOL三类型 按工艺 (FY2025/FY2026)
    use('CMC')
    budget_rows = rows("""
        SELECT fiscal_year, process_type, project_code, plant,
               ame_target_bol, achievable_bol, budget_bol
        FROM CN_IE_BOL_BudgetBol
    """)
    budget_groups = {}
    for field, index, output in (
        ('ame_target_bol', 4, 'ame'),
        ('achievable_bol', 5, 'ach'),
        ('budget_bol', 6, 'bud'),
    ):
        project_rows = aggregate_bol_rows(
            [
                {'fiscal_year': fy, 'process_type': proc, 'project_code': code,
                 'plant': plant, field: row[index]}
                for row in budget_rows
                for fy, proc, code, plant in [row[:4]]
            ],
            field, ('fiscal_year', 'process_type', 'project_code'),
        )
        values_by_group = defaultdict(list)
        for record in project_rows:
            values_by_group[(record['fiscal_year'], record['process_type'])].append(record['bol'])
        for key, values in values_by_group.items():
            stats = budget_groups.setdefault(key, {'n': 0})
            stats[output] = round(sum(values) / len(values), 2)
            stats['n'] = max(stats['n'], len(values))
    Y['budget_by_process'] = [
        {'fy': fy, 'process': proc, 'n': values['n'],
         'ame': values.get('ame'), 'ach': values.get('ach'), 'bud': values.get('bud')}
        for (fy, proc), values in sorted(budget_groups.items())
    ]

    ach_rows = rows("""
        SELECT fiscal_year, bol_type, process_type, project_code, plant, bol, oee
        FROM CN_IE_BOL_AchievableTargetBol
    """)
    ach_project_rows = aggregate_bol_rows(
        [
            {'fiscal_year': fy, 'bol_type': bol_type, 'process_type': proc,
             'project_code': code, 'plant': plant, 'bol': bol}
            for fy, bol_type, proc, code, plant, bol, _oee in ach_rows
        ],
        'bol', ('fiscal_year', 'bol_type', 'process_type', 'project_code'),
    )
    ach_groups = defaultdict(list)
    for record in ach_project_rows:
        ach_groups[(record['fiscal_year'], record['bol_type'], record['process_type'])].append(record['bol'])
    oee_by_project = defaultdict(list)
    for fy, bol_type, proc, code, _plant, _bol, oee in ach_rows:
        if oee is not None:
            oee_by_project[(fy, bol_type, proc, code)].append(float(oee))
    oee_groups = defaultdict(list)
    for (fy, bol_type, proc, _code), values in oee_by_project.items():
        oee_groups[(fy, bol_type, proc)].append(sum(values) / len(values))
    Y['achtgt_by_process'] = [
        {
            'fy': fy, 'type': bol_type, 'process': proc, 'n': len(values),
            'bol': round(sum(values) / len(values), 2),
            'oee': round(sum(oee_groups[(fy, bol_type, proc)]) /
                         len(oee_groups[(fy, bol_type, proc)]), 4)
                    if oee_groups[(fy, bol_type, proc)] else None,
        }
        for (fy, bol_type, proc), values in sorted(ach_groups.items())
    ]

    # B3. FY2026 按工厂: BudgetBol平均 & ACHIEVABLE平均
    r = rows("""
        SELECT plant, project_code, process_type, budget_bol FROM CN_IE_BOL_BudgetBol
        WHERE fiscal_year=2026
    """)
    budget_plant_rows = aggregate_bol_rows(
        [
            {'plant': plant, 'project_code': code, 'process_type': proc,
             'budget_bol': bol}
            for plant, code, proc, bol in r
        ],
        'budget_bol', ('project_code', 'process_type', 'plant'),
    )
    budget_by_plant = defaultdict(list)
    for record in budget_plant_rows:
        budget_by_plant[record['plant']].append(record['bol'])
    Y['budget26_by_plant'] = [
        {'plant_raw': plant, 'plant': plant, 'n': len(values),
         'bol': round(sum(values) / len(values), 2)}
        for plant, values in sorted(budget_by_plant.items())
    ]
    r = rows("""
        SELECT plant, process_type, project_code, bol
        FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year=2026 AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
    """)
    ach_plant_rows = aggregate_bol_rows(
        [
            {'plant': plant, 'process_type': proc, 'project_code': code, 'bol': bol}
            for plant, proc, code, bol in r
        ],
        'bol', ('project_code', 'process_type', 'plant'),
    )
    ach_by_plant_process = defaultdict(list)
    for record in ach_plant_rows:
        ach_by_plant_process[(record['plant'], record['process_type'])].append(record['bol'])
    Y['ach26_by_plant_process'] = [
        {'plant': plant, 'process': proc, 'n': len(values),
         'avg': round(sum(values) / len(values), 2),
         'min': round(min(values), 2), 'max': round(max(values), 2)}
        for (plant, proc), values in sorted(ach_by_plant_process.items())
    ]

    # B4. FY2026 ACHIEVABLE join cbco → 工艺×RoofType 平均BOL
    r = rows("""
        SELECT process_type, project_code, plant, bol FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year=2026 AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
    """)
    r2 = rows("""
        SELECT program_number, typ_of_roof, topline_status, volume FROM cbco_records
        WHERE year IN (2026, 2027)
    """)
    roof_map = {}
    for pn, roof, ts, vol in r2:
        if pn and pn not in roof_map:
            roof_map[pn] = {'roof': (roof or '').strip(), 'status': ts, 'vol': vol}
    roof_rows = []
    for pr, pc, pl, bol in r:
        roof = roof_map.get(pc, {}).get('roof', '')
        roof = roof if roof else 'N/A'
        roof_rows.append({
            'project_code': pc, 'process_type': pr, 'plant': pl,
            'roof_type': roof, 'bol': bol,
        })
    roof_project_rows = aggregate_bol_rows(
        roof_rows, 'bol', ('project_code', 'process_type', 'roof_type')
    )
    cat_agg = defaultdict(list)
    won_only = defaultdict(list)
    for record in roof_project_rows:
        key = (record['process_type'], record['roof_type'])
        cat_agg[key].append(record['bol'])
        if roof_map.get(record['project_code'], {}).get('status') == 'WON':
            won_only[key].append(record['bol'])
    def pack(src, minn=2):
        out = []
        for (pr, roof), v in src.items():
            if len(v) >= minn:
                out.append({'process': pr, 'roof': roof, 'n': len(v),
                            'avg': round(sum(v) / len(v), 2),
                            'min': round(min(v), 2), 'max': round(max(v), 2)})
        return sorted(out, key=lambda x: (x['process'], x['avg']))
    Y['ach26_by_roof'] = pack(cat_agg, 1)
    Y['ach26_by_roof_won'] = pack(won_only, 2)

    # B5. 2026改善目标达成 (improveTarget vs 最新实际BOL)
    use('HRDB')
    r = rows("SELECT plant, process, programCode, programName, bol_budget, target_bol FROM CN_AME_IE_BOL_improveTarget WHERE year=2026")
    # 最新实际BOL: 按(program,process)取byProcess最新
    r2 = rows("""
        SELECT BOL_Nr, programCode, process, BOL, LB_rate, updateTime FROM CN_IE_BOLOverView_byProcess
    """)
    act_latest = {}
    for bn, pc, proc, bol, lb, ut in r2:
        key = (pc, proc)
        if key not in act_latest or (ut and act_latest[key]['ut'] < ut):
            act_latest[key] = {'bol': f(bol), 'lb': f(lb), 'ut': ut}
    tgt_rows = []
    for pl, proc, pc, pn, bb, tb in r:
        act = act_latest.get((pc, proc))
        bb_v = f(bb)
        tb_v = f(tb)
        row = {'plant': norm_plant(pl), 'process': proc, 'program': pc, 'name': pn,
               'budget': bb_v, 'target_ratio': tb_v,
               'actual': act['bol'] if act else None,
               'lb': act['lb'] if act else None}
        if bb_v and act and act['bol'] is not None:
            row['gap_pct'] = round((act['bol'] - bb_v) / bb_v * 100, 1)
            if tb_v is not None:
                exp = bb_v * (1 - tb_v)
                row['expected'] = round(exp, 2)
                need = bb_v - exp
                got = bb_v - act['bol']
                row['progress'] = round(got / need * 100, 1) if need > 0 else None
                row['state'] = ('met' if act['bol'] <= exp else
                                'near' if row['progress'] is not None and row['progress'] >= 60 else
                                'behind')
            else:
                row['state'] = 'improved' if act['bol'] < bb_v else 'worse'
        tgt_rows.append(row)
    Y['improve_target_rows'] = tgt_rows
    st = defaultdict(lambda: defaultdict(int))
    for x in tgt_rows:
        if x.get('state'):
            st[x['plant']][x['state']] += 1
    Y['improve_target_by_plant'] = {p: dict(v) for p, v in sorted(st.items())}

    # B6. 瓶颈CT月度中位数 按工厂 (2025-08 ~ 2026-08)
    r = rows("""
        SELECT FORMAT(updateTime,'yyyy-MM'), company, cycleTime_bottleNeck
        FROM CN_IE_CT_bottleNeck_list
        WHERE updateTime >= '2025-08-01' AND cycleTime_bottleNeck IS NOT NULL
    """)
    mct = defaultdict(lambda: defaultdict(list))
    for ym, comp, ct in r:
        mct[ym][norm_plant(comp)].append(float(ct))
    months = sorted(mct.keys())
    Y['bn_monthly_by_plant'] = {
        'months': months,
        'series': {p: [round(median_ad(mct[ym].get(p, [])), 1) if mct[ym].get(p) else None
                       for ym in months]
                   for p in ['BJ', 'SH', 'CQ', 'GZ', 'CJ']},
    }

    # B7. KPI年度 (BOL Reduction/Updates Rate, Actual CT Rate)
    r = rows("""
        SELECT kpi_name, year, month, location, kpi_value FROM CN_AME_KPI_monthlyHistory
        WHERE kpi_name IN ('BOL Reduction Rate','BOL Updates Rate','Acutal CT Rate')
            AND year IN (2025, 2026)
        ORDER BY kpi_name, year, month, location
    """)
    kp = defaultdict(lambda: defaultdict(dict))
    for kn, y, m, loc, v in r:
        kp[kn][f'{y}-{m:02d}'][norm_plant(loc)] = f(v)
    Y['kpi_monthly'] = {k: dict(v) for k, v in kp.items()}

    # B8. FY2026 ACHIEVABLE(WON) 工艺×RoofType×工厂 组合级统计（跨工厂可比组合分析）
    use('CMC')
    r = rows("""
        SELECT process_type, project_code, plant, bol FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year=2026 AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
    """)
    r2 = rows("""
        SELECT program_number, typ_of_roof, topline_status FROM cbco_records
        WHERE year IN (2026, 2027)
    """)
    roof_map2 = {}
    for pn, roof, ts in r2:
        if pn and pn not in roof_map2:
            roof_map2[pn] = {'roof': (roof or '').strip(), 'status': ts}
    won_rows = []
    won_projects = set()
    for pr, pc, pl, bol in r:
        info = roof_map2.get(pc, {})
        if info.get('status') != 'WON':
            continue
        won_projects.add(pc)
        roof = info.get('roof') or 'N/A'
        won_rows.append({
            'project_code': pc, 'process_type': pr, 'plant': pl,
            'roof_type': roof, 'bol': bol,
        })
    won_project_rows = aggregate_bol_rows(
        won_rows, 'bol', ('project_code', 'process_type', 'roof_type', 'plant')
    )
    combo = defaultdict(list)
    for record in won_project_rows:
        combo[(record['process_type'], record['roof_type'], record['plant'])].append(record['bol'])
    Y['ach26_won_by_roof_plant'] = [
        {'process': pr, 'roof': roof, 'plant': plant, 'n': len(values),
         'avg': round(sum(values) / len(values), 2),
         'min': round(min(values), 2), 'max': round(max(values), 2)}
        for (pr, roof, plant), values in sorted(combo.items())
    ]
    Y['ach26_won_projects'] = len(won_projects)

    # B9. FY2025 vs FY2026 同项目（同工艺）Achievable BOL 变化
    r = rows("""
        SELECT fiscal_year, project_code, process_type, plant, bol FROM CN_IE_BOL_AchievableTargetBol
        WHERE bol_type='ACHIEVABLE' AND bol IS NOT NULL AND fiscal_year IN (2025, 2026)
    """)
    fy_project_rows = aggregate_bol_rows(
        [
            {'fiscal_year': fy, 'project_code': pc, 'process_type': proc,
             'plant': plant, 'bol': bol}
            for fy, pc, proc, plant, bol in r
        ],
        'bol', ('fiscal_year', 'project_code', 'process_type'),
    )
    fy_map = {
        (record['fiscal_year'], record['project_code'], record['process_type']): record['bol']
        for record in fy_project_rows
    }
    pairs = []
    for (fy, pc, pr), v in fy_map.items():
        if fy == 2026 and (2025, pc, pr) in fy_map:
            pairs.append({'program': pc, 'process': pr,
                          'y25': round(fy_map[(2025, pc, pr)], 2), 'y26': round(v, 2),
                          'delta': round(v - fy_map[(2025, pc, pr)], 2)})
    fy_agg = defaultdict(lambda: {'improved': 0, 'stable': 0, 'worse': 0, 'deltas': []})
    for x in pairs:
        a = fy_agg[x['process']]
        a['deltas'].append(x['delta'])
        if x['delta'] < -0.5:
            a['improved'] += 1
        elif x['delta'] > 0.5:
            a['worse'] += 1
        else:
            a['stable'] += 1
    Y['fy2526_pairs'] = pairs
    Y['fy2526_by_process'] = {
        pr: {'improved': v['improved'], 'stable': v['stable'], 'worse': v['worse'],
             'n': len(v['deltas']), 'avg_delta': round(sum(v['deltas']) / len(v['deltas']), 2),
             'avg_delta_pct': round(sum(v['deltas']) / len(v['deltas']) /
                                    (sum(x['y25'] for x in pairs if x['process'] == pr) /
                                     max(1, sum(1 for x in pairs if x['process'] == pr))) * 100, 1)}
        for pr, v in fy_agg.items()}
    pairs.sort(key=lambda x: x['delta'])
    Y['fy2526_top_drop'] = pairs[:8]
    Y['fy2526_top_rise'] = sorted(pairs, key=lambda x: -x['delta'])[:8]

    # B10. QWS报价 vs 实际BOL覆盖（项目级，最近审批版本）
    use('HRDB')
    r = rows("""
        SELECT programCode, BOL_Overall, qwsBOL, submitDate FROM CN_IE_BOLOverView
        WHERE final_approve_status='Approved' AND qwsBOL IS NOT NULL AND qwsBOL > 0
    """)
    max_date = {}
    for pc, bo, qb, sd in r:
        if sd is None or bo is None:
            continue
        if pc not in max_date or sd > max_date[pc]:
            max_date[pc] = sd
    prog_latest = defaultdict(lambda: {'bol': 0.0, 'qws': 0.0})
    for pc, bo, qb, sd in r:
        if sd is None or bo is None or max_date.get(pc) != sd:
            continue
        prog_latest[pc]['bol'] += float(bo)
        prog_latest[pc]['qws'] = max(prog_latest[pc]['qws'], float(qb))
    qws_items = []
    for pc, k in prog_latest.items():
        if k['qws'] > 0 and k['bol'] > 0:
            qws_items.append({'program': pc, 'bol': round(k['bol'], 2), 'qws': round(k['qws'], 2),
                              'ratio': round(k['bol'] / k['qws'] * 100, 1)})
    qws_items.sort(key=lambda x: -x['ratio'])
    Y['qws_items'] = qws_items
    ratios = [x['ratio'] for x in qws_items]
    Y['qws_summary'] = {
        'n': len(ratios),
        'median': round(median_ad(ratios), 1) if ratios else None,
        'over': sum(1 for x in ratios if x > 100),
        'b80_100': sum(1 for x in ratios if 80 <= x <= 100),
        'b50_80': sum(1 for x in ratios if 50 <= x < 80),
        'under50': sum(1 for x in ratios if x < 50),
    }

    # B11. FY2026 ACHIEVABLE 覆盖范围（工厂×工艺 项目数）
    use('CMC')
    r = rows("""
        SELECT plant, process_type, COUNT(*), COUNT(DISTINCT project_code)
        FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year=2026 AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
        GROUP BY plant, process_type
    """)
    Y['ach26_coverage'] = [
        {'plant': norm_plant(pl), 'process': pr, 'rows': n, 'projects': np_}
        for pl, pr, n, np_ in r]

    with open(r'c:\Users\ligu\.trae-cn\work\6a9391eb1284e4ca632072fe\year_data.json', 'w', encoding='utf-8') as fp:
        json.dump(Y, fp, ensure_ascii=False, indent=1, default=str)

    cn.close()
    print('OK quarter keys:', sorted(Q.keys()))
    print('OK year keys:', sorted(Y.keys()))
    print(f"quarter bol_changes={len(Q['bol_changes'])} low_lb={Q['low_lb_count']}/{Q['low_lb_total_projects']} bn_lines={Q['bn_total_lines']}")
    print(f"year improve_targets={len(Y['improve_target_rows'])}")


if __name__ == '__main__':
    main()

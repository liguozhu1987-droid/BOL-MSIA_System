# -*- coding: utf-8 -*-
"""BOL 季度/年度报告 数据提取（参数化移植自 报告生成脚本/extract_report_data.py）

按指定周期从 HRDB / CMC 提取报告所需的全部统计数据，返回 dict：
  - extract_quarter_data(year, quarter) → 季度报告数据 Q
  - extract_year_data(year)             → 年度报告数据 Y

连接方式与原脚本一致：pyodbc 直连，连接参数取自 Django settings
（db_config.ini / 默认值，ODBC 18 与 TrustServerCertificate 已处理）。
"""
import datetime as dt
import math
import re
import statistics
from collections import defaultdict

import pyodbc
from django.conf import settings

# ── 工厂标准化（与 plant_utils 保持一致）─────────────────────
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

MAIN_PLANTS = ['BJ', 'SH', 'CJ', 'CQ', 'GZ']          # 报告主分析工厂
CT_PLANTS = ['BJ', 'SH', 'CQ', 'CJ', 'GZ']            # 实测CT监控工厂


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


def month_add(y, m, k):
    """月份加法：返回 (year, month)"""
    t = (m - 1) + k
    return y + t // 12, t % 12 + 1


def ym_str(y, m):
    return f'{y}-{m:02d}'


# ── 数据库连接 ────────────────────────────────────────────────
def get_connection():
    """按 settings 中的数据库参数建立 pyodbc 连接（HRDB）"""
    opts = settings.DB_OPTIONS
    extra = opts.get('extra_params', '') or ''
    conn_str = (
        f"DRIVER={{{opts['driver']}}};"
        f"SERVER={settings.DB_HOST};"
        f"UID={settings.DB_USER};"
        f"PWD={settings.DB_PASSWORD};"
        f"DATABASE=HRDB;{extra}"
    )
    return pyodbc.connect(conn_str, timeout=30)


def quarter_range(year, quarter):
    """季度 → (季初, 季末次日)，均为 date"""
    start_month = 3 * (quarter - 1) + 1
    qs = dt.date(year, start_month, 1)
    if quarter == 4:
        qe = dt.date(year + 1, 1, 1)
    else:
        qe = dt.date(year, start_month + 3, 1)
    return qs, qe


def prev_quarter(year, quarter):
    """上一季度 → (year, quarter)"""
    if quarter == 1:
        return year - 1, 4
    return year, quarter - 1


# ════════════════════════════════════════════════════════════════
# 季度报告数据
# ════════════════════════════════════════════════════════════════
def extract_quarter_data(year, quarter, today=None):
    today = today or dt.date.today()
    Q = {}
    QS, QE = quarter_range(year, quarter)
    py, pq = prev_quarter(year, quarter)
    PS, PE = quarter_range(py, pq)
    YS, YE = quarter_range(year - 1, quarter)

    qs_s, qe_s = d2s(QS), d2s(QE)
    ps_s, pe_s = d2s(PS), d2s(PE)
    ys_s, ye_s = d2s(YS), d2s(YE)

    Q['year'] = year
    Q['quarter'] = quarter
    Q['qs'] = qs_s
    Q['qe'] = d2s(QE - dt.timedelta(days=1))
    Q['prev_label'] = f'{py}Q{pq}'
    Q['this_label'] = f'{year}Q{quarter}'
    Q['yoy_label'] = f'{year - 1}Q{quarter}'
    Q['gen_date'] = d2s(today)

    cn = get_connection()
    cur = cn.cursor()

    def use(db):
        cur.execute(f"USE {db}")

    def rows(sql):
        return cur.execute(sql).fetchall()

    # A1. 近15个月月度审批通过数
    sy, sm = month_add(today.year, today.month, -15)
    r = rows(f"""
        SELECT YEAR(submitDate), MONTH(submitDate), COUNT(*) FROM CN_IE_BOLOverView
        WHERE final_approve_status='Approved' AND submitDate >= '{ym_str(sy, sm)}-01'
        GROUP BY YEAR(submitDate), MONTH(submitDate) ORDER BY 1,2
    """)
    Q['approval_monthly'] = [{'ym': f'{a}-{b:02d}', 'cnt': c} for a, b, c in r]
    # 季度起始前一个月起的最近两个月（延续节奏观察）
    ry, rm = month_add(today.year, today.month, -1)
    ry2, rm2 = month_add(ry, rm, -1)
    Q['recent_2m'] = [ym_str(ry2, rm2), ym_str(ry, rm)]
    Q['recent_2m_cnt'] = [next((m['cnt'] for m in Q['approval_monthly']
                                if m['ym'] == ym), 0) for ym in Q['recent_2m']]

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
        'this': appr_by_factory(qs_s, qe_s),
        'prev': appr_by_factory(ps_s, pe_s),
        'yoy': appr_by_factory(ys_s, ye_s),
    }

    # A3. 本季审批明细（含BOL变化方向计算）
    r = rows("""
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
            if qs_s <= rec['date'].strftime('%Y-%m-%d') < qe_s:
                prev = lst[i - 1]['bol'] if i > 0 else None
                quarter_changes.append({
                    'program': pc, 'name': rec['name'], 'plant': rec['loc'],
                    'process': proc, 'line': rec['line'], 'customer': rec['cust'],
                    'bol': rec['bol'], 'prev_bol': prev,
                    'delta': (rec['bol'] - prev) if (rec['bol'] is not None and prev is not None) else None,
                    'date': d2s(rec['date']), 'qws': rec['qws'], 'new': rec['new'] == 'Y',
                })
    Q['bol_changes'] = quarter_changes

    # A4. 瓶颈CT：季度内每个(项目,产线)最新一条
    r = rows(f"""
        SELECT projectCode, projectName, lineNr, company, cycleTime_bottleNeck, updateTime
        FROM CN_IE_CT_bottleNeck_list
        WHERE updateTime >= '{qs_s}' AND updateTime < '{qe_s}'
    """)
    bn_latest = {}
    for (pc, pn, ln, comp, ct, ut) in r:
        if ct is None:
            continue
        key = (pc, ln)
        if key not in bn_latest or ut > bn_latest[key]['_ut_raw']:
            bn_latest[key] = {'_ut_raw': ut, 'ut': d2s(ut), 'pc': pc, 'pn': pn,
                              'line': ln, 'plant': norm_plant(comp), 'ct': f(ct)}
    bn_list = [{k: v for k, v in x.items() if k != '_ut_raw'} for x in bn_latest.values()]
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

    # A5. 低LB改善机会（LB<0.85, 按(program,process)取最新）
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
    # 低LB项目按工厂汇总：保守可减人数合计 / 潜力合计
    agg_lp = defaultdict(lambda: {'count': 0, 'reduce': 0, 'potential': 0.0})
    for x in low_items:
        agg_lp[x['plant']]['count'] += 1
        agg_lp[x['plant']]['reduce'] += x['reduce_cons']
        agg_lp[x['plant']]['potential'] += x['potential']
    Q['low_lb_agg_by_plant'] = {p: {'count': v['count'], 'reduce': v['reduce'],
                                    'potential': round(v['potential'], 1)}
                                for p, v in sorted(agg_lp.items(), key=lambda kv: -kv[1]['reduce'])}
    if low_items:
        Q['lowest_lb_item'] = low_items[0]

    # A6. KPI月度 LB（本年各月，供近3月趋势）
    r = rows(f"""
        SELECT year, month, location, kpi_value FROM CN_AME_KPI_monthlyHistory
        WHERE kpi_name='LB' AND year*100+month >= {today.year}01 ORDER BY year, month
    """)
    Q['kpi_lb'] = [{'ym': f'{y}-{m:02d}', 'plant': norm_plant(loc), 'v': f(v)}
                   for y, m, loc, v in r]
    # 近3个月（含生成当月）
    yms = []
    y_, m_ = today.year, today.month
    for k in (2, 1, 0):
        yy, mm = month_add(y_, m_, -k)
        yms.append(ym_str(yy, mm))
    Q['lb_trend_months'] = yms

    # A7. 瓶颈CT季度环比中位数（上季 vs 本季，按工厂，全部记录口径）
    def bn_quarter_median(s, e):
        r = rows(f"""
            SELECT company, cycleTime_bottleNeck FROM CN_IE_CT_bottleNeck_list
            WHERE updateTime >= '{s}' AND updateTime < '{e}' AND cycleTime_bottleNeck IS NOT NULL
        """)
        agg = defaultdict(list)
        for comp, ct in r:
            agg[norm_plant(comp)].append(float(ct))
        return {p: round(median_ad(v), 1) for p, v in sorted(agg.items()) if v}

    Q['bn_q_median_prev'] = bn_quarter_median(ps_s, pe_s)
    Q['bn_q_median_this'] = bn_quarter_median(qs_s, qe_s)

    # A9. AME BOL KPI 三指标（BOL更新率/降低率/ACT CT抓取率，本年最新月，按工厂）
    r = rows(f"""
        SELECT kpi_name, year, month, location, kpi_value FROM CN_AME_KPI_monthlyHistory
        WHERE year={year} AND kpi_name IN ('Acutal CT Rate','BOL Reduction Rate','BOL Updates Rate')
    """)
    kpi_raw = defaultdict(list)
    for kn, ky, mo, loc, v in r:
        kpi_raw[kn].append((ky * 100 + mo, norm_plant(loc or ''), f(v)))
    Q['ame_kpis'] = {}
    for kn, lst in kpi_raw.items():
        latest = max(x[0] for x in lst)
        precision = 2 if kn == 'BOL Reduction Rate' else 1
        by_plant = {}
        for ym, plant, v in lst:
            if ym == latest and plant and plant != '未知' and v is not None:
                by_plant[plant] = round(v * 100, precision)
        cmc = by_plant.pop('CMC', None)
        avg = round(sum(by_plant.values()) / len(by_plant), precision) if by_plant else 0
        Q['ame_kpis'][kn] = {'month': latest % 100, 'by_plant': by_plant,
                             'avg_pct': avg,
                             'cmc_pct': round(cmc, precision) if cmc is not None else None}

    # A10/A11/A12 共用：瓶颈CT全量记录（按时间倒序，供各口径取最新）
    r = rows("""
        SELECT projectCode, projectName, lineNr, company, cycleTime_bottleNeck, updateTime
        FROM CN_IE_CT_bottleNeck_list
        WHERE cycleTime_bottleNeck IS NOT NULL AND updateTime IS NOT NULL
        ORDER BY updateTime DESC
    """)
    bn_all = [(pc, pn, ln, norm_plant(comp), float(ct), ut)
              for pc, pn, ln, comp, ct, ut in r]

    # A10. ACT CT 趋势 TOP10（近3月均值 vs 前3月均值，环比，项目+产线粒度）
    def _ym_shift(ym, delta):
        y, m = ym.split('-')
        total = int(y) * 12 + (int(m) - 1) + delta
        return f"{total // 12:04d}-{total % 12 + 1:02d}"

    ct_monthly = defaultdict(lambda: defaultdict(list))
    ct_meta = {}
    sy2, sm2 = month_add(today.year, today.month, -9)
    ym_9m = ym_str(sy2, sm2)
    for pc, pn, ln, plant, ct, ut in bn_all:
        ym = ut.strftime('%Y-%m')
        if ym < ym_9m:
            continue
        key = (pc, ln)
        ct_monthly[key][ym].append(ct)
        if key not in ct_meta:
            ct_meta[key] = {'plant': plant, 'pc': pc, 'pn': pn or '', 'line': ln}
    ct_trend = {'periods': None, 'mom': {'rise': [], 'drop': []}, 'stats': {}}
    if ct_monthly:
        all_months = sorted({ym for by_m in ct_monthly.values() for ym in by_m})
        recent3 = all_months[-3:]
        prev3 = [_ym_shift(recent3[0], -i) for i in (3, 2, 1)]

        def _win_avg(medians, months):
            vals = [medians[ym] for ym in months if ym in medians]
            return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)

        mom_rows = []
        for key, by_m in ct_monthly.items():
            medians = {ym: statistics.median(v) for ym, v in by_m.items()}
            recent_avg, recent_n = _win_avg(medians, recent3)
            if recent_avg is None:
                continue
            base_avg, base_n = _win_avg(medians, prev3)
            if base_avg and base_avg > 0:
                mom_rows.append({
                    **ct_meta[key], 'recent_avg': round(recent_avg, 2),
                    'base_avg': round(base_avg, 2),
                    'change_pct': round((recent_avg - base_avg) / base_avg * 100, 1),
                })
        rise = sorted([x for x in mom_rows if x['change_pct'] > 0],
                      key=lambda x: -x['change_pct'])[:10]
        drop = sorted([x for x in mom_rows if x['change_pct'] < 0],
                      key=lambda x: x['change_pct'])[:10]
        ct_trend = {'periods': {'recent': recent3, 'prev': prev3},
                    'mom': {'rise': rise, 'drop': drop},
                    'stats': {'tracked': len(ct_monthly), 'computed': len(mom_rows)}}
    Q['ct_trend'] = ct_trend

    # A11. ACT vs Std 偏差 TOP20（|(ACT−Std)/Std|>10%，按|偏差%|降序；项目键合并 O/S/T 前缀）
    _PK_RE = re.compile(r'^[A-Z](\d{4})([a-zA-Z]?)$')

    def _proj_key(code):
        if not code:
            return None
        m = _PK_RE.match(code.strip())
        return (m.group(1) + (m.group(2) or '')) if m else None

    act_map = {}
    for pc, pn, ln, plant, ct, ut in bn_all:
        pkey = _proj_key(pc) or pc
        key = (pkey, ln)
        if key not in act_map:
            act_map[key] = {'plant': plant, 'pc': pc, 'pn': pn or '', 'line': ln,
                            'act': ct, 'ut': d2s(ut)}
    std_map = {}
    r = rows("""
        SELECT programCode, lineNr, process, CT, submitDate FROM CN_IE_BOLOverView
        WHERE final_approve_status='Approved' AND CT IS NOT NULL
        ORDER BY submitDate DESC
    """)
    for pc, ln, proc, ct, sd in r:
        pkey = _proj_key(pc) or pc
        key = (pkey, ln, proc)
        if key not in std_map:
            std_map[key] = {'pc': pc, 'std': float(ct), 'date': d2s(sd)}
    std_by_line = defaultdict(list)
    for (pkey, ln, proc), v in std_map.items():
        std_by_line[(pkey, ln)].append((proc, v))
    act_std_items = []
    matched_ct = 0
    for (pkey, ln), act in act_map.items():
        for proc, sv in std_by_line.get((pkey, ln), []):
            if sv['std'] is None or sv['std'] <= 0:
                continue
            matched_ct += 1
            dev = act['act'] - sv['std']
            dev_pct = dev / sv['std'] * 100
            if abs(dev_pct) <= 10:
                continue
            act_std_items.append({
                'plant': act['plant'], 'pc': sv['pc'], 'pn': act['pn'], 'line': ln,
                'process': proc, 'std': round(sv['std'], 2), 'act': round(act['act'], 2),
                'dev': round(dev, 2), 'dev_pct': round(dev_pct, 1),
                'sct_date': sv['date'], 'act_date': act['ut'],
            })
    act_std_items.sort(key=lambda x: -abs(x['dev_pct']))
    Q['act_std_top20'] = act_std_items[:20]
    Q['act_std_stats'] = {
        'matched': matched_ct,
        'over': len(act_std_items),
        'above': sum(1 for x in act_std_items if x['dev_pct'] > 0),
        'below': sum(1 for x in act_std_items if x['dev_pct'] < 0),
    }

    # A12. SCT vs ACT 对比（按工厂；project_code+line 精确匹配，各取最新）
    act_exact = {}
    for pc, pn, ln, plant, ct, ut in bn_all:
        key = (pc, ln)
        if key not in act_exact:
            act_exact[key] = {'plant': plant, 'pc': pc, 'pn': pn or '', 'line': ln,
                              'act': ct, 'ut': d2s(ut)}
    sct_map = {}
    for pc, ln, proc, ct, sd in r:  # r = Approved CT 记录（时间倒序）
        key = (pc, ln, proc)
        if key not in sct_map:
            sct_map[key] = float(ct)
    sct_by_line = defaultdict(list)
    for (pc, ln, proc), ct in sct_map.items():
        sct_by_line[(pc, ln)].append((proc, ct))
    sa_by_plant = defaultdict(lambda: {'items': [], 'act_only': 0})
    for (pc, ln), act in act_exact.items():
        matches = sct_by_line.get((pc, ln), [])
        if not matches:
            sa_by_plant[act['plant']]['act_only'] += 1
            continue
        for proc, sct in matches:
            gap = sct - act['act']
            sa_by_plant[act['plant']]['items'].append({
                'pc': pc, 'pn': act['pn'], 'line': ln, 'process': proc,
                'sct': round(sct, 2), 'act': round(act['act'], 2),
                'gap': round(gap, 2),
                'gap_pct': round(gap / sct * 100, 1) if sct > 0 else None,
                'ut': act['ut'],
            })
    Q['sct_act_by_plant'] = {p: {'items': sorted(v['items'], key=lambda x: -abs(x['gap_pct'] or 0)),
                                 'act_only': v['act_only']}
                             for p, v in sorted(sa_by_plant.items())}

    # A13. TOP10 对比分析（本季提交口径：项目+工艺去重取最新一条）
    tc_latest = {}
    for c in Q['bol_changes']:
        key = (c['program'], c['process'])
        ex = tc_latest.get(key)
        if not ex or c['date'] > ex['date']:
            tc_latest[key] = c

    def _near_double(a, b):
        """接近 2 倍关系（比值 1.8~2.2）→ 疑似漏提交/重复提交"""
        if not a or not b or a <= 0 or b <= 0:
            return False
        ratio = a / b if a > b else b / a
        return 1.8 <= ratio <= 2.2

    qws_rows, mom_rows = [], []
    for c in tc_latest.values():
        if c['bol'] is None:
            continue
        if c['qws'] is not None and c['qws'] > 0:
            qws_rows.append({
                'program': c['program'], 'name': c['name'] or '', 'plant': c['plant'],
                'process': c['process'], 'bol': c['bol'], 'qws': c['qws'],
                'change_pct': round((c['bol'] - c['qws']) / c['qws'] * 100, 1),
                'anomaly': _near_double(c['bol'], c['qws']), 'date': c['date'],
            })
        if c['prev_bol'] is not None and c['prev_bol'] > 0:
            mom_rows.append({
                'program': c['program'], 'name': c['name'] or '', 'plant': c['plant'],
                'process': c['process'], 'bol': c['bol'], 'prev': c['prev_bol'],
                'change_pct': round((c['bol'] - c['prev_bol']) / c['prev_bol'] * 100, 1),
                'anomaly': _near_double(c['bol'], c['prev_bol']), 'date': c['date'],
            })

    def _tops(rows_list):
        rise_t = sorted([x for x in rows_list if x['change_pct'] > 0],
                        key=lambda x: -x['change_pct'])[:10]
        drop_t = sorted([x for x in rows_list if x['change_pct'] < 0],
                        key=lambda x: x['change_pct'])[:10]
        return {'rise': rise_t, 'drop': drop_t}

    Q['top_compare'] = {
        'qws': _tops(qws_rows), 'mom': _tops(mom_rows),
        'anomaly_count': sum(1 for x in qws_rows + mom_rows if x['anomaly']),
        'qws_total': len(qws_rows), 'mom_total': len(mom_rows),
    }

    # A8. 高BOL跟踪闭环 (CMC)
    use('CMC')
    try:
        r = rows("SELECT status, COUNT(*), SUM(cost_gap) FROM CN_IE_BOL_HighBolTracking GROUP BY status")
        Q['tracking_status'] = [{'status': s, 'cnt': c, 'cost': f(sg) or 0} for s, c, sg in r]
        r = rows(f"""
            SELECT COUNT(*) FROM CN_IE_BOL_HighBolTracking
            WHERE created_at >= '{qs_s}' AND created_at < '{qe_s}'
        """)
        Q['tracking_new_in_q'] = r[0][0]
        r = rows(f"""
            SELECT COUNT(*), SUM(cost_gap) FROM CN_IE_BOL_HighBolTracking
            WHERE achieved_at >= '{qs_s}' AND achieved_at < '{qe_s}'
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
    except Exception as e:  # noqa: BLE001
        Q['tracking_error'] = str(e)

    # K2. 三工时汇总：复用综合看板 HRDB improveTarget 同源口径
    try:
        from apps.analytics.views import _calc_improve_target_compare

        compare = _calc_improve_target_compare(year)
        Q['improve_hours'] = [
            {
                'plant': row['plant'],
                'budget': row['budget_hours'],
                'target': row['target_hours'],
                'achievable': row['achievable_hours'],
            }
            for row in compare['summary']
        ]
    except Exception as e:  # noqa: BLE001
        Q['improve_hours_error'] = str(e)

    cn.close()
    return Q


# ════════════════════════════════════════════════════════════════
# 年度报告数据
# ════════════════════════════════════════════════════════════════
def extract_year_data(year, today=None):
    from apps.analytics.bol_aggregation import aggregate_bol_rows

    today = today or dt.date.today()
    Y = {}
    Y['year'] = year
    Y['prev_year'] = year - 1
    Y['gen_date'] = d2s(today)
    # 年度报告数据截止：当年生成（YTD）为生成日；次年生成（全年）为 12-31
    if today.year > year:
        Y['data_end'] = f'{year}-12-31'
        Y['ytd_month'] = 12
    else:
        Y['data_end'] = d2s(today)
        Y['ytd_month'] = today.month

    cn = get_connection()
    cur = cn.cursor()

    def use(db):
        cur.execute(f"USE {db}")

    def rows(sql):
        return cur.execute(sql).fetchall()

    # B1. 月度审批量 本年 vs 上年 + 月度平均BOL_Overall
    use('HRDB')
    for yr in (year - 1, year):
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

    # B2. 预算BOL三类型 按工艺（本年/上年）
    use('CMC')
    budget_rows = rows(f"""
        SELECT fiscal_year, process_type, project_code, plant, ame_target_bol,
               achievable_bol, budget_bol
        FROM CN_IE_BOL_BudgetBol WHERE fiscal_year IN ({year - 1}, {year})
    """)
    budget_stats = {}
    for field, output_field in (
        ('ame_target_bol', 'ame'),
        ('achievable_bol', 'ach'),
        ('budget_bol', 'bud'),
    ):
        field_index = {
            'ame_target_bol': 4,
            'achievable_bol': 5,
            'budget_bol': 6,
        }[field]
        project_rows = aggregate_bol_rows(
            [
                {
                    'fiscal_year': record[0], 'process_type': record[1],
                    'project_code': record[2], 'plant': record[3],
                    field: record[field_index],
                }
                for record in budget_rows
            ],
            field,
            ('fiscal_year', 'process_type', 'project_code'),
        )
        metric_groups = defaultdict(list)
        for record in project_rows:
            metric_groups[(record['fiscal_year'], record['process_type'])].append(record['bol'])
        for key, values in metric_groups.items():
            stats = budget_stats.setdefault(key, {'n': 0})
            stats[output_field] = round(sum(values) / len(values), 2)
            stats['n'] = max(stats['n'], len(values))

    Y['budget_by_process'] = [
        {'fy': fy, 'process': proc, 'n': values['n'],
         'ame': values.get('ame'), 'ach': values.get('ach'), 'bud': values.get('bud')}
        for (fy, proc), values in sorted(budget_stats.items())
    ]
    ach_rows = rows(f"""
        SELECT fiscal_year, bol_type, process_type, project_code, plant, bol, oee
        FROM CN_IE_BOL_AchievableTargetBol WHERE fiscal_year IN ({year - 1}, {year})
    """)
    ach_project_rows = aggregate_bol_rows(
        [
            {'fiscal_year': fy, 'bol_type': bol_type, 'process_type': proc,
             'project_code': code, 'plant': plant, 'bol': bol}
            for fy, bol_type, proc, code, plant, bol, _oee in ach_rows
        ],
        'bol',
        ('fiscal_year', 'bol_type', 'process_type', 'project_code'),
    )
    ach_bol_groups = defaultdict(list)
    for record in ach_project_rows:
        ach_bol_groups[(record['fiscal_year'], record['bol_type'], record['process_type'])].append(record['bol'])
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
        for (fy, bol_type, proc), values in sorted(ach_bol_groups.items())
    ]

    # B3. 本年 按工厂: BudgetBol平均 & ACHIEVABLE平均
    r = rows(f"""
        SELECT plant, project_code, process_type, budget_bol FROM CN_IE_BOL_BudgetBol
        WHERE fiscal_year={year}
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
    Y['budget_by_plant'] = [
        {'plant_raw': plant, 'plant': plant, 'n': len(values),
         'bol': round(sum(values) / len(values), 2)}
        for plant, values in sorted(budget_by_plant.items())
    ]
    r = rows(f"""
        SELECT plant, process_type, project_code, bol
        FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year={year} AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
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
    Y['ach_by_plant_process'] = [
        {'plant': plant, 'process': proc, 'n': len(values),
         'avg': round(sum(values) / len(values), 2),
         'min': round(min(values), 2), 'max': round(max(values), 2)}
        for (plant, proc), values in sorted(ach_by_plant_process.items())
    ]

    # B4. 本年 ACHIEVABLE join cbco → 工艺×RoofType 平均BOL
    r = rows(f"""
        SELECT process_type, project_code, plant, bol FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year={year} AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
    """)
    r2 = rows(f"""
        SELECT program_number, typ_of_roof, topline_status, volume FROM cbco_records
        WHERE year IN ({year}, {year + 1})
    """)
    roof_map = {}
    for pn, roof, ts, vol in r2:
        if pn and pn not in roof_map:
            roof_map[pn] = {'roof': (roof or '').strip(), 'status': ts, 'vol': vol}
    ach_roof_rows = []
    for pr, pc, pl, bol in r:
        roof = roof_map.get(pc, {}).get('roof', '')
        roof = roof if roof else 'N/A'
        ach_roof_rows.append({
            'project_code': pc, 'process_type': pr, 'plant': pl,
            'roof_type': roof, 'bol': bol,
        })
    project_roof_rows = aggregate_bol_rows(
        ach_roof_rows, 'bol', ('project_code', 'process_type', 'roof_type')
    )
    cat_agg = defaultdict(list)
    won_only = defaultdict(list)
    for record in project_roof_rows:
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

    Y['ach_by_roof'] = pack(cat_agg, 1)
    Y['ach_by_roof_won'] = pack(won_only, 2)

    # B4b. 逐项目原始 BOL 值（工厂×工艺），供第五章点图（strip plot）展示真实分布
    ach_proj = defaultdict(list)
    ach_plant_project_rows = aggregate_bol_rows(
        ach_roof_rows, 'bol', ('project_code', 'process_type', 'plant')
    )
    for record in ach_plant_project_rows:
        ach_proj[(record['plant'], record['process_type'])].append(round(record['bol'], 2))
    Y['ach_projects'] = {k: sorted(v) for k, v in ach_proj.items()}

    # B5. 本年改善目标达成 (improveTarget vs 最新实际BOL)
    use('HRDB')
    r = rows(f"SELECT plant, process, programCode, programName, bol_budget, target_bol FROM CN_AME_IE_BOL_improveTarget WHERE year={year}")
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

    # B6. 瓶颈CT月度中位数 按工厂（近13个月）
    ct_start = f'{month_add(today.year, today.month, -13)[0]}-{month_add(today.year, today.month, -13)[1]:02d}-01'
    r = rows(f"""
        SELECT FORMAT(updateTime,'yyyy-MM'), company, cycleTime_bottleNeck
        FROM CN_IE_CT_bottleNeck_list
        WHERE updateTime >= '{ct_start}' AND cycleTime_bottleNeck IS NOT NULL
    """)
    mct = defaultdict(lambda: defaultdict(list))
    for ym, comp, ct in r:
        mct[ym][norm_plant(comp)].append(float(ct))
    months = sorted(mct.keys())
    Y['bn_monthly_by_plant'] = {
        'months': months,
        'series': {p: [round(median_ad(mct[ym].get(p, [])), 1) if mct[ym].get(p) else None
                       for ym in months]
                   for p in CT_PLANTS},
    }

    # B7. KPI年度 (BOL Reduction/Updates Rate, Actual CT Rate)
    r = rows(f"""
        SELECT kpi_name, year, month, location, kpi_value FROM CN_AME_KPI_monthlyHistory
        WHERE kpi_name IN ('BOL Reduction Rate','BOL Updates Rate','Acutal CT Rate')
            AND year IN ({year - 1}, {year})
        ORDER BY kpi_name, year, month, location
    """)
    kp = defaultdict(lambda: defaultdict(dict))
    for kn, y, m, loc, v in r:
        kp[kn][f'{y}-{m:02d}'][norm_plant(loc)] = f(v)
    Y['kpi_monthly'] = {k: dict(v) for k, v in kp.items()}
    Y['kpi_latest_month'] = max(
        (ym for kn, d in Y['kpi_monthly'].items() for ym in d.keys()
         if ym.startswith(str(year))), default=f'{year}-12')

    # B8. 本年 ACHIEVABLE(WON) 工艺×RoofType×工厂 组合级统计
    use('CMC')
    r = rows(f"""
        SELECT process_type, project_code, plant, bol FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year={year} AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
    """)
    r2 = rows(f"""
        SELECT program_number, typ_of_roof, topline_status FROM cbco_records
        WHERE year IN ({year}, {year + 1})
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
    combo_project_rows = defaultdict(list)
    for record in won_project_rows:
        combo_project_rows[(record['process_type'], record['roof_type'], record['plant'])].append(record['bol'])
    Y['ach_won_by_roof_plant'] = [
        {'process': pr, 'roof': roof, 'plant': plant, 'n': len(values),
         'avg': round(sum(values) / len(values), 2),
         'min': round(min(values), 2), 'max': round(max(values), 2)}
        for (pr, roof, plant), values in sorted(combo_project_rows.items())
    ]
    Y['ach_won_projects'] = len(won_projects)

    # B9. 上年 vs 本年 同项目（同工艺）Achievable BOL 变化
    r = rows(f"""
        SELECT fiscal_year, project_code, process_type, plant, bol FROM CN_IE_BOL_AchievableTargetBol
        WHERE bol_type='ACHIEVABLE' AND bol IS NOT NULL AND fiscal_year IN ({year - 1}, {year})
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
        if fy == year and (year - 1, pc, pr) in fy_map:
            pairs.append({'program': pc, 'process': pr,
                          'prev': round(fy_map[(year - 1, pc, pr)], 2), 'cur': round(v, 2),
                          'delta': round(v - fy_map[(year - 1, pc, pr)], 2)})
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
    Y['fy_pairs'] = pairs
    Y['fy_by_process'] = {
        pr: {'improved': v['improved'], 'stable': v['stable'], 'worse': v['worse'],
             'n': len(v['deltas']),
             'avg_delta': round(sum(v['deltas']) / len(v['deltas']), 2) if v['deltas'] else 0,
             'avg_delta_pct': round(sum(v['deltas']) / len(v['deltas']) /
                                    (sum(x['prev'] for x in pairs if x['process'] == pr) /
                                     max(1, sum(1 for x in pairs if x['process'] == pr))) * 100, 1)
        }
        for pr, v in fy_agg.items()}
    pairs.sort(key=lambda x: x['delta'])
    Y['fy_top_drop'] = pairs[:8]
    Y['fy_top_rise'] = sorted(pairs, key=lambda x: -x['delta'])[:8]

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

    # B11. 本年 ACHIEVABLE 覆盖范围（工厂×工艺 项目数）
    use('CMC')
    r = rows(f"""
        SELECT plant, process_type, COUNT(*), COUNT(DISTINCT project_code)
        FROM CN_IE_BOL_AchievableTargetBol
        WHERE fiscal_year={year} AND bol_type='ACHIEVABLE' AND bol IS NOT NULL
        GROUP BY plant, process_type
    """)
    Y['ach_coverage'] = [
        {'plant': norm_plant(pl), 'process': pr, 'rows': n, 'projects': np_}
        for pl, pr, n, np_ in r]

    cn.close()
    return Y

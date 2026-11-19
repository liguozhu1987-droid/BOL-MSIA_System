# -*- coding: utf-8 -*-
"""分析模块 视图：6大分析场景API

跨库查询约束：
  - hrdb 库（只读）：BolOverView（BOL更新记录）、ProgramInfo（项目主数据）、
    RealCtExtract / RealCtExtractPerDay / BottleNeckCt（实测CT及瓶颈CT）
  - default(CMC) 库（读写）：BudgetBol（年度预算BOL）、HighBolTracking（高BOL跟踪）
  - Django 不支持跨库 JOIN，所有跨库数据合并均在 Python 层完成，
    绝不使用 select_related / prefetch_related 跨库关联。

概念说明（重要）：
  - HRDB 中 CN_IE_CT_ 开头的表只采集 cycle time（CT），并不是 BOL。
  - BOL = CT × HC × (1+1/15) / OEE / 60，计算 BOL 必须有 HC。
  - 传感器系统只采集了 CT，没有 HC，因此无法直接换算 BOL。
  - 本模块通过 BolOverView 中的 HC/OEE，结合 BottleNeckCt 的实测瓶颈 CT，
    反推"由实测CT换算的BOL"（estimated_bol_from_ct），用于佐证人工提交 BOL 的合理性。
"""
from datetime import timedelta
import statistics as _stats

from django.db.models import Avg, Count, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.actual_ct.models import BottleNeckCt, KpiMonthlyHistory, RealCtExtract
from apps.budget_bol.models import BudgetBol
from apps.budget_bol.cbco_models import CbcoRecord
from apps.dynamic_bol.models import BolOverView, BolOverViewByProcess
from apps.projects.models import ProgramInfo
from apps.tracking.models import HighBolTracking
from bol_platform.bol_calc import calc_bol, calc_bol_gap
from bol_platform.plant_utils import normalize_plant, get_plant_raw_values, normalize_project_code

# ============================================================
# 工具函数
# ============================================================
def _f(v):
    """安全转换 Decimal/None → float/None"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _qstr(request, name):
    """取查询参数，去空白；空字符串视为未提供"""
    v = request.query_params.get(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def _qint(request, name, default=None):
    """取查询参数并转 int；失败或未提供返回 default"""
    v = _qstr(request, name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _qfloat(request, name, default=None):
    """取查询参数并转 float；失败或未提供返回 default"""
    v = _qstr(request, name)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _line_key(program_code, process, line_nr):
    """统一构造 (program_code, process, line_nr) 合并键，None 归一为 ''"""
    return (program_code or '', process or '', (line_nr or '').strip())


def _pp_key(program_code, process):
    """统一构造 (program_code, process) 合并键，None 归一为 ''"""
    return (program_code or '', process or '')


# ============================================================
# 1. 多维度BOL对比
# ============================================================
class BolComparisonView(APIView):
    """GET /api/analytics/comparison/

    查询参数：program_code(可选), location(可选), fiscal_year(可选)
    返回：指定项目的 QWS / 预算 / BOL更新记录 / 实测CT换算 多种BOL并排对比，按工艺分组
    """

    def get(self, request, *args, **kwargs):
        from apps.analytics.bol_aggregation import aggregate_bol_rows

        program_code = _qstr(request, 'program_code')
        location = _qstr(request, 'location')
        fiscal_year = _qint(request, 'fiscal_year')

        # === BOL 更新记录（hrdb 库）：final_approve_status='Approved'，按 program+process+line_nr 取最新 ===
        dyn_qs = BolOverView.objects.filter(final_approve_status='Approved')
        if program_code:
            dyn_qs = dyn_qs.filter(program_code=program_code)
        if location:
            dyn_qs = dyn_qs.filter(location__in=get_plant_raw_values(location))
        dyn_qs = dyn_qs.order_by('-submit_date')
        dyn_map = {}
        for r in dyn_qs.values(
            'program_code', 'process', 'line_nr', 'bol', 'qws_bol', 'ct', 'hc', 'oee',
        ):
            key = _line_key(r['program_code'], r['process'], r['line_nr'])
            if key not in dyn_map:
                dyn_map[key] = {
                    'qws_bol': _f(r['qws_bol']),
                    'latest_bol': _f(r['bol']),
                    'hc': _f(r['hc']),
                    'oee': _f(r['oee']),
                }

        # === 预算 BOL（default 库）：按 fiscal_year 和 project_code 过滤，未传 fiscal_year 则取最新财年 ===
        # BudgetBol 表结构已重构：字段 project_code / process_type / asset / budget_bol
        budget_qs = BudgetBol.objects.all()
        if program_code:
            budget_qs = budget_qs.filter(project_code=program_code)
        if location:
            # plant 字段可能含 _后缀（如 Beijing_IHE），需前缀匹配
            raw_vals = get_plant_raw_values(location)
            from django.db.models import Q as _Q
            plant_q = _Q()
            for v in raw_vals:
                plant_q |= _Q(plant=v) | _Q(plant__startswith=f'{v}_')
            budget_qs = budget_qs.filter(plant_q)
        if fiscal_year:
            budget_qs = budget_qs.filter(fiscal_year=fiscal_year)
        else:
            latest_fy = BudgetBol.objects.order_by('-fiscal_year').values_list(
                'fiscal_year', flat=True
            ).first()
            if latest_fy is not None:
                budget_qs = budget_qs.filter(fiscal_year=latest_fy)
        budget_map = {
            _line_key(r['project_code'], r['process_type'], r['asset']): r['bol']
            for r in aggregate_bol_rows(
                budget_qs.values('project_code', 'process_type', 'asset', 'plant', 'budget_bol'),
                'budget_bol', ('project_code', 'process_type', 'asset'),
            )
        }

        # === 瓶颈 CT（hrdb 库）：按 project_code 过滤（BottleNeckCt 字段名为 project_code），按 program+line_nr 取最新 ===
        bn_qs = BottleNeckCt.objects.all()
        if program_code:
            bn_qs = bn_qs.filter(project_code=program_code)
        bn_qs = bn_qs.order_by('-update_time')
        bn_map = {}
        for r in bn_qs.values(
            'project_code', 'line_nr', 'cycle_time_bottleneck', 'update_time',
        ):
            # BottleNeckCt 无 process 字段，按 program+line_nr 关联
            bn_key = (r['project_code'] or '', (r['line_nr'] or '').strip())
            if bn_key not in bn_map:
                bn_map[bn_key] = {
                    'bottleneck_ct': _f(r['cycle_time_bottleneck']),
                    'update_time': r['update_time'],
                }

        # === Python 层合并（绝不在SQL层JOIN）===
        all_keys = set(dyn_map) | set(budget_map)
        items = []
        for key in all_keys:
            program_code_, process, line_nr = key
            dyn = dyn_map.get(key, {})
            qws_bol = dyn.get('qws_bol')
            latest_bol = dyn.get('latest_bol')
            hc = dyn.get('hc')
            oee = dyn.get('oee')
            budget_bol = budget_map.get(key)
            # 瓶颈CT按 program+line_nr 关联
            bn_info = bn_map.get((program_code_, line_nr), {})
            bottleneck_ct = bn_info.get('bottleneck_ct')

            # 用BolOverView的hc和oee，结合BottleNeckCt的cycle_time_bottleneck，计算 estimated_bol_from_ct
            estimated_bol_from_ct = None
            if bottleneck_ct is not None and hc is not None and oee is not None:
                estimated_bol_from_ct = calc_bol(bottleneck_ct, hc, oee)

            # gap = latest - 基准（正值表示实际高于基准）
            gap_qws_vs_latest = None
            if latest_bol is not None and qws_bol is not None:
                gap_qws_vs_latest = calc_bol_gap(latest_bol, qws_bol)
            gap_budget_vs_latest = None
            if latest_bol is not None and budget_bol is not None:
                gap_budget_vs_latest = calc_bol_gap(latest_bol, budget_bol)

            items.append({
                'process': process,
                'line_nr': line_nr,
                'qws_bol': qws_bol,
                'budget_bol': budget_bol,
                'latest_bol': latest_bol,
                'bottleneck_ct': bottleneck_ct,
                'estimated_bol_from_ct': estimated_bol_from_ct,
                'gap_qws_vs_latest': gap_qws_vs_latest,
                'gap_budget_vs_latest': gap_budget_vs_latest,
            })
        items.sort(key=lambda x: (x['process'], x['line_nr']))
        return Response({
            'program_code': program_code,
            'items': items,
        })


# ============================================================
# 5.5 Achievable BOL 多年份同比（哑铃图数据源）
# ============================================================
def _calc_achievable_yoy_multi(years, plants=None, top_n=10):
    """Achievable BOL 多年份同比分析（同/环比趋势 Tab 主图）

    数据源：BOL 预算模块上传的 AchievableTargetBol（bol_type='ACHIEVABLE'）
    分组键：(project_code, process_type, 标准化工厂)；同年多条生产线 BOL 求和

    Args:
        years: 参与对比的财年列表（默认本年 vs 上年；可传 ≥2 个任意年份）
        plants: 工厂筛选（标准化短代码列表；None = 全部工厂）
        top_n: 按首末年份绝对差值排序取前 N；0 = 全部

    返回:
        {
          'options': {'years': [...], 'plants': [...]},   # 筛选器可选值（全量口径）
          'selected_years': [...],                        # 实际参与对比的年份（升序）
          'items': [
            {
              'label': 'T6875/FA' 或 'T6875/FA(BJ)',      # X 轴标签（跨工厂时带后缀）
              'project_code', 'process_type', 'plant',
              'project_name', 'volume',
              'values': {'2025': 12.3, '2026': 11.8},     # 各选中年份的 Achievable BOL
              'from_year', 'to_year', 'from_bol', 'to_bol',
              'diff', 'diff_pct',                          # to - from（负值=同比下降=改善）
            }, ...
          ]
        }
    """
    from apps.budget_bol.models import AchievableTargetBol
    from apps.analytics.bol_aggregation import aggregate_bol_rows

    # 年份规整：去重升序；不足 2 年时自动补最小年份的上一年
    years = sorted(set(int(y) for y in years if y))
    if len(years) < 2:
        base = years[0] if years else timezone.now().year
        years = sorted(set(years) | {base - 1})
    years_set = set(years)

    # ---- 筛选器可选值（全量 ACHIEVABLE 数据口径，不受当前筛选影响） ----
    opt_years = list(
        AchievableTargetBol.objects.filter(bol_type='ACHIEVABLE')
        .values_list('fiscal_year', flat=True).distinct().order_by('fiscal_year')
    )
    opt_plants = sorted({
        p for p in (normalize_plant(x) for x in
                    AchievableTargetBol.objects.filter(bol_type='ACHIEVABLE')
                    .values_list('plant', flat=True).distinct())
        if p and p != '未知'
    })

    # ---- 按项目+工艺汇总同年各产线，再构建跨年比较组 ----
    qs = AchievableTargetBol.objects.filter(
        fiscal_year__in=years, bol_type='ACHIEVABLE'
    ).order_by('fiscal_year', 'id').values(
        'fiscal_year', 'project_code', 'process_type', 'plant', 'bol'
    )
    eligible_rows = []
    for r in qs:
        std_plant = normalize_plant(r['plant'] or '')
        if not std_plant or std_plant == '未知':
            continue
        if plants and std_plant not in plants:
            continue
        eligible_rows.append({**r, 'plant': std_plant})

    groups = {}
    for r in aggregate_bol_rows(
        eligible_rows, 'bol', ('fiscal_year', 'project_code', 'process_type')
    ):
        key = (r['project_code'], r['process_type'])
        group = groups.setdefault(key, {'years': {}, 'plants': set()})
        group['years'][r['fiscal_year']] = r['bol']
        group['plants'].update(r['plants'])

    # ---- 项目名称 + volume（取各组最后对比年份，缺则取最新可得） ----
    all_codes = set(k[0] for k in groups.keys())
    vol_name = {}
    if all_codes:
        for r in CbcoRecord.objects.filter(
            program_number__in=list(all_codes), year__in=years
        ).order_by('-year').values('program_number', 'year', 'volume', 'program_description'):
            m = vol_name.setdefault(r['program_number'], {})
            m.setdefault(r['year'], {
                'volume': r['volume'] or 0,
                'name': r.get('program_description') or '',
            })

    def _meta(code, prefer_year):
        m = vol_name.get(code) or {}
        y = prefer_year if prefer_year in m else (max(m.keys()) if m else None)
        if y is None:
            return '', 0
        return m[y]['name'], m[y]['volume']

    # ---- 构建条目: 至少 2 个选中年份有值才具备同比意义 ----
    items = []
    for (code, process), group in groups.items():
        yearvals = group['years']
        ys = sorted(y for y in yearvals if y in years_set)
        if len(ys) < 2:
            continue
        from_bol, to_bol = yearvals[ys[0]], yearvals[ys[-1]]
        diff = to_bol - from_bol
        diff_pct = round(diff / from_bol * 100, 1) if from_bol > 0 else None
        name, volume = _meta(code, ys[-1])
        items.append({
            'project_code': code,
            'process_type': process,
            'plant': '/'.join(sorted(group['plants'])),
            'project_name': name or code,
            'volume': volume,
            'values': {str(y): round(yearvals[y], 2) for y in ys},
            'from_year': ys[0],
            'to_year': ys[-1],
            'from_bol': round(from_bol, 2),
            'to_bol': round(to_bol, 2),
            'diff': round(diff, 2),
            'diff_pct': diff_pct,
        })

    # 按首末年份绝对差值降序，取 Top N
    items.sort(key=lambda x: abs(x['diff']), reverse=True)
    if top_n and top_n > 0:
        items = items[:top_n]

    # 同一项目+工艺已汇总为一项，避免按产线重复出现在图中。
    for it in items:
        base_label = f"{it['project_code']}/{it['process_type'] or 'N/A'}"
        it['label'] = base_label

    return {
        'options': {'years': opt_years, 'plants': opt_plants},
        'selected_years': years,
        'items': items,
    }


# ============================================================
# 6. 综合看板概览
# ============================================================
class DashboardView(APIView):
    """GET /api/analytics/dashboard/

    综合看板：跨模块（BOL更新记录 + 预算BOL + 实测CT）综合分析。
    基于IE行业BOL生命周期管理最佳实践，提供：
      1. 跨模块核心KPI汇总
      2. BOL全链路对比（Budget → Achievable → Target → 实测BOL）
      3. SCT vs ACT差距分析
      4. 审批状态健康度
      5. 月度趋势（BOL审批 + CT采集）
      6. 工厂维度综合对比
      7. 改善机会预警列表
    """

    def get(self, request, *args, **kwargs):
        from apps.budget_bol.models import AchievableTargetBol
        current_year = timezone.now().year
        # 兜底：当年尚无预算数据时回退到库中最新财年（跨年切换期保护，
        # 确保 Budget/Achievable/Target 始终取自同一最新财年）
        if not BudgetBol.objects.filter(fiscal_year=current_year).exists():
            current_year = BudgetBol.objects.order_by('-fiscal_year').values_list(
                'fiscal_year', flat=True
            ).first() or current_year

        # 筛选参数（仅 plant_compare 使用，逗号分隔多值）
        plants_param = _qstr(request, 'plants')
        process_types_param = _qstr(request, 'process_types')
        roof_types_param = _qstr(request, 'roof_types')
        # Tab 1 全链路 单独的工厂筛选（与 plant_compare 的 plants 分开命名）
        lifecycle_plants_param = _qstr(request, 'lifecycle_plants')
        plants = [p for p in plants_param.split(',')] if plants_param else None
        process_types = [p for p in process_types_param.split(',')] if process_types_param else None
        roof_types = [p for p in roof_types_param.split(',')] if roof_types_param else None
        lifecycle_plants = [p for p in lifecycle_plants_param.split(',')] if lifecycle_plants_param else None

        # Tab 3 工厂对比年份（默认当前年）
        compare_year = _qint(request, 'year') or current_year

        # ============================================================
        # 并行执行独立查询块
        # ------------------------------------------------------------
        # 本接口原为串行跨库查询（HRDB + CMC 每块数百毫秒网络往返），
        # 累计 3.5~4 秒，是页面进入慢的主因。各查询块只依赖
        # 年份/筛选参数、彼此无依赖，改为线程池并行后总耗时
        # 约等于最慢单块。GIL 在 SQL 网络等待期间释放，并行有效。
        # ============================================================

        def _kpi_counts():
            # KPI 1/7: BOL 审批率（本年 Approved/Total；HRDB 待审状态值为 Ongoing）
            qs = BolOverView.objects.filter(submit_date__year=current_year)
            total = qs.count()
            approved = qs.filter(final_approve_status='Approved').count()
            pending = qs.filter(final_approve_status='Ongoing').count()
            return total, approved, pending

        def _target_total():
            # KPI 6: Target 达成率分母（排除工厂无法标准化的记录）
            total = 0.0
            for r in AchievableTargetBol.objects.filter(
                fiscal_year=current_year, bol_type='TARGET'
            ).values('plant', 'bol'):
                std_plant = normalize_plant(r['plant'])
                if std_plant and std_plant != '未知':
                    v = _f(r['bol'])
                    if v:
                        total += v
            return total

        def _plant_options():
            # 工厂选项（2026 BudgetBol + Achievable 的工厂并集，作为前端下拉项）
            plant_set = set()
            for r in BudgetBol.objects.filter(fiscal_year=current_year, bol_type='BUDGET').values('plant'):
                sp = normalize_plant(r.get('plant') or '')
                if sp and sp != '未知':
                    plant_set.add(sp)
            for r in AchievableTargetBol.objects.filter(fiscal_year=current_year, bol_type='ACHIEVABLE').values('plant'):
                sp = normalize_plant(r.get('plant') or '')
                if sp and sp != '未知':
                    plant_set.add(sp)
            return sorted(plant_set)

        tasks = [
            (_kpi_counts, (), {}),
            (self._load_ame_kpis, (current_year,), {}),
            (self._calc_plant_achievement, (current_year,), {}),
            (_target_total, (), {}),
            (lambda: HighBolTracking.objects.filter(
                status__in=['OPEN', 'IN_PROGRESS']).count(), (), {}),
            (self._calc_bol_lifecycle, (current_year,), {'plants': lifecycle_plants}),
            (_plant_options, (), {}),
            (self._calc_improvement_opportunities, (current_year,), {}),
            (self._calc_improvement_opportunities, (current_year,), {'direction': 'up'}),
            (_calc_achievable_yoy_multi,
             ([current_year - 1, current_year],), {'plants': None, 'top_n': 10}),
            (self._calc_yearly_compare, (current_year,), {}),
            (self._calc_plant_compare, (compare_year,),
             {'plants': plants, 'process_types': process_types, 'roof_types': roof_types}),
        ]
        (total_bol_records, approved_count, pending_count), \
            ame_kpis, plant_achievement, target_total, tracking_open, \
            bol_lifecycle, lifecycle_plant_options, \
            improvement_opportunities, improvement_increases, \
            achievable_yoy, yearly_compare, plant_compare = self._run_parallel(tasks)

        # ============================================================
        # KPI 卡片数据（8 项，用于 Tab 4 KPI 总览）
        # ============================================================
        approval_rate = round(approved_count / total_bol_records * 100, 1) if total_bol_records > 0 else 0
        # KPI 5: Budget 达成率（反转口径 ΣBudget/ΣAchievable，<100% 为达成）
        total_budget = sum(p['budget'] for p in plant_achievement)
        total_achievable = sum(p['achievable'] for p in plant_achievement)
        budget_achievement_rate = round(total_budget / total_achievable * 100, 1) if total_achievable > 0 else 0
        target_achievement_rate = round(total_achievable / target_total * 100, 1) if target_total > 0 else 0

        kpi_cards = {
            'approval_rate': approval_rate,
            'approved_count': approved_count,
            'total_bol_records': total_bol_records,
            'pending_count': pending_count,
            'ct_capture_rate': ame_kpis['Acutal CT Rate']['cmc_pct'] or 0,
            'bol_reduction_rate': ame_kpis['BOL Reduction Rate']['cmc_pct'] or 0,
            'bol_updates_rate': ame_kpis['BOL Updates Rate']['cmc_pct'] or 0,
            'lb_rate': ame_kpis['LB']['cmc_pct'] or 0,
            'budget_achievement_rate': budget_achievement_rate,
            'target_achievement_rate': target_achievement_rate,
            'tracking_open': tracking_open,
        }

        return Response({
            'kpi_cards': kpi_cards,
            'bol_lifecycle': bol_lifecycle,
            'bol_lifecycle_plant_options': lifecycle_plant_options,
            'improvement_opportunities': improvement_opportunities,
            'improvement_increases': improvement_increases,
            'achievable_yoy': achievable_yoy,
            'yearly_compare': yearly_compare,
            'plant_compare': plant_compare,
            'plant_achievement': plant_achievement,
            'ame_kpis': ame_kpis,
        })

    def _run_parallel(self, tasks):
        """并行执行互不依赖的查询块，按提交顺序返回结果。

        tasks: [(fn, args, kwargs), ...]
        - 任务均为 IO 密集（跨库 SQL 网络往返），GIL 在等待期释放，并行有效
        - worker 线程结束后关闭该线程持有的数据库连接（Django 连接按线程
          隔离），避免线程池销毁时 ODBC 连接泄漏
        - 任一任务异常会原样抛出（与串行执行的错误行为一致）
        """
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections

        def _wrap(fn, args, kwargs):
            try:
                return fn(*args, **kwargs)
            finally:
                # 仅关闭当前 worker 线程的连接（connections 为 threading.local）
                connections.close_all()

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(_wrap, fn, args, kwargs) for fn, args, kwargs in tasks]
            return [f.result() for f in futures]

    def _calc_sct_act_gap_pct(self):
        """计算 SCT vs ACT 平均差距百分比"""
        from apps.dynamic_bol.models import BolOverView
        # ACT: 瓶颈CT最新记录（按 项目+产线+工厂 取最新一条）
        act_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull=False)
        act_map = {}
        for r in act_qs.values('project_code', 'line_nr', 'company', 'cycle_time_bottleneck').order_by('-update_time'):
            key = (r['project_code'], r['line_nr'], normalize_plant(r.get('company') or ''))
            if key not in act_map:
                act_map[key] = float(r['cycle_time_bottleneck'])

        # SCT: BOL审批通过的最新CT
        sct_qs = BolOverView.objects.filter(
            final_approve_status='Approved', ct__isnull=False
        ).values('program_code', 'line_nr', 'location', 'ct').order_by('-submit_date')
        sct_map = {}
        for r in sct_qs:
            key = (r['program_code'], r['line_nr'], normalize_plant(r.get('location') or ''))
            if key not in sct_map:
                sct_map[key] = float(r['ct'])

        # 匹配并计算差距（精确匹配，不做兜底）
        gaps = []
        for key, sct in sct_map.items():
            act = act_map.get(key)
            if act and act > 0:
                gap_pct = (sct - act) / sct * 100
                gaps.append(gap_pct)

        return round(sum(gaps) / len(gaps), 1) if gaps else 0

    def _calc_sct_act_gap_over_count(self, threshold_pct=15):
        """计算 SCT vs ACT 差距超过指定百分比的项目数

        Args:
            threshold_pct: 差距百分比阈值（默认 15）
        """
        from apps.dynamic_bol.models import BolOverView
        act_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull=False)
        act_map = {}
        for r in act_qs.values('project_code', 'line_nr', 'company', 'cycle_time_bottleneck').order_by('-update_time'):
            key = (r['project_code'], r['line_nr'], normalize_plant(r.get('company') or ''))
            if key not in act_map:
                act_map[key] = float(r['cycle_time_bottleneck'])

        sct_qs = BolOverView.objects.filter(
            final_approve_status='Approved', ct__isnull=False
        ).values('program_code', 'line_nr', 'location', 'ct').order_by('-submit_date')
        sct_map = {}
        for r in sct_qs:
            key = (r['program_code'], r['line_nr'], normalize_plant(r.get('location') or ''))
            if key not in sct_map:
                sct_map[key] = float(r['ct'])

        count = 0
        for key, sct in sct_map.items():
            # 精确匹配，不做兜底
            act = act_map.get(key)
            if act and act > 0 and sct > 0:
                gap_pct = abs((sct - act) / sct * 100)
                if gap_pct > threshold_pct:
                    count += 1
        return count

    def _calc_bol_approval_detail(self, current_year, limit=100):
        """本年度 BOL 审批更新记录明细（用于指标卡详情弹窗）

        返回字段对齐 BOL 更新记录模块的列表：提交人、提交时间、CT、HC、OEE、BOL 值等。
        """
        qs = BolOverView.objects.filter(submit_date__year=current_year).order_by('-submit_date')[:limit]
        items = []
        for r in qs.values(
            'bol_nr', 'program_code', 'program_name', 'customer', 'location',
            'process', 'type', 'line_nr', 'ct', 'hc', 'oee', 'bol',
            'qws_bol', 'gap_bol', 'final_approve_status', 'submit_date',
            'submit_user_name',
        ):
            items.append({
                'bol_nr': r['bol_nr'],
                'program_code': r['program_code'],
                'program_name': r['program_name'],
                'customer': r['customer'],
                'location': normalize_plant(r['location']),
                'process': r['process'],
                'type': r['type'],
                'line_nr': r['line_nr'],
                'ct': _f(r['ct']),
                'hc': _f(r['hc']),
                'oee': _f(r['oee']),
                'bol': _f(r['bol']),
                'qws_bol': _f(r['qws_bol']),
                'gap_bol': _f(r['gap_bol']),
                'final_approve_status': r['final_approve_status'] or '',
                'submit_date': r['submit_date'].strftime('%Y-%m-%d %H:%M') if r['submit_date'] else '',
                'submit_user_name': r['submit_user_name'] or '',
            })
        return items

    def _calc_ct_programs_detail(self, current_year, limit=100):
        """实测 CT 覆盖项目明细（用于指标卡详情弹窗）

        按项目代码聚合 RealCtExtract（本年度），返回项目级清单：
        项目代码、项目名称、工厂、产线数、工位数、最新采集时间。
        """
        from django.db.models import Count as _Count, Max as _Max

        qs = RealCtExtract.objects.filter(
            update_time__year=current_year
        ).values('project_code', 'project_name', 'company').annotate(
            line_count=_Count('line_nr', distinct=True),
            station_count=_Count('station_nr', distinct=True),
            latest_update=_Max('update_time'),
        ).order_by('-latest_update')[:limit]

        items = []
        for r in qs:
            items.append({
                'project_code': r['project_code'],
                'project_name': r['project_name'],
                'company': normalize_plant(r['company']),
                'line_count': r['line_count'],
                'station_count': r['station_count'],
                'latest_update': r['latest_update'].strftime('%Y-%m-%d %H:%M') if r['latest_update'] else '',
            })
        return items

    def _calc_net_hours_saved(self, current_year):
        """计算本财年 Budget BOL 对比上一财年的净节省工时"""
        from apps.budget_bol.cbco_models import CbcoRecord
        from apps.analytics.bol_aggregation import aggregate_bol_rows
        from_year = current_year - 1
        to_year = current_year

        from_records = aggregate_bol_rows(BudgetBol.objects.filter(
            fiscal_year=from_year, bol_type='BUDGET'
        ).values('project_code', 'process_type', 'budget_bol'), 'budget_bol',
            ('project_code', 'process_type'))
        to_records = aggregate_bol_rows(BudgetBol.objects.filter(
            fiscal_year=to_year, bol_type='BUDGET'
        ).values('project_code', 'process_type', 'budget_bol'), 'budget_bol',
            ('project_code', 'process_type'))

        from_map = {
            (r['project_code'], r['process_type']): r['bol']
            for r in from_records
        }
        to_map = {
            (r['project_code'], r['process_type']): r['bol']
            for r in to_records
        }

        all_codes = set(r['project_code'] for r in from_records) | set(r['project_code'] for r in to_records)
        volume_map = {}
        if all_codes:
            for r in CbcoRecord.objects.filter(
                program_number__in=list(all_codes), year=to_year
            ).values('program_number', 'volume'):
                volume_map[r['program_number']] = r['volume'] or 0

        common_keys = set(from_map.keys()) & set(to_map.keys())
        total_hours = 0.0
        for key in common_keys:
            from_bol = from_map[key]
            to_bol = to_map[key]
            if from_bol is None or to_bol is None or from_bol <= 0 or to_bol <= 0:
                continue
            to_vol = volume_map.get(key[0], 0)
            bol_reduction = from_bol - to_bol
            hours_saved = to_vol * bol_reduction / 60 if to_vol > 0 else 0
            total_hours += hours_saved

        return round(total_hours, 1)

    def _calc_bol_lifecycle(self, current_year, plants=None):
        """BOL 全链路对比：Budget → Achievable → Target → 实测BOL

        实测BOL 计算方式：
          BOL = CT × HC × (1+1/15) / OEE / 60
          - CT  来自 BottleNeckCt（按 project_code + line_nr 取最新瓶颈工时）
          - HC  来自 BolOverViewByProcess（按 program_code + line_nr + process 取最新提交记录）
          - OEE 来自 BolOverViewByProcess（同上）

        Top10 选择标准：当年 CBCO_record 中 Volume 需求最高的项目
        plants: 标准化工厂短代码列表（None=全部；传多工厂取它们项目的并集综合排序）
        """
        from apps.budget_bol.models import AchievableTargetBol
        from apps.analytics.bol_aggregation import aggregate_bol_rows

        # 取本财年三类预算 BOL（Budget / Achievable 按 plant 归属）
        budget_rows = []
        for r in BudgetBol.objects.filter(
            fiscal_year=current_year, bol_type='BUDGET'
        ).values('project_code', 'process_type', 'budget_bol', 'plant'):
            sp = normalize_plant(r.get('plant') or '')
            if not sp or sp == '未知':
                continue
            if plants and sp not in plants:
                continue
            budget_rows.append({**r, 'plant': sp})
        budget_map = {
            (r['project_code'], r['process_type']): {
                'value': r['bol'], 'plant': '/'.join(r['plants'])
            }
            for r in aggregate_bol_rows(
                budget_rows, 'budget_bol', ('project_code', 'process_type')
            )
        }

        achievable_rows = []
        for r in AchievableTargetBol.objects.filter(
            fiscal_year=current_year, bol_type='ACHIEVABLE'
        ).values('project_code', 'process_type', 'bol', 'plant'):
            sp = normalize_plant(r.get('plant') or '')
            if not sp or sp == '未知':
                continue
            if plants and sp not in plants:
                continue
            achievable_rows.append({**r, 'plant': sp})
        achievable_map = {
            (r['project_code'], r['process_type']): {
                'value': r['bol'], 'plant': '/'.join(r['plants'])
            }
            for r in aggregate_bol_rows(
                achievable_rows, 'bol', ('project_code', 'process_type')
            )
        }

        target_rows = []
        for r in AchievableTargetBol.objects.filter(
            fiscal_year=current_year, bol_type='TARGET'
        ).values('project_code', 'process_type', 'bol', 'plant'):
            sp = normalize_plant(r.get('plant') or '')
            if not sp or sp == '未知':
                continue
            if plants and sp not in plants:
                continue
            target_rows.append({**r, 'plant': sp})
        target_map = {
            (r['project_code'], r['process_type']): r['bol']
            for r in aggregate_bol_rows(
                target_rows, 'bol', ('project_code', 'process_type')
            )
        }

        # === 实测 BOL 公式计算 ===
        # 1. 从 BolOverViewByProcess 获取 HC 和 OEE（按 program_code + process 取最新提交记录）
        #    key: (program_code, process) → {hc, oee, line_nr}
        bp_qs = BolOverViewByProcess.objects.filter(
            hc__isnull=False, oee__isnull=False
        ).order_by('-update_time')
        bp_map = {}
        for r in bp_qs.values('program_code', 'process', 'line_nr', 'hc', 'oee', 'update_time'):
            key = (r['program_code'], r['process'])
            if key not in bp_map:
                bp_map[key] = {
                    'hc': _f(r['hc']),
                    'oee': _f(r['oee']),
                    'line_nr': (r['line_nr'] or '').strip(),
                }

        # 2. 从 BottleNeckCt 获取瓶颈 CT（按 project_code + line_nr 取最新）
        #    key: (project_code, line_nr) → bottleneck_ct
        bn_qs = BottleNeckCt.objects.filter(
            cycle_time_bottleneck__isnull=False
        ).order_by('-update_time')
        bn_map = {}
        for r in bn_qs.values('project_code', 'line_nr', 'cycle_time_bottleneck'):
            bn_key = (r['project_code'] or '', (r['line_nr'] or '').strip())
            if bn_key not in bn_map:
                bn_map[bn_key] = _f(r['cycle_time_bottleneck'])

        # 3. 按 (project_code, process) 计算实测 BOL
        actual_map = {}  # (project_code, process) → estimated_bol
        for key, bp_info in bp_map.items():
            program_code, process = key
            line_nr = bp_info.get('line_nr', '')
            hc = bp_info.get('hc')
            oee = bp_info.get('oee')
            # 精确匹配 project_code + line_nr，不做兜底
            bottleneck_ct = bn_map.get((program_code, line_nr)) if line_nr else None
            if bottleneck_ct is not None and hc is not None and oee is not None:
                actual_map[key] = calc_bol(bottleneck_ct, hc, oee)

        # === 当年 CBCO Volume 和项目名称（用于 Top25 排序和显示）===
        volume_map = {}  # project_code → volume
        name_map = {}    # project_code → program_description
        for r in CbcoRecord.objects.filter(
            year=current_year, volume__isnull=False
        ).values('program_number', 'volume', 'program_description'):
            code = r['program_number']
            if code:
                if code not in volume_map:
                    volume_map[code] = r['volume'] or 0
                if code not in name_map and r.get('program_description'):
                    name_map[code] = r['program_description']

        # 合并：取 Budget 和 Achievable 都有的项目
        common_keys = set(budget_map.keys()) & set(achievable_map.keys())
        items = []
        for key in common_keys:
            b_entry = budget_map.get(key)
            a_entry = achievable_map.get(key)
            budget = b_entry['value'] if b_entry else None
            achievable = a_entry['value'] if a_entry else None
            # plant 归属：以 Budget 为准，否则 Achievable 的 plant
            plant = b_entry['plant'] if b_entry else (a_entry['plant'] if a_entry else '')
            target = target_map.get(key)
            actual = actual_map.get(key)
            if budget is None or achievable is None or budget <= 0:
                continue
            gap = budget - achievable
            # 节省率 = (Budget - Achievable)/Budget × 100：正值=Achievable低于预算(节省)，负值=超预算
            saving_pct = round(gap / budget * 100, 1) if budget > 0 else None
            volume = volume_map.get(key[0], 0)
            # 计算实测BOL与Achievable BOL的差距百分比
            actual_ach_gap_pct = None
            if actual is not None and achievable and achievable > 0:
                actual_ach_gap_pct = round((actual - achievable) / achievable * 100, 1)
            items.append({
                'project_code': key[0],
                'project_name': name_map.get(key[0], key[0]),
                'process_type': key[1],
                'plant': plant,
                'budget': round(budget, 2),
                'achievable': round(achievable, 2),
                'target': round(target, 2) if target else None,
                'actual': round(actual, 2) if actual else None,
                'gap': round(gap, 2),
                'saving_pct': saving_pct,
                'volume': volume,
                'actual_ach_gap_pct': actual_ach_gap_pct,
            })

        # 排序：FA 优先，然后按当年 Volume 需求降序，取 Top 20
        items.sort(key=lambda x: (
            0 if x['process_type'] == 'FA' else 1,  # FA 排前
            -x['volume'],                            # Volume 降序
        ))
        return items[:20]

    def _calc_sct_vs_act_top(self):
        """SCT vs ACT 差距 Top 10"""
        from apps.dynamic_bol.models import BolOverView

        # ACT: 瓶颈CT最新记录（按 项目+产线+工厂 取最新一条）
        act_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull=False)
        act_map = {}
        act_info = {}
        for r in act_qs.values('company', 'project_code', 'project_name', 'line_nr',
                               'cycle_time_bottleneck').order_by('-update_time'):
            std_company = normalize_plant(r.get('company') or '')
            key = (r['project_code'], r['line_nr'], std_company)
            if key not in act_map:
                act_map[key] = float(r['cycle_time_bottleneck'])
                act_info[key] = {
                    'company': std_company,
                    'project_name': r['project_name'] or '',
                }

        # SCT: BOL审批通过的最新CT
        sct_qs = BolOverView.objects.filter(
            final_approve_status='Approved', ct__isnull=False
        ).values('program_code', 'line_nr', 'process', 'location', 'ct').order_by('-submit_date')
        sct_map = {}
        sct_process = {}
        for r in sct_qs:
            std_loc = normalize_plant(r.get('location') or '')
            key = (r['program_code'], r['line_nr'], std_loc)
            if key not in sct_map:
                sct_map[key] = float(r['ct'])
                sct_process[key] = r['process'] or ''

        # 匹配并计算差距（精确匹配，不做兜底）
        items = []
        for key, sct in sct_map.items():
            act = act_map.get(key)
            if act and act > 0 and sct > 0:
                gap = sct - act
                gap_pct = gap / sct * 100
                info = act_info.get(key, {})
                items.append({
                    'project_code': key[0],
                    'project_name': info.get('project_name', ''),
                    'line_nr': key[1],
                    'process': sct_process.get(key, ''),
                    'company': info.get('company', key[2]),
                    'sct': round(sct, 2),
                    'act': round(act, 2),
                    'gap': round(gap, 2),
                    'gap_pct': round(gap_pct, 1),
                })

        # 按差距百分比升序（负值越大表示ACT远超SCT，最需要改善）
        items.sort(key=lambda x: x['gap_pct'])
        return items[:10]

    def _calc_yearly_compare(self, current_year, years_n=3):
        """近 3 年 Budget vs Achievable 总量对比（支持下钻明细）

        返回结构：
          - years/budget/achievable: 年度总量（顶层视图）
          - detail: 扁平明细 [{year, plant, process, budget, achievable}]
            前端按 年 → 工厂 → 工艺 三级钻取聚合
        用于 Tab 2 副图（点击柱子下钻）
        """
        from apps.budget_bol.models import AchievableTargetBol
        from apps.analytics.bol_aggregation import aggregate_bol_rows
        from collections import defaultdict
        years = list(range(current_year - years_n + 1, current_year + 1))

        # 聚合键: (year, plant, process) → {budget, achievable}
        agg = defaultdict(lambda: {'budget': 0.0, 'achievable': 0.0})

        for y in years:
            budget_rows = aggregate_bol_rows(BudgetBol.objects.filter(
                fiscal_year=y, bol_type='BUDGET'
            ).values('project_code', 'plant', 'process_type', 'budget_bol'),
                'budget_bol', ('project_code', 'plant', 'process_type'))
            for r in budget_rows:
                std_plant = r['plant']
                if not std_plant or std_plant == '未知':
                    continue
                process = (r['process_type'] or '').strip() or 'N/A'
                key = (y, std_plant, process)
                agg[key]['budget'] += r['bol']

            achievable_rows = aggregate_bol_rows(AchievableTargetBol.objects.filter(
                fiscal_year=y, bol_type='ACHIEVABLE'
            ).values('project_code', 'plant', 'process_type', 'bol'),
                'bol', ('project_code', 'plant', 'process_type'))
            for r in achievable_rows:
                std_plant = r['plant']
                if not std_plant or std_plant == '未知':
                    continue
                process = (r['process_type'] or '').strip() or 'N/A'
                key = (y, std_plant, process)
                agg[key]['achievable'] += r['bol']

        detail = [
            {
                'year': y,
                'plant': p,
                'process': proc,
                'budget': round(vals['budget'], 2),
                'achievable': round(vals['achievable'], 2),
            }
            for (y, p, proc), vals in sorted(agg.items())
        ]

        # 年度总量（由 detail 汇总，保证层级间口径一致）
        budget_by_year = {y: 0.0 for y in years}
        achievable_by_year = {y: 0.0 for y in years}
        for d in detail:
            budget_by_year[d['year']] += d['budget']
            achievable_by_year[d['year']] += d['achievable']

        return {
            'years': [str(y) for y in years],
            'budget': [round(budget_by_year[y], 2) for y in years],
            'achievable': [round(achievable_by_year[y], 2) for y in years],
            'detail': detail,
        }

    @staticmethod
    def _percentile(sorted_vals, p):
        """线性插值百分位数（与 ECharts boxplot / Excel PERCENTILE.INC 口径一致）"""
        n = len(sorted_vals)
        if n == 1:
            return sorted_vals[0]
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])

    def _calc_plant_compare(self, compare_year, plants=None, process_types=None, roof_types=None):
        """工厂间 Achievable BOL 分布对比（箱线图统计）

        X 轴=工厂，Y 轴=Achievable BOL；各工厂项目 BOL 的 min/Q1/median/Q3/max/mean/count
        筛选：plants（工厂短代码多选）/ process_types（FA/IHR/IHE 多选）/ roof_types（产品类型多选）
        产品类型：cbco_records.typ_of_roof 实际值（program_number ↔ project_code + 同财年关联）
        返回：{year, available_years, roof_type_options, stats}
        """
        from apps.budget_bol.models import AchievableTargetBol
        from apps.analytics.bol_aggregation import aggregate_bol_rows
        from collections import defaultdict

        # 可选财年（有 Achievable 数据的年份，降序）
        available_years = sorted({
            y for y in AchievableTargetBol.objects
            .filter(bol_type='ACHIEVABLE')
            .values_list('fiscal_year', flat=True)
            .distinct() if y
        }, reverse=True)

        # 产品类型选项：cbco_records.typ_of_roof 去重（实际业务值，不限于 BL/TL）
        roof_type_options = sorted({
            (v or '').strip()
            for v in CbcoRecord.objects
            .exclude(typ_of_roof__isnull=True)
            .exclude(typ_of_roof='')
            .values_list('typ_of_roof', flat=True)
            .distinct() if (v or '').strip()
        })

        qs = AchievableTargetBol.objects.filter(
            fiscal_year=compare_year, bol_type='ACHIEVABLE'
        ).values('project_code', 'process_type', 'plant', 'bol')

        # 应用 process_type 筛选
        if process_types:
            qs = qs.filter(process_type__in=process_types)

        # 应用 plant 筛选（plants 为标准化短代码列表，逐个反查原始值变体）
        if plants:
            raw_values = []
            for p in plants:
                raw_values.extend(get_plant_raw_values(p))
            qs = qs.filter(plant__in=raw_values)

        # 先按项目+工艺+标准化工厂求和各产线记录
        items_map = {}
        for r in aggregate_bol_rows(
            qs, 'bol', ('project_code', 'process_type', 'plant')
        ):
            std_plant = r['plant']
            if not std_plant or std_plant == '未知':
                continue
            if plants and std_plant not in plants:
                continue
            key = (r['project_code'], r['process_type'], std_plant)
            items_map[key] = {
                'project_code': r['project_code'],
                'plant': std_plant,
                'process_type': r['process_type'],
                'bol': r['bol'],
            }

        # 获取 roof_type / volume / 项目名称（cbco_records.program_number = project_code，同财年；
        # 同一项目同年多条记录时取首条非空值）
        all_codes = set(k[0] for k in items_map.keys())
        roof_map = {}
        volume_map = {}
        name_map = {}
        if all_codes:
            for r in CbcoRecord.objects.filter(
                program_number__in=list(all_codes), year=compare_year
            ).values('program_number', 'typ_of_roof', 'volume', 'program_description'):
                code = r['program_number']
                val = (r.get('typ_of_roof') or '').strip()
                if code not in roof_map or (val and not roof_map[code]):
                    roof_map[code] = val
                if code not in volume_map:
                    volume_map[code] = r.get('volume') or 0
                if code not in name_map and r.get('program_description'):
                    name_map[code] = r['program_description']

        # 应用 roof_type 筛选后，按工厂收集 BOL 值（同时保留项目级明细供前端钻取）
        vals_by_plant = defaultdict(list)
        details = []
        for (project_code, _process, _plant), v in items_map.items():
            if roof_types and roof_map.get(project_code, '') not in roof_types:
                continue
            if v['bol'] is not None:
                vals_by_plant[v['plant']].append(v['bol'])
                details.append({
                    'project_code': project_code,
                    'project_name': name_map.get(project_code, project_code),
                    'plant': v['plant'],
                    'process_type': v['process_type'],
                    'bol': round(v['bol'], 2),
                    'roof_type': roof_map.get(project_code, ''),
                    'volume': volume_map.get(project_code, 0),
                })

        # 各工厂箱线图统计（统计值四舍五入 2 位，count 为整数项目数）
        stats = []
        for plant, vals in vals_by_plant.items():
            if not vals:
                continue
            vals_sorted = sorted(vals)
            stats.append({
                'plant': plant,
                'count': len(vals_sorted),
                'min': round(_f(vals_sorted[0]), 2),
                'q1': round(self._percentile(vals_sorted, 0.25), 2),
                'median': round(self._percentile(vals_sorted, 0.5), 2),
                'q3': round(self._percentile(vals_sorted, 0.75), 2),
                'max': round(_f(vals_sorted[-1]), 2),
                'mean': round(sum(vals_sorted) / len(vals_sorted), 2),
            })

        # 按中位数降序排列，便于横向对比
        stats.sort(key=lambda s: -s['median'])
        # 明细按 BOL 降序
        details.sort(key=lambda d: -(d['bol'] or 0))
        return {
            'year': compare_year,
            'available_years': available_years,
            'roof_type_options': roof_type_options,
            'stats': stats,
            'details': details,
        }

    def _calc_plant_achievement(self, current_year):
        """各工厂 Budget 达成率（ΣAchievable / ΣBudget）

        用于 Tab 4 各工厂达成率分组柱状
        """
        from apps.budget_bol.models import AchievableTargetBol
        from collections import defaultdict

        # 按 plant 聚合 Budget
        budget_by_plant = defaultdict(float)
        for r in BudgetBol.objects.filter(
            fiscal_year=current_year, bol_type='BUDGET'
        ).values('plant', 'budget_bol'):
            std_plant = normalize_plant(r['plant'])
            if std_plant and std_plant != '未知':
                v = _f(r['budget_bol'])
                if v:
                    budget_by_plant[std_plant] += v

        # 按 plant 聚合 Achievable
        ach_by_plant = defaultdict(float)
        for r in AchievableTargetBol.objects.filter(
            fiscal_year=current_year, bol_type='ACHIEVABLE'
        ).values('plant', 'bol'):
            std_plant = normalize_plant(r['plant'])
            if std_plant and std_plant != '未知':
                v = _f(r['bol'])
                if v:
                    ach_by_plant[std_plant] += v

        # 计算达成率（反转口径 ΣBudget/ΣAchievable，<100% 为达成，符合常规阅读习惯）
        all_plants = set(budget_by_plant.keys()) | set(ach_by_plant.keys())
        result = []
        for plant in sorted(all_plants):
            budget = budget_by_plant.get(plant, 0)
            achievable = ach_by_plant.get(plant, 0)
            achievement_rate = round(budget / achievable * 100, 1) if achievable > 0 else 0
            result.append({
                'plant': plant,
                'budget': round(budget, 2),
                'achievable': round(achievable, 2),
                'achievement_rate': achievement_rate,
            })
        return result

    # HRDB CN_AME_KPI_monthlyHistory 中与 BOL 相关的 KPI 名称
    AME_KPI_NAMES = ('Acutal CT Rate', 'BOL Reduction Rate', 'BOL Updates Rate', 'LB')

    def _load_ame_kpis(self, current_year):
        """从 HRDB CN_AME_KPI_monthlyHistory 读取 BOL 相关官方 KPI 值

        每个指标取本年最新月份，按工厂返回；kpi_value 为小数，转为百分比。
        返回 {kpi_name: {'month': m, 'by_plant': {plant: pct}, 'avg_pct': x, 'cmc_pct': y}}
        用于 KPI 卡（CMC 区域值）+ Tab 4 图表（分工厂，CMC 由前端追加在最后）
        """
        result = {}
        for kpi_name in self.AME_KPI_NAMES:
            qs = KpiMonthlyHistory.objects.filter(
                year=current_year, kpi_name=kpi_name
            )
            latest_month = qs.order_by('-month').values_list(
                'month', flat=True
            ).first()
            if latest_month is None:
                result[kpi_name] = {
                    'month': None, 'by_plant': {}, 'avg_pct': 0, 'cmc_pct': None
                }
                continue
            by_plant = {}
            for r in qs.filter(month=latest_month).values('location', 'kpi_value'):
                plant = normalize_plant(r['location'] or '')
                v = _f(r['kpi_value'])
                if plant and plant != '未知' and v is not None:
                    by_plant[plant] = round(v * 100, 1)
            # CMC 为区域汇总值（汇总所有工厂），从工厂数据中分离，不参与均值
            cmc_pct = by_plant.pop('CMC', None)
            avg_pct = round(
                sum(by_plant.values()) / len(by_plant), 1
            ) if by_plant else 0
            result[kpi_name] = {
                'month': latest_month,
                'by_plant': by_plant,
                'avg_pct': avg_pct,
                'cmc_pct': cmc_pct,
            }
        return result

    def _calc_improvement_opportunities(self, current_year, plants=None, direction='down'):
        """Achievable BOL 同比项目清单（全量，按变动幅度降序）

        仅做客观的 BOL 同比对比（本年 vs 上年），不做人年（HC）换算。
        同一项目+工艺在筛选范围内的多条产线记录先按年求和。
        用于 同/环比趋势 Tab 副表。
        direction: 'down'=下降清单（改善，本年<上年）；'up'=上升清单（恶化，本年>上年）
        plants: 标准化工厂短代码列表（None=全部）
        """
        from apps.budget_bol.models import AchievableTargetBol
        from apps.analytics.bol_aggregation import aggregate_bol_rows

        from_year = current_year - 1
        to_year = current_year

        def _build_ach_map(fy):
            rows = []
            for r in AchievableTargetBol.objects.filter(
                fiscal_year=fy, bol_type='ACHIEVABLE'
            ).values('project_code', 'process_type', 'bol', 'plant'):
                sp = normalize_plant(r['plant'])
                if plants and (not sp or sp == '未知' or sp not in plants):
                    continue
                rows.append({**r, 'plant': sp})
            aggregated = aggregate_bol_rows(
                rows, 'bol', ('project_code', 'process_type')
            )
            return {
                (r['project_code'], r['process_type']): {
                    'bol': r['bol'],
                    'plant': '/'.join(r['plants']),
                }
                for r in aggregated
            }

        from_map = _build_ach_map(from_year)
        to_map = _build_ach_map(to_year)

        # 项目名称 + volume
        name_map = {}
        volume_map = {}
        all_codes = set(k[0] for k in from_map.keys()) | set(k[0] for k in to_map.keys())
        if all_codes:
            for r in CbcoRecord.objects.filter(
                program_number__in=list(all_codes), year=to_year
            ).values('program_number', 'volume', 'program_description'):
                volume_map[r['program_number']] = r['volume'] or 0
                if r.get('program_description'):
                    name_map[r['program_number']] = r['program_description']

        common_keys = set(from_map.keys()) & set(to_map.keys())

        items = []
        for key in common_keys:
            from_bol = from_map[key]['bol']
            to_bol = to_map[key]['bol']
            if from_bol is None or to_bol is None or from_bol <= 0:
                continue
            # 按方向筛选：down=下降(改善)，up=上升(恶化)
            if direction == 'down' and to_bol >= from_bol:
                continue
            if direction == 'up' and to_bol <= from_bol:
                continue
            bol_reduction = from_bol - to_bol  # 分钟/台（down 为正降幅，up 为负值即上升量）
            items.append({
                'project_code': key[0],
                'process_type': key[1],
                'project_name': name_map.get(key[0], key[0]),
                'plant': to_map[key]['plant'],
                'volume': volume_map.get(key[0], 0),
                'from_bol': round(from_bol, 2),
                'to_bol': round(to_bol, 2),
                'bol_reduction': round(bol_reduction, 2),
            })

        items.sort(key=lambda x: x['bol_reduction'], reverse=True)
        return items


# ============================================================
# 6.5 Achievable BOL 多年份同比（筛选器联动接口）
# ============================================================
class AchievableYoyView(APIView):
    """GET /api/analytics/achievable-yoy/

    同/环比趋势 Tab 主图（哑铃图）独立数据接口，支持筛选器联动：
      - years:  逗号分隔对比年份（≥2 个，默认本年 vs 上年）
      - plants: 逗号分隔工厂短代码（可选，默认全部）
      - top_n:  Top N 条数（默认 10；0 = 全部）

    数据源与 dashboard.achievable_yoy 一致：BOL 预算模块
    AchievableTargetBol（bol_type='ACHIEVABLE'）。
    """

    def get(self, request, *args, **kwargs):
        years_param = _qstr(request, 'years')
        plants_param = _qstr(request, 'plants')
        top_n = _qint(request, 'top_n')
        if top_n is None or top_n < 0:
            top_n = 10

        years = []
        if years_param:
            for part in years_param.split(','):
                part = part.strip()
                if part.isdigit():
                    years.append(int(part))
        if not years:
            years = [timezone.now().year]

        plants = None
        if plants_param:
            plants = [p.strip().upper() for p in plants_param.split(',') if p.strip()]

        data = _calc_achievable_yoy_multi(years, plants=plants, top_n=top_n)
        return Response(data)


# ============================================================
# 6.6 改善目标对比（Budget工时 vs 改善目标工时 vs Achievable工时）
# ============================================================
def _calculate_improve_target_achievable_bol(row):
    pairs = []
    for i in range(1, 5):
        ct = _f(row.get(f'process_{i:02d}_ct'))
        hc = _f(row.get(f'process_{i:02d}_hc'))
        if ct is not None and hc is not None:
            pairs.append((ct, hc))
    if pairs:
        total = sum(ct * hc for ct, hc in pairs)
        achievable_bol = total * (1 + 1 / 15) / 0.85 / 60
        if achievable_bol != 0:
            return achievable_bol, 'process'
    return _f(row.get('bol_budget')), 'bol_budget'


def _calculate_improve_target_bol(bol_budget, target_pct):
    """Calculate target BOL; a missing improvement percentage means no reduction."""
    budget = _f(bol_budget)
    if budget is None:
        return None
    pct = _f(target_pct)
    return budget * (1 - pct) if pct is not None else budget

def _calculate_improve_target_hours(bol, volume):
    """Calculate hours for positive BOL values when Volume is available."""
    bol_value = _f(bol)
    volume_value = _f(volume)
    if bol_value is None or bol_value <= 0 or volume_value is None:
        return None
    return bol_value * volume_value / 60


def _calc_improve_target_compare(year):
    """改善目标对比：各工厂 Budget / 改善目标 / Achievable 三种年化工时对比

    数据源统一为 HRDB 两张表（以 nr 一对一关联），确保三工时口径完全一致：
      - CN_AME_IE_BOL_improveTarget（主表）：bol_budget 预算 BOL、target_bol 改善目标比例、
        process_01~04_ct/hc 各工段实测 CT/HC
      - CN_AME_IE_BOL_improveTarget_volume（产量表）：项目年产量

    三种工时口径（纵坐标 = 工时数，单位小时）：
      - Budget 工时     = bol_budget × Volume / 60
      - 改善目标工时    = bol_budget × (1 - target_bol) × Volume / 60
                          （target_bol 为 NULL 时按 0% 改善处理，即该项目目标工时等于 Budget 工时）
      - Achievable 工时 = Achievable BOL × Volume / 60，其中 Achievable BOL（实际达到水平）：
             a) 公式结果非空且非 0：
                 (Σ process_XX_ct × process_XX_hc) × (1 + 1/15) / 0.85 / 60（分钟）
             b) 无有效实测结果（无数据或计算结果为 0）：按 bol_budget 回退

    匹配规则：同键 (programCode, process, 标准化plant) 多条记录取 updateDate/nr 最新一条；
    无法关联 Volume 的行工时记 None（前端显示空，无兜底）。

    返回:
        {
          'year': year,
          'summary': [  # 一级视图：按工厂汇总（点击散点下钻用）
            {plant, budget_hours, target_hours, achievable_hours,
             budget_count, target_count, achievable_count}, ...
          ],
          'details': {  # 二级明细：按 项目+工艺
            'budget':     [{plant, project_code, project_name, process_type,
                            bol, volume, hours}, ...],
            'target':     [{plant, project_code, project_name, process_type,
                            bol_budget, target_pct, volume, hours}, ...],
            'achievable': [{plant, project_code, project_name, process_type,
                            bol, source, volume, hours}, ...],  # source: process=实测 / bol_budget=回退
          },
        }
    """
    from apps.actual_ct.models import BolImproveTarget, BolImproveTargetVolume
    from collections import defaultdict

    # ---- Volume: nr → volume（产量表与主表以 nr 一对一关联） ----
    volume_map = {}
    for v in BolImproveTargetVolume.objects.filter(year=year).values('id', 'volume'):
        if v['volume'] is not None:
            volume_map[v['id']] = float(v['volume'])

    # ---- Achievable BOL（实际达到水平）计算 ----
    budget_details = []
    target_details = []
    achievable_details = []
    # 每条主表记录都保留；同项目/工艺可能对应不同产线记录，不做项目级去重。
    target_qs = BolImproveTarget.objects.filter(year=year).order_by(
        '-update_date', '-id'
    ).values(
        'id', 'plant', 'process', 'program_code', 'program_name',
        'bol_budget', 'target_bol',
        'process_01_ct', 'process_01_hc', 'process_02_ct', 'process_02_hc',
        'process_03_ct', 'process_03_hc', 'process_04_ct', 'process_04_hc',
    )
    for r in target_qs:
        std_plant = normalize_plant(r['plant'] or '')
        if not std_plant or std_plant == '未知':
            continue
        code = r['program_code']
        process = (r['process'] or '').strip()

        vol = volume_map.get(r['id'])
        bol_budget = _f(r['bol_budget'])
        pct = _f(r['target_bol'])
        # 目标工时必须覆盖所有预算项目；缺少比例时按 0% 改善保留 Budget 工时
        target_bol_val = _calculate_improve_target_bol(bol_budget, pct)
        achv_bol_val, achv_src = _calculate_improve_target_achievable_bol(r)

        budget_details.append({
            'plant': std_plant,
            'project_code': code,
            'project_name': r['program_name'] or '',
            'process_type': process,
            'bol': round(bol_budget, 2) if bol_budget is not None else None,
            'volume': vol,
            'hours': _calculate_improve_target_hours(bol_budget, vol),
        })
        target_details.append({
            'plant': std_plant,
            'project_code': code,
            'project_name': r['program_name'] or '',
            'process_type': process,
            'bol_budget': round(bol_budget, 2) if bol_budget is not None else None,
            'target_pct': round(pct, 4) if pct is not None else None,
            'volume': vol,
            'hours': _calculate_improve_target_hours(target_bol_val, vol),
        })
        achievable_details.append({
            'plant': std_plant,
            'project_code': code,
            'project_name': r['program_name'] or '',
            'process_type': process,
            'bol': round(achv_bol_val, 2) if achv_bol_val is not None else None,
            'source': achv_src,
            'volume': vol,
            'hours': _calculate_improve_target_hours(achv_bol_val, vol),
        })

    # ---- 一级汇总：按工厂求和 ----
    def _agg(details):
        total = defaultdict(float)
        count = defaultdict(int)
        for d in details:
            if d['hours'] is not None:
                total[d['plant']] += d['hours']
                count[d['plant']] += 1
        return total, count

    budget_sum, budget_cnt = _agg(budget_details)
    target_sum, target_cnt = _agg(target_details)
    ach_sum, ach_cnt = _agg(achievable_details)

    all_plants = sorted(set(budget_sum) | set(target_sum) | set(ach_sum))
    summary = []
    for p in all_plants:
        # count=0 表示该工厂该口径无任何有效数据 → hours 置 None（前端不画点，避免 0 值误导）
        summary.append({
            'plant': p,
            'budget_hours': round(budget_sum[p], 1) if budget_cnt.get(p) else None,
            'target_hours': round(target_sum[p], 1) if target_cnt.get(p) else None,
            'achievable_hours': round(ach_sum[p], 1) if ach_cnt.get(p) else None,
            'budget_count': budget_cnt.get(p, 0),
            'target_count': target_cnt.get(p, 0),
            'achievable_count': ach_cnt.get(p, 0),
        })

    return {
        'year': year,
        'summary': summary,
        'details': {
            'budget': budget_details,
            'target': target_details,
            'achievable': achievable_details,
        },
    }


class ImproveTargetCompareView(APIView):
    """GET /api/analytics/improve-target-compare/

    改善目标对比（综合看板"改善目标对比"Tab）：
    各工厂 Budget 工时 / 改善目标工时 / Achievable 工时 年化汇总 + 项目级明细。

    数据源统一为 HRDB 两张表（nr 关联）：
      - CN_AME_IE_BOL_improveTarget（主表：bol_budget / target_bol / process_XX_ct·hc）
      - CN_AME_IE_BOL_improveTarget_volume（年产量 volume）

    参数:
      - year: 财年（默认当前年份；两表均按该年过滤）
    """

    def get(self, request, *args, **kwargs):
        year = _qint(request, 'year') or timezone.now().year
        data = _calc_improve_target_compare(year)
        return Response(data)


# ============================================================
# 7. Budget BOL 财年对比分析（节省比例 & 节省工时）
# ============================================================
class BudgetBolComparisonView(APIView):
    """财年 BOL 对比分析（支持 Budget / Achievable / Target 三种类型）

    对比两个财年的 BOL 数据，计算：
      - BOL 降低比例 = (from_bol - to_bol) / from_bol × 100%
      - 节省工时 = to_volume × (from_bol - to_bol) / 60 小时

    入参：
      from_year, to_year, bol_type（BUDGET / ACHIEVABLE / TARGET，默认 BUDGET）

    数据来源：
      - BUDGET 类型：BudgetBol 表的 budget_bol 字段
      - ACHIEVABLE/TARGET 类型：AchievableTargetBol 表的 bol 字段
      - CbcoRecord 表：获取各项目在对应财年的 Volume
    """

    def get(self, request):
        from_year = request.query_params.get('from_year', '2025')
        to_year = request.query_params.get('to_year', '2026')
        bol_type = (request.query_params.get('bol_type') or 'BUDGET').upper()
        if bol_type not in ('BUDGET', 'ACHIEVABLE', 'TARGET'):
            bol_type = 'BUDGET'

        try:
            from_year = int(from_year)
            to_year = int(to_year)
        except (ValueError, TypeError):
            return Response({'error': 'from_year 和 to_year 必须为整数'},
                            status=status.HTTP_400_BAD_REQUEST)

        if from_year >= to_year:
            return Response({'error': 'from_year 必须小于 to_year'},
                            status=status.HTTP_400_BAD_REQUEST)

        from apps.budget_bol.cbco_models import CbcoRecord
        from apps.budget_bol.models import AchievableTargetBol
        from apps.analytics.bol_aggregation import aggregate_bol_rows

        # 根据 bol_type 选择查询的表和字段
        if bol_type == 'BUDGET':
            from_records = BudgetBol.objects.filter(
                fiscal_year=from_year, bol_type='BUDGET'
            ).values('project_code', 'process_type', 'plant', 'budget_bol')
            to_records = BudgetBol.objects.filter(
                fiscal_year=to_year, bol_type='BUDGET'
            ).values('project_code', 'process_type', 'plant', 'budget_bol')
            bol_field = 'budget_bol'
        else:
            from_records = AchievableTargetBol.objects.filter(
                fiscal_year=from_year, bol_type=bol_type
            ).values('project_code', 'process_type', 'plant', 'bol')
            to_records = AchievableTargetBol.objects.filter(
                fiscal_year=to_year, bol_type=bol_type
            ).values('project_code', 'process_type', 'plant', 'bol')
            bol_field = 'bol'

        # 先将各产线记录汇总到 (project_code, process_type) 粒度
        from_map = {
            (r['project_code'], r['process_type']): {
                'bol': r['bol'], 'plant': '/'.join(r['plants'])
            }
            for r in aggregate_bol_rows(
                from_records, bol_field, ('project_code', 'process_type')
            )
        }
        to_map = {
            (r['project_code'], r['process_type']): {
                'bol': r['bol'], 'plant': '/'.join(r['plants'])
            }
            for r in aggregate_bol_rows(
                to_records, bol_field, ('project_code', 'process_type')
            )
        }

        # 查询 CBCO_records 获取 Volume
        all_codes = set()
        for r in from_records:
            all_codes.add(r['project_code'])
        for r in to_records:
            all_codes.add(r['project_code'])

        volume_map = {}  # {(project_code, year): volume}
        desc_map = {}  # project_code → program_description
        if all_codes:
            for r in CbcoRecord.objects.filter(
                program_number__in=list(all_codes),
                year__in=[from_year, to_year]
            ).values('program_number', 'year', 'volume', 'program_description'):
                volume_map[(r['program_number'], r['year'])] = r['volume'] or 0
                if r['program_number'] not in desc_map and r.get('program_description'):
                    desc_map[r['program_number']] = r['program_description']

        # 计算对比：找出两个财年共有的 (project_code, process_type) 组合
        common_keys = set(from_map.keys()) & set(to_map.keys())
        items = []
        total_hours_saved = 0.0
        total_bol_increase_count = 0
        plant_hours = {}  # plant → net_hours_saved
        process_hours = {}  # process_type → net_hours_saved

        for key in sorted(common_keys):
            project_code, process_type = key
            from_bol = from_map[key]['bol']
            to_bol = to_map[key]['bol']
            plant = from_map[key]['plant'] or to_map[key]['plant']

            # 过滤：任一年度 BOL 为空/为0 的不参与计算
            # （新项目前一年无数据、已结束项目后一年无数据，均排除）
            if from_bol is None or to_bol is None or from_bol <= 0 or to_bol <= 0:
                continue

            from_vol = volume_map.get((project_code, from_year), 0)
            to_vol = volume_map.get((project_code, to_year), 0)

            bol_reduction = from_bol - to_bol
            bol_reduction_pct = round(bol_reduction / from_bol * 100, 2)
            hours_saved = round(to_vol * bol_reduction / 60, 2) if to_vol > 0 else 0

            item = {
                'project_code': project_code,
                'process_type': process_type,
                'plant': plant,
                'program_description': desc_map.get(project_code, ''),
                'from_bol': round(from_bol, 2),
                'to_bol': round(to_bol, 2),
                'from_volume': from_vol,
                'to_volume': to_vol,
                'bol_reduction': round(bol_reduction, 2),
                'bol_reduction_pct': bol_reduction_pct,
                'hours_saved': hours_saved,
            }
            items.append(item)

            # 净节省工时（含正负：BOL降低为正，BOL上升为负）
            total_hours_saved += hours_saved
            if bol_reduction_pct < 0:
                total_bol_increase_count += 1

            # 按 plant 汇总净工时（已标准化）
            plant_hours[plant] = plant_hours.get(plant, 0) + hours_saved

            # 按 process_type 汇总净工时
            process_hours[process_type] = process_hours.get(process_type, 0) + hours_saved

        # 按 plant 汇总
        by_plant = sorted(
            [{'plant': k, 'hours_saved': round(v, 2), 'project_count': sum(
                1 for x in items if x.get('plant', '') == k and x['hours_saved'] > 0
            )} for k, v in plant_hours.items()],
            key=lambda x: x['hours_saved'], reverse=True
        )

        # 按 process_type 汇总
        by_process = sorted(
            [{'process_type': k, 'hours_saved': round(v, 2), 'project_count': sum(
                1 for x in items if x['process_type'] == k and x['hours_saved'] > 0
            )} for k, v in process_hours.items()],
            key=lambda x: x['hours_saved'], reverse=True
        )

        return Response({
            'from_year': from_year,
            'to_year': to_year,
            'bol_type': bol_type,
            'summary': {
                'total_compared': len(common_keys),
                'total_items': len(items),
                'total_hours_saved': round(total_hours_saved, 2),
            },
            'items': items,
            'by_plant': by_plant,
            'by_process': by_process,
        })


# ============================================================
# 8. BOL 全链路对比 — 全量数据（用于图表点击弹窗）
# ============================================================
class BolLifecycleAllView(APIView):
    """GET /api/analytics/bol-lifecycle-all/

    返回本财年所有项目的 BOL 全链路数据（不限制 Top 25），
    用于综合看板 BOL 全链路对比图点击弹窗展示。
    """

    def get(self, request, *args, **kwargs):
        current_year = _qint(request, 'fiscal_year')
        if not current_year:
            current_year = BudgetBol.objects.order_by('-fiscal_year').values_list(
                'fiscal_year', flat=True
            ).first() or timezone.now().year

        from apps.budget_bol.models import AchievableTargetBol
        from apps.budget_bol.cbco_models import CbcoRecord
        from apps.analytics.bol_aggregation import aggregate_bol_rows

        budget_map = {
            (r['project_code'], r['process_type']): r['bol']
            for r in aggregate_bol_rows(BudgetBol.objects.filter(
            fiscal_year=current_year, bol_type='BUDGET'
            ).values('project_code', 'process_type', 'budget_bol'),
                'budget_bol', ('project_code', 'process_type'))
        }

        achievable_map = {
            (r['project_code'], r['process_type']): r['bol']
            for r in aggregate_bol_rows(AchievableTargetBol.objects.filter(
            fiscal_year=current_year, bol_type='ACHIEVABLE'
            ).values('project_code', 'process_type', 'bol'),
                'bol', ('project_code', 'process_type'))
        }

        target_map = {
            (r['project_code'], r['process_type']): r['bol']
            for r in aggregate_bol_rows(AchievableTargetBol.objects.filter(
            fiscal_year=current_year, bol_type='TARGET'
            ).values('project_code', 'process_type', 'bol'),
                'bol', ('project_code', 'process_type'))
        }

        bp_qs = BolOverViewByProcess.objects.filter(
            hc__isnull=False, oee__isnull=False
        ).order_by('-update_time')
        bp_map = {}
        for r in bp_qs.values('program_code', 'process', 'line_nr', 'hc', 'oee'):
            key = (r['program_code'], r['process'])
            if key not in bp_map:
                bp_map[key] = {
                    'hc': _f(r['hc']),
                    'oee': _f(r['oee']),
                    'line_nr': r['line_nr'],
                }

        bn_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull=False).order_by('-update_time')
        bn_map = {}
        for r in bn_qs.values('project_code', 'line_nr', 'cycle_time_bottleneck'):
            key = (r['project_code'], r['line_nr'])
            if key not in bn_map:
                bn_map[key] = _f(r['cycle_time_bottleneck'])

        volume_map = {}
        try:
            for r in CbcoRecord.objects.filter(fiscal_year=current_year).values(
                'project_code', 'annual_volume'
            ):
                pc = r['project_code']
                if pc not in volume_map:
                    volume_map[pc] = int(r['annual_volume'] or 0)
        except Exception:
            pass

        all_keys = set(budget_map) | set(achievable_map)
        items = []
        for key in all_keys:
            project_code, process_type = key
            budget = budget_map.get(key)
            achievable = achievable_map.get(key)
            target = target_map.get(key)
            bp = bp_map.get((project_code, process_type), {})
            hc = bp.get('hc')
            oee = bp.get('oee')
            line_nr = bp.get('line_nr', '')

            # 精确匹配 project_code + line_nr，不做兜底
            ct_actual = bn_map.get((project_code, line_nr)) if line_nr else None
            actual = None
            if ct_actual is not None and hc is not None and oee is not None:
                actual = calc_bol(ct_actual, hc, oee)

            gap = None
            if budget is not None and achievable is not None:
                gap = round(budget - achievable, 2)

            actual_ach_gap_pct = None
            if actual is not None and achievable and achievable > 0:
                actual_ach_gap_pct = round((actual - achievable) / achievable * 100, 1)

            items.append({
                'project_code': project_code,
                'process_type': process_type,
                'budget': budget,
                'achievable': achievable,
                'target': target,
                'actual': actual,
                'actual_ct': ct_actual,
                'hc': hc,
                'oee': oee,
                'line_nr': line_nr,
                'gap': gap,
                'volume': volume_map.get(project_code, 0),
                'actual_ach_gap_pct': actual_ach_gap_pct,
            })

        items.sort(key=lambda x: (
            0 if x['process_type'] == 'FA' else 1,
            -x['volume'],
        ))
        return Response({
            'fiscal_year': current_year,
            'total': len(items),
            'items': items,
        })


# ============================================================
# 10. 综合多维度 BOL 分析（工艺 × RoofType × 工厂 × 财年）
# ============================================================
class MultiDimBolAnalysisView(APIView):
    """GET /api/analytics/multi-dim-analysis/

    综合多维度 BOL 分析，参考 BOL_Analysis_Report_Standalone.html 报告维度。
    数据源：BudgetBol / AchievableTargetBol 表 + CbcoRecord（获取 roof_type）。

    分析维度：
      1. 工艺类型 × RoofType BOL 总览（均值/中位数/Min-Max/标准差）
      2. 跨工厂对比（同工艺+同RoofType下各工厂对比）
      3. 时间维度（按财年对比，支持多年数据分析）

    入参：
      - bol_type: BUDGET / ACHIEVABLE / TARGET（默认 ACHIEVABLE）
      - fiscal_year: 财年（可选，不传则查全部财年）
      - process_type: 工艺类型筛选（可选）
    """

    def get(self, request):
        from apps.analytics.bol_aggregation import aggregate_bol_rows

        bol_type = (request.query_params.get('bol_type') or 'ACHIEVABLE').upper()
        if bol_type not in ('BUDGET', 'ACHIEVABLE', 'TARGET'):
            bol_type = 'ACHIEVABLE'

        fiscal_year = _qint(request, 'fiscal_year')
        process_type = _qstr(request, 'process_type')

        # 查询 BOL 数据
        if bol_type == 'BUDGET':
            qs = BudgetBol.objects.filter(bol_type='BUDGET')
            if fiscal_year is not None:
                qs = qs.filter(fiscal_year=fiscal_year)
            if process_type:
                qs = qs.filter(process_type=process_type)
            records = list(qs.values(
                'fiscal_year', 'process_type', 'project_code',
                'plant', 'budget_bol',
            ))
            bol_field = 'budget_bol'
        else:
            from apps.budget_bol.models import AchievableTargetBol
            qs = AchievableTargetBol.objects.filter(bol_type=bol_type)
            if fiscal_year is not None:
                qs = qs.filter(fiscal_year=fiscal_year)
            if process_type:
                qs = qs.filter(process_type=process_type)
            records = list(qs.values(
                'fiscal_year', 'process_type', 'project_code',
                'plant', 'bol',
            ))
            bol_field = 'bol'

        if not records:
            return Response({
                'summary': {
                    'total_projects': 0, 'plant_count': 0,
                    'process_type_count': 0, 'roof_type_count': 0,
                    'fiscal_years': [],
                },
                'by_process_roof': [],
                'cross_plant': [],
                'by_year_combo': [],
                'by_year_plant_combo': [],
                'bol_type': bol_type,
                'fiscal_year': fiscal_year,
            })

        # 批量查询 CbcoRecord 获取 roof_type（按 project_code 取最近年份记录）
        all_codes = list({r['project_code'] for r in records if r['project_code']})
        roof_map = {}  # project_code → roof_type
        if all_codes:
            for r in CbcoRecord.objects.filter(
                program_number__in=all_codes
            ).order_by('-year').values('program_number', 'typ_of_roof'):
                if r['program_number'] not in roof_map and r.get('typ_of_roof'):
                    roof_map[r['program_number']] = r['typ_of_roof'].strip()

        # 构建记录列表（含 roof_type 和标准化 plant）
        enriched = []
        for r in records:
            bol_val = _f(r.get(bol_field))
            if bol_val is None or bol_val <= 0:
                continue
            roof = roof_map.get(r['project_code'], '')
            plant = normalize_plant(r.get('plant') or '')
            enriched.append({
                'fiscal_year': r['fiscal_year'],
                'process_type': (r.get('process_type') or '').strip(),
                'project_code': r['project_code'],
                'plant': plant,
                'roof_type': roof,
                'bol': bol_val,
            })

        if not enriched:
            return Response({
                'summary': {
                    'total_projects': 0, 'plant_count': 0,
                    'process_type_count': 0, 'roof_type_count': 0,
                    'fiscal_years': [],
                },
                'by_process_roof': [],
                'cross_plant': [],
                'by_year_combo': [],
                'by_year_plant_combo': [],
                'bol_type': bol_type,
                'fiscal_year': fiscal_year,
            })

        project_records = aggregate_bol_rows(
            enriched, 'bol',
            ('fiscal_year', 'project_code', 'process_type', 'roof_type'),
        )
        plant_project_records = aggregate_bol_rows(
            enriched, 'bol',
            ('fiscal_year', 'project_code', 'process_type', 'roof_type', 'plant'),
        )

        # ===== 1. 汇总信息 =====
        plants_set = {e['plant'] for e in enriched if e['plant']}
        process_set = {e['process_type'] for e in enriched if e['process_type']}
        roof_set = {e['roof_type'] for e in enriched if e['roof_type']}
        years_set = {e['fiscal_year'] for e in enriched}
        # 按 project_code 去重统计项目数
        projects_set = {e['project_code'] for e in enriched}

        summary = {
            'total_projects': len(projects_set),
            'plant_count': len(plants_set),
            'process_type_count': len(process_set),
            'roof_type_count': len(roof_set),
            'fiscal_years': sorted(years_set),
        }

        # ===== 2. 工艺 × RoofType BOL 总览 =====
        by_process_roof = self._calc_stats(
            project_records,
            group_keys=('process_type', 'roof_type'),
        )

        # ===== 3. 跨工厂对比（工艺 × RoofType × 工厂）=====
        cross_plant_all = self._calc_stats(
            plant_project_records,
            group_keys=('process_type', 'roof_type', 'plant'),
        )
        # 仅保留同工艺+同RoofType下 ≥2 个工厂的组合（才有跨工厂对比意义）
        combo_plant_count = {}
        for item in cross_plant_all:
            key = (item['process_type'], item['roof_type'])
            combo_plant_count[key] = combo_plant_count.get(key, 0) + 1
        cross_plant = [
            item for item in cross_plant_all
            if combo_plant_count.get(
                (item['process_type'], item['roof_type']), 0
            ) >= 2
        ]

        # ===== 4. 时间维度（财年 × 工艺 × RoofType 组合）=====
        # by_year_combo：全局各"工艺+RoofType"组合的年度趋势（如 TLBS+FA、TLBS+IHE）
        by_year_combo = self._calc_stats(
            project_records,
            group_keys=('fiscal_year', 'process_type', 'roof_type'),
        )
        by_year_combo.sort(key=lambda x: (x['fiscal_year'], x['process_type'], x['roof_type']))

        # by_year_plant_combo：各工厂内"工艺+RoofType"组合的年度趋势（用于选定工厂查看）
        by_year_plant_combo = self._calc_stats(
            plant_project_records,
            group_keys=('fiscal_year', 'plant', 'process_type', 'roof_type'),
        )
        by_year_plant_combo.sort(
            key=lambda x: (x['fiscal_year'], x['plant'], x['process_type'], x['roof_type'])
        )

        return Response({
            'summary': summary,
            'by_process_roof': by_process_roof,
            'cross_plant': cross_plant,
            'by_year_combo': by_year_combo,
            'by_year_plant_combo': by_year_plant_combo,
            'bol_type': bol_type,
            'fiscal_year': fiscal_year,
        })

    @staticmethod
    def _calc_stats(records, group_keys):
        """按 group_keys 分组计算统计量（count/mean/median/min/max/std）"""
        groups = {}
        for r in records:
            key = tuple(r.get(k, '') for k in group_keys)
            groups.setdefault(key, []).append(r['bol'])

        result = []
        for key, bols in groups.items():
            if not bols:
                continue
            n = len(bols)
            mean_val = round(sum(bols) / n, 2)
            median_val = round(_stats.median(bols), 2)
            min_val = round(min(bols), 2)
            max_val = round(max(bols), 2)
            std_val = round(_stats.pstdev(bols), 2) if n > 1 else 0.0
            item = {k: v for k, v in zip(group_keys, key)}
            item.update({
                'count': n,
                'mean': mean_val,
                'median': median_val,
                'min': min_val,
                'max': max_val,
                'std': std_val,
            })
            result.append(item)

        # 排序：按 group_keys 字段值排序
        result.sort(key=lambda x: tuple(str(x.get(k, '')) for k in group_keys))
        return result


class MultiDimBolTrendView(APIView):
    """时间维度多 BOL 类型对比分析

    同时获取 Budget / Achievable / Target 三种 BOL 类型的年度数据，
    计算差距（Budget-Achievable）和年度变化率，支持工艺+RoofType 组合维度。

    数据源：
        - BudgetBol（budget_bol 字段）
        - AchievableTargetBol（bol 字段，bol_type=ACHIEVABLE/TARGET）
        - CbcoRecord（roof_type 来源）

    返回结构：
        - by_year_combo: 各工艺+RoofType 组合的年度 BOL 均值（三种类型对比）
        - by_year_gap: 各组合的 Budget-Achievable 差距年度变化
        - by_year_plant_combo: 各工厂内组合的年度趋势
        - fiscal_years: 财年列表
    """

    def get(self, request):
        from apps.budget_bol.models import BudgetBol, AchievableTargetBol
        from apps.budget_bol.cbco_models import CbcoRecord
        from apps.analytics.bol_aggregation import aggregate_bol_rows

        process_type = _qstr(request, 'process_type')

        # 1. 查询 Budget BOL
        budget_qs = BudgetBol.objects.filter(bol_type='BUDGET')
        if process_type:
            budget_qs = budget_qs.filter(process_type=process_type)
        budget_records = list(budget_qs.values(
            'fiscal_year', 'process_type', 'project_code', 'plant', 'budget_bol'
        ))

        # 2. 查询 Achievable BOL
        ach_qs = AchievableTargetBol.objects.filter(bol_type='ACHIEVABLE')
        if process_type:
            ach_qs = ach_qs.filter(process_type=process_type)
        ach_records = list(ach_qs.values(
            'fiscal_year', 'process_type', 'project_code', 'plant', 'bol'
        ))

        # 3. 查询 Target BOL
        tgt_qs = AchievableTargetBol.objects.filter(bol_type='TARGET')
        if process_type:
            tgt_qs = tgt_qs.filter(process_type=process_type)
        tgt_records = list(tgt_qs.values(
            'fiscal_year', 'process_type', 'project_code', 'plant', 'bol'
        ))

        # 4. 批量查询 CbcoRecord 获取 roof_type
        all_codes = set()
        for r in budget_records + ach_records + tgt_records:
            if r['project_code']:
                all_codes.add(r['project_code'])
        roof_map = {}
        if all_codes:
            for r in CbcoRecord.objects.filter(
                program_number__in=list(all_codes)
            ).order_by('-year').values('program_number', 'typ_of_roof'):
                if r['program_number'] not in roof_map and r.get('typ_of_roof'):
                    roof_map[r['program_number']] = r['typ_of_roof'].strip()

        # 5. 标准化 plant 并补充 roof_type
        def enrich(records, bol_field):
            for r in records:
                r['plant'] = normalize_plant(r.get('plant', ''))
                r['roof_type'] = roof_map.get(r['project_code'], '')
                r['bol'] = float(r.get(bol_field) or 0) if r.get(bol_field) is not None else None
            return [r for r in records if r['bol'] is not None and r['roof_type']]

        budget_records = enrich(budget_records, 'budget_bol')
        ach_records = enrich(ach_records, 'bol')
        tgt_records = enrich(tgt_records, 'bol')

        project_group_fields = ('fiscal_year', 'project_code', 'process_type', 'roof_type')
        budget_project_records = aggregate_bol_rows(
            budget_records, 'bol', project_group_fields
        )
        achievable_project_records = aggregate_bol_rows(
            ach_records, 'bol', project_group_fields
        )
        target_project_records = aggregate_bol_rows(
            tgt_records, 'bol', project_group_fields
        )

        # 6. 按财年 × 工艺 × RoofType 组合计算均值
        def calc_combo_stats(records, bol_type_label):
            groups = {}
            for r in records:
                key = (r['fiscal_year'], r['process_type'], r['roof_type'])
                groups.setdefault(key, []).append(r['bol'])
            result = []
            for (fy, proc, roof), bols in groups.items():
                if not bols:
                    continue
                n = len(bols)
                result.append({
                    'fiscal_year': fy,
                    'process_type': proc,
                    'roof_type': roof,
                    'combo': f'{roof}+{proc}',
                    'bol_type': bol_type_label,
                    'count': n,
                    'mean': round(sum(bols) / n, 2),
                    'median': round(_stats.median(bols), 2),
                })
            return result

        budget_stats = calc_combo_stats(budget_project_records, 'Budget')
        ach_stats = calc_combo_stats(achievable_project_records, 'Achievable')
        tgt_stats = calc_combo_stats(target_project_records, 'Target')

        # 7. 合并三种类型到同一结构（按 combo + fiscal_year 对齐）
        all_combos = sorted(set(
            f"{r['roof_type']}+{r['process_type']}"
            for r in budget_project_records + achievable_project_records + target_project_records
        ))
        all_years = sorted(set(
            r['fiscal_year']
            for r in budget_project_records + achievable_project_records + target_project_records
        ))

        # by_year_combo：每个组合每年的 Budget/Achievable/Target 均值
        by_year_combo = []
        for combo in all_combos:
            roof, proc = combo.split('+')
            for fy in all_years:
                b = next((x for x in budget_stats if x['combo'] == combo and x['fiscal_year'] == fy), None)
                a = next((x for x in ach_stats if x['combo'] == combo and x['fiscal_year'] == fy), None)
                t = next((x for x in tgt_stats if x['combo'] == combo and x['fiscal_year'] == fy), None)
                # 至少有一种类型有数据才输出
                if not (b or a or t):
                    continue
                item = {
                    'fiscal_year': fy,
                    'combo': combo,
                    'process_type': proc,
                    'roof_type': roof,
                    'budget_mean': b['mean'] if b else None,
                    'budget_count': b['count'] if b else 0,
                    'achievable_mean': a['mean'] if a else None,
                    'achievable_count': a['count'] if a else 0,
                    'target_mean': t['mean'] if t else None,
                    'target_count': t['count'] if t else 0,
                }
                # Budget-Achievable 差距（正值=BOL 预算高于可达，改善空间）
                if b and a and b['mean'] and a['mean']:
                    item['gap_budget_ach'] = round(b['mean'] - a['mean'], 2)
                    item['gap_pct'] = round((b['mean'] - a['mean']) / b['mean'] * 100, 1) if b['mean'] else None
                else:
                    item['gap_budget_ach'] = None
                    item['gap_pct'] = None
                by_year_combo.append(item)

        # 8. 按工厂 × 组合的年度趋势（Achievable）
        by_year_plant_combo = []
        plant_combo_groups = {}
        achievable_plant_project_records = aggregate_bol_rows(
            ach_records, 'bol',
            ('fiscal_year', 'project_code', 'process_type', 'roof_type', 'plant'),
        )
        for r in achievable_plant_project_records:
            key = (r['fiscal_year'], r['plant'], r['process_type'], r['roof_type'])
            plant_combo_groups.setdefault(key, []).append(r['bol'])
        for (fy, plant, proc, roof), bols in plant_combo_groups.items():
            if not bols:
                continue
            n = len(bols)
            by_year_plant_combo.append({
                'fiscal_year': fy,
                'plant': plant,
                'process_type': proc,
                'roof_type': roof,
                'combo': f'{roof}+{proc}',
                'count': n,
                'mean': round(sum(bols) / n, 2),
                'median': round(_stats.median(bols), 2),
            })
        by_year_plant_combo.sort(key=lambda x: (x['fiscal_year'], x['plant'], x['combo']))

        return Response({
            'by_year_combo': by_year_combo,
            'by_year_plant_combo': by_year_plant_combo,
            'fiscal_years': all_years,
            'combos': all_combos,
        })

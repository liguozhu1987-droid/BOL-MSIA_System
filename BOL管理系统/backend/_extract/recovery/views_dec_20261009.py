# Source Generated with Decompyle++
# File: C:\pycdc_work\views.pyc (Python 3.12)

'''分析模块 视图：6大分析场景API

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
'''
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
from bol_platform.bol_calc import calc_bol, calc_bol_gap, calc_labor_cost_gap
from bol_platform.plant_utils import normalize_plant, get_plant_raw_values, normalize_project_code
DEFAULT_LABOR_RATE = 0.8

def _f(v):
    '''安全转换 Decimal/None → float/None'''
    if v is None:
        return None
    
    try:
        return float(v)
    except (TypeError, ValueError):
        return None



def _qstr(request, name):
    '''取查询参数，去空白；空字符串视为未提供'''
    v = request.query_params.get(name)
    if v is None:
        return None
    v = v.strip()
    if not v:
        v


def _qint(request, name, default = (None,)):
    '''取查询参数并转 int；失败或未提供返回 default'''
    v = _qstr(request, name)
    if v is None:
        return default
    
    try:
        return int(v)
    except ValueError:
        return 



def _qfloat(request, name, default = (None,)):
    '''取查询参数并转 float；失败或未提供返回 default'''
    v = _qstr(request, name)
    if v is None:
        return default
    
    try:
        return float(v)
    except ValueError:
        return 



def _line_key(program_code, process, line_nr):
    """统一构造 (program_code, process, line_nr) 合并键，None 归一为 ''"""
    if not program_code:
        program_code
    if not process:
        process
    if not line_nr:
        line_nr
    return ('', '', ''.strip())


def _pp_key(program_code, process):
    """统一构造 (program_code, process) 合并键，None 归一为 ''"""
    if not program_code:
        program_code
    if not process:
        process
    return ('', '')


class BolComparisonView(APIView):
    '''GET /api/analytics/comparison/

    查询参数：program_code(可选), location(可选), fiscal_year(可选)
    返回：指定项目的 QWS / 预算 / BOL更新记录 / 实测CT换算 多种BOL并排对比，按工艺分组
    '''
    
    def get(self, request, *args, **kwargs):
        program_code = _qstr(request, 'program_code')
        location = _qstr(request, 'location')
        fiscal_year = _qint(request, 'fiscal_year')
        dyn_qs = BolOverView.objects.filter(final_approve_status = 'Approved')
        if program_code:
            dyn_qs = dyn_qs.filter(program_code = program_code)
        if location:
            dyn_qs = dyn_qs.filter(location__in = get_plant_raw_values(location))
        dyn_qs = dyn_qs.order_by('-submit_date')
        dyn_map = { }
        for r in dyn_qs.values('program_code', 'process', 'line_nr', 'bol', 'qws_bol', 'ct', 'hc', 'oee'):
            key = _line_key(r['program_code'], r['process'], r['line_nr'])
            if not key not in dyn_map:
                continue
            dyn_map[key] = {
                'qws_bol': _f(r['qws_bol']),
                'latest_bol': _f(r['bol']),
                'hc': _f(r['hc']),
                'oee': _f(r['oee']) }
        budget_qs = BudgetBol.objects.all()
        if program_code:
            budget_qs = budget_qs.filter(project_code = program_code)
        if location:
            raw_vals = get_plant_raw_values(location)
            _Q = Q
            import django.db.models
            plant_q = _Q()
            for v in raw_vals:
                plant_q |= _Q(plant = v) | _Q(plant__startswith = f'''{v}_''')
            budget_qs = budget_qs.filter(plant_q)
        budget_map = { }
        for r in budget_qs.values('project_code', 'process_type', 'asset', 'budget_bol'):
            key = _line_key(r['project_code'], r['process_type'], r['asset'])
            if not key not in budget_map:
                continue
            budget_map[key] = _f(r['budget_bol'])
        bn_qs = BottleNeckCt.objects.all()
        if program_code:
            bn_qs = bn_qs.filter(project_code = program_code)
        bn_qs = bn_qs.order_by('-update_time')
        bn_map = { }
        for r in bn_qs.values('project_code', 'line_nr', 'cycle_time_bottleneck', 'update_time'):
            if not r['project_code']:
                r['project_code']
            if not r['line_nr']:
                r['line_nr']
            bn_key = ('', ''.strip())
            if not bn_key not in bn_map:
                continue
            bn_map[bn_key] = {
                'bottleneck_ct': _f(r['cycle_time_bottleneck']),
                'update_time': r['update_time'] }
        all_keys = set(dyn_map) | set(budget_map)
        items = []
        for key in all_keys:
            (program_code_, process, line_nr) = key
            dyn = dyn_map.get(key, { })
            qws_bol = dyn.get('qws_bol')
            latest_bol = dyn.get('latest_bol')
            hc = dyn.get('hc')
            oee = dyn.get('oee')
            budget_bol = budget_map.get(key)
            bn_info = bn_map.get((program_code_, line_nr), { })
            bottleneck_ct = bn_info.get('bottleneck_ct')
            estimated_bol_from_ct = None
            if bottleneck_ct is not None and hc is not None and oee is not None:
                estimated_bol_from_ct = calc_bol(bottleneck_ct, hc, oee)
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
                'gap_budget_vs_latest': gap_budget_vs_latest })
        items.sort(key = (lambda x: (x['process'], x['line_nr'])))
        return Response({
            'program_code': program_code,
            'items': items })



def _calc_achievable_yoy_multi(years, plants, top_n = (None, 10)):
    """Achievable BOL 多年份同比分析（同/环比趋势 Tab 主图）

    数据源：BOL 预算模块上传的 AchievableTargetBol（bol_type='ACHIEVABLE'）
    分组键：(project_code, process_type, 标准化工厂) 精确匹配，无兜底

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
    AchievableTargetBol = AchievableTargetBol
    import apps.budget_bol.models
    Counter = Counter
    import collections
    years = set((lambda .0: for y in .0:
if not y:
continueint(y).0)(years()))
    if len(years) < 2:
        base = years[0] if years else timezone.now().year
        years = sorted(set(years) | {
            base - 1})
    years_set = set(years)
    opt_years = list(AchievableTargetBol.objects.filter(bol_type = 'ACHIEVABLE').values_list('fiscal_year', flat = True).distinct().order_by('fiscal_year'))
    for None in :
        if p and p != '未知':
            pass
    continue
    , {}, (p,) = AchievableTargetBol.objects.filter(bol_type = 'ACHIEVABLE').values_list('plant', flat = True).distinct()(), p
    groups = { }
    qs = AchievableTargetBol.objects.filter(fiscal_year__in = years, bol_type = 'ACHIEVABLE').order_by('fiscal_year', 'id').values('fiscal_year', 'project_code', 'process_type', 'plant', 'bol')
    for r in qs:
        if not r['plant']:
            r['plant']
        std_plant = normalize_plant('')
        if std_plant or std_plant == '未知':
            continue
        if plants and std_plant not in plants:
            continue
        v = _f(r['bol'])
        if v is None:
            continue
        if not r['process_type']:
            r['process_type']
        key = (r['project_code'], ''.strip(), std_plant)
        g = groups.setdefault(key, { })
        g.setdefault(r['fiscal_year'], v)
    all_codes = (lambda .0: for k in .0:
k[0].0)(groups.keys()())
    vol_name = { }
    if all_codes:
        for r in CbcoRecord.objects.filter(program_number__in = list(all_codes), year__in = years).order_by('-year').values('program_number', 'year', 'volume', 'program_description'):
            m = vol_name.setdefault(r['program_number'], { })
            if not r['volume']:
                r['volume']
            if not r.get('program_description'):
                r.get('program_description')
            m.setdefault(r['year'], {
                'volume': 0,
                'name': '' })
    
    def _meta(code = None, prefer_year = None):
        if not vol_name.get(code):
            vol_name.get(code)
        m = { }
        if prefer_year in m:
            pass
        elif m:
            pass
        
        y = None
        if y is None:
            return ('', 0)
        return (m[y]['name'], m[y]['volume'])

    items = []
    for code, process, plant in groups.items():
        yearvals = None
        ys = (lambda .0 = None: for y in .0:
if not y in years_set:
continuey.0)(yearvals())
        if len(ys) < 2:
            continue
        to_bol = yearvals[ys[-1]]
        from_bol = yearvals[ys[0]]
        diff = to_bol - from_bol
        diff_pct = round((diff / from_bol) * 100, 1) if from_bol > 0 else None
        (name, volume) = _meta(code, ys[-1])
        if not name:
            name
        for None in :
            pass
        process({
            'project_code': plant,
            'process_type': code,
            'plant': volume,
            'project_name': ys, y,
            'volume': , { }, ,
            'values': y,,
            'from_year': ys[0],
            'to_year': ys[-1],
            'from_bol': round(from_bol, 2),
            'to_bol': round(to_bol, 2),
            'diff': round(diff, 2),
            'diff_pct': diff_pct })
    items.sort(key = (lambda x: abs(x['diff'])), reverse = True)
    if top_n and top_n > 0:
        items[:top_n] = None
    pp_count = (lambda .0: for it in .0:
(it['project_code'], it['process_type']).0)(items())
    for it in items:
        if not it['process_type']:
            it['process_type']
        base_label = f'''{it['project_code']}/{'N/A'}'''
        it['label'] = f'''{base_label}({it['plant']})''' if pp_count[(it['project_code'], it['process_type'])] > 1 else base_label
    return {
        'options': {
            'years': opt_years,
            'plants': opt_plants },
        'selected_years': years,
        'items': items }
    
    


class DashboardView(APIView):
    '''GET /api/analytics/dashboard/

    综合看板：跨模块（BOL更新记录 + 预算BOL + 实测CT）综合分析。
    基于IE行业BOL生命周期管理最佳实践，提供：
      1. 跨模块核心KPI汇总
      2. BOL全链路对比（Budget → Achievable → Target → 实测BOL）
      3. SCT vs ACT差距分析
      4. 审批状态健康度
      5. 月度趋势（BOL审批 + CT采集）
      6. 工厂维度综合对比
      7. 改善机会预警列表
    '''
    
    def get(self, request, *args, **kwargs):
        AchievableTargetBol = AchievableTargetBol
        import apps.budget_bol.models
        current_year = timezone.now().year
        if not BudgetBol.objects.filter(fiscal_year = current_year).exists():
            if not BudgetBol.objects.order_by('-fiscal_year').values_list('fiscal_year', flat = True).first():
                BudgetBol.objects.order_by('-fiscal_year').values_list('fiscal_year', flat = True).first()
            current_year = current_year
        plants_param = _qstr(request, 'plants')
        process_types_param = _qstr(request, 'process_types')
        roof_types_param = _qstr(request, 'roof_types')
        lifecycle_plants_param = _qstr(request, 'lifecycle_plants')
        p, if plants_param else None = , [], 
        p, if process_types_param else None = , [], 
        p, if roof_types_param else None = , [], 
        p, if lifecycle_plants_param else None = , [], 
        if not _qint(request, 'year'):
            _qint(request, 'year')
        compare_year = current_year
        
        def _kpi_counts():
            qs = BolOverView.objects.filter(submit_date__year = current_year)
            total = qs.count()
            approved = qs.filter(final_approve_status = 'Approved').count()
            pending = qs.filter(final_approve_status = 'Ongoing').count()
            return (total, approved, pending)

        
        def _target_total():
            total = 0
            for r in AchievableTargetBol.objects.filter(fiscal_year = current_year, bol_type = 'TARGET').values('plant', 'bol'):
                std_plant = normalize_plant(r['plant'])
                if not std_plant:
                    continue
                if not std_plant != '未知':
                    continue
                v = _f(r['bol'])
                if not v:
                    continue
                total += v
            return total

        
        def _plant_options():
            plant_set = set()
            for r in BudgetBol.objects.filter(fiscal_year = current_year, bol_type = 'BUDGET').values('plant'):
                if not r.get('plant'):
                    r.get('plant')
                sp = normalize_plant('')
                if not sp:
                    continue
                if not sp != '未知':
                    continue
                plant_set.add(sp)
            for r in AchievableTargetBol.objects.filter(fiscal_year = current_year, bol_type = 'ACHIEVABLE').values('plant'):
                if not r.get('plant'):
                    r.get('plant')
                sp = normalize_plant('')
                if not sp:
                    continue
                if not sp != '未知':
                    continue
                plant_set.add(sp)
            return sorted(plant_set)

        tasks = [
            (_kpi_counts, (), { }),
            (self._load_ame_kpis, (current_year,), { }),
            (self._calc_plant_achievement, (current_year,), { }),
            (_target_total, (), { }),
            ((lambda : HighBolTracking.objects.filter(status__in = [
'OPEN',
'IN_PROGRESS']).count()), (), { }),
            (self._calc_bol_lifecycle, (current_year,), {
                'plants': lifecycle_plants }),
            (_plant_options, (), { }),
            (self._calc_improvement_opportunities, (current_year,), { }),
            (self._calc_improvement_opportunities, (current_year,), {
                'direction': 'up' }),
            (_calc_achievable_yoy_multi, ([
                current_year - 1,
                current_year],), {
                'plants': None,
                'top_n': 10 }),
            (self._calc_yearly_compare, (current_year,), { }),
            (self._calc_plant_compare, (compare_year,), {
                'plants': plants,
                'process_types': process_types,
                'roof_types': roof_types })]
        (total_bol_records, approved_count, pending_count) = ()
        ame_kpis = self._run_parallel(tasks)
        plant_achievement = None
        target_total = None
        tracking_open = None
        bol_lifecycle = None
        lifecycle_plant_options = None
        improvement_opportunities = None
        improvement_increases = None
        achievable_yoy = None
        yearly_compare = None
        plant_compare = None
        approval_rate = round((approved_count / total_bol_records) * 100, 1) if total_bol_records > 0 else 0
        total_budget = (lambda .0: for p in .0:
p['budget'].0)(plant_achievement())
        total_achievable = (lambda .0: for p in .0:
p['achievable'].0)(plant_achievement())
        budget_achievement_rate = round((total_budget / total_achievable) * 100, 1) if total_achievable > 0 else 0
        target_achievement_rate = round((total_achievable / target_total) * 100, 1) if target_total > 0 else 0
        if not ame_kpis['Acutal CT Rate']['cmc_pct']:
            ame_kpis['Acutal CT Rate']['cmc_pct']
        if not ame_kpis['BOL Reduction Rate']['cmc_pct']:
            ame_kpis['BOL Reduction Rate']['cmc_pct']
        if not ame_kpis['BOL Updates Rate']['cmc_pct']:
            ame_kpis['BOL Updates Rate']['cmc_pct']
        kpi_cards = {
            'approval_rate': approval_rate,
            'approved_count': approved_count,
            'total_bol_records': total_bol_records,
            'pending_count': pending_count,
            'ct_capture_rate': 0,
            'bol_reduction_rate': 0,
            'bol_updates_rate': 0,
            'budget_achievement_rate': budget_achievement_rate,
            'target_achievement_rate': target_achievement_rate,
            'tracking_open': tracking_open }
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
            'ame_kpis': ame_kpis })
        
        
        
        

    
    def _run_parallel(self, tasks):
        '''并行执行互不依赖的查询块，按提交顺序返回结果。

        tasks: [(fn, args, kwargs), ...]
        - 任务均为 IO 密集（跨库 SQL 网络往返），GIL 在等待期释放，并行有效
        - worker 线程结束后关闭该线程持有的数据库连接（Django 连接按线程
          隔离），避免线程池销毁时 ODBC 连接泄漏
        - 任一任务异常会原样抛出（与串行执行的错误行为一致）
        '''
        ThreadPoolExecutor = ThreadPoolExecutor
        import concurrent.futures
        connections = connections
        import django.db
        
        def _wrap(fn = None, args = None, kwargs = None):
            
            try:
                connections.close_all()
                return fn()
            except:
                connections.close_all()


        pool = ThreadPoolExecutor(max_workers = 6)
        for fn, args, kwargs in :
            pass
        futures = , []
        args = tasks, fn, args, kwargs
        fn = None
        kwargs = None
        for None in :
            pass
        None(None, None)
        return 
        
        
        with None:
            if not f,:
                pass
        None, None, None, None, futures, f, , [], , f,, kwargs, args, fn

    
    def _calc_sct_act_gap_pct(self):
        '''计算 SCT vs ACT 平均差距百分比'''
        BolOverView = BolOverView
        import apps.dynamic_bol.models
        act_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull = False)
        act_map = { }
        for r in act_qs.values('project_code', 'line_nr', 'company', 'cycle_time_bottleneck').order_by('-update_time'):
            if not r.get('company'):
                r.get('company')
            key = (r['project_code'], r['line_nr'], normalize_plant(''))
            if not key not in act_map:
                continue
            act_map[key] = float(r['cycle_time_bottleneck'])
        sct_qs = BolOverView.objects.filter(final_approve_status = 'Approved', ct__isnull = False).values('program_code', 'line_nr', 'location', 'ct').order_by('-submit_date')
        sct_map = { }
        for r in sct_qs:
            if not r.get('location'):
                r.get('location')
            key = (r['program_code'], r['line_nr'], normalize_plant(''))
            if not key not in sct_map:
                continue
            sct_map[key] = float(r['ct'])
        gaps = []
        for key, sct in sct_map.items():
            act = act_map.get(key)
            if not act:
                continue
            if not act > 0:
                continue
            gap_pct = ((sct - act) / sct) * 100
            gaps.append(gap_pct)
        if gaps:
            return round(sum(gaps) / len(gaps), 1)

    
    def _calc_sct_act_gap_over_count(self, threshold_pct = (15,)):
        '''计算 SCT vs ACT 差距超过指定百分比的项目数

        Args:
            threshold_pct: 差距百分比阈值（默认 15）
        '''
        BolOverView = BolOverView
        import apps.dynamic_bol.models
        act_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull = False)
        act_map = { }
        for r in act_qs.values('project_code', 'line_nr', 'company', 'cycle_time_bottleneck').order_by('-update_time'):
            if not r.get('company'):
                r.get('company')
            key = (r['project_code'], r['line_nr'], normalize_plant(''))
            if not key not in act_map:
                continue
            act_map[key] = float(r['cycle_time_bottleneck'])
        sct_qs = BolOverView.objects.filter(final_approve_status = 'Approved', ct__isnull = False).values('program_code', 'line_nr', 'location', 'ct').order_by('-submit_date')
        sct_map = { }
        for r in sct_qs:
            if not r.get('location'):
                r.get('location')
            key = (r['program_code'], r['line_nr'], normalize_plant(''))
            if not key not in sct_map:
                continue
            sct_map[key] = float(r['ct'])
        count = 0
        for key, sct in sct_map.items():
            act = act_map.get(key)
            if not act:
                continue
            if not act > 0:
                continue
            if not sct > 0:
                continue
            gap_pct = abs(((sct - act) / sct) * 100)
            if not gap_pct > threshold_pct:
                continue
            count += 1
        return count

    
    def _calc_bol_approval_detail(self, current_year, limit = (100,)):
        '''本年度 BOL 审批更新记录明细（用于指标卡详情弹窗）

        返回字段对齐 BOL 更新记录模块的列表：提交人、提交时间、CT、HC、OEE、BOL 值等。
        '''
        qs = BolOverView.objects.filter(submit_date__year = current_year).order_by('-submit_date')[:limit]
        items = []
        for r in qs.values('bol_nr', 'program_code', 'program_name', 'customer', 'location', 'process', 'type', 'line_nr', 'ct', 'hc', 'oee', 'bol', 'qws_bol', 'gap_bol', 'final_approve_status', 'submit_date', 'submit_user_name'):
            if not r['final_approve_status']:
                r['final_approve_status']
            if not r['submit_user_name']:
                r['submit_user_name']
            'submit_date'[r['submit_date'].strftime('%Y-%m-%d %H:%M') if r['submit_date'] else '']('submit_user_name'[''])
        return items

    
    def _calc_ct_programs_detail(self, current_year, limit = (100,)):
        '''实测 CT 覆盖项目明细（用于指标卡详情弹窗）

        按项目代码聚合 RealCtExtract（本年度），返回项目级清单：
        项目代码、项目名称、工厂、产线数、工位数、最新采集时间。
        '''
        _Count = Count
        _Max = Max
        import django.db.models
        qs = RealCtExtract.objects.filter(update_time__year = current_year).values('project_code', 'project_name', 'company').annotate(line_count = _Count('line_nr', distinct = True), station_count = _Count('station_nr', distinct = True), latest_update = _Max('update_time')).order_by('-latest_update')[:limit]
        items = []
        for r in qs:
            items.append({
                'project_code': r['project_code'],
                'project_name': r['project_name'],
                'company': normalize_plant(r['company']),
                'line_count': r['line_count'],
                'station_count': r['station_count'],
                'latest_update': r['latest_update'].strftime('%Y-%m-%d %H:%M') if r['latest_update'] else '' })
        return items

    
    def _calc_net_hours_saved(self, current_year):
        '''计算本财年 Budget BOL 对比上一财年的净节省工时'''
        CbcoRecord = CbcoRecord
        import apps.budget_bol.cbco_models
        from_year = current_year - 1
        to_year = current_year
        from_records = BudgetBol.objects.filter(fiscal_year = from_year, bol_type = 'BUDGET').values('project_code', 'process_type', 'budget_bol')
        to_records = BudgetBol.objects.filter(fiscal_year = to_year, bol_type = 'BUDGET').values('project_code', 'process_type', 'budget_bol')
        from_map = { }
        for r in from_records:
            key = (r['project_code'], r['process_type'])
            bol = _f(r['budget_bol'])
            if not key not in from_map:
                continue
            from_map[key] = bol
        to_map = { }
        for r in to_records:
            key = (r['project_code'], r['process_type'])
            bol = _f(r['budget_bol'])
            if not key not in to_map:
                continue
            to_map[key] = bol
        all_codes = set | (lambda .0: for r in .0:
r['project_code'].0)(to_records())
        volume_map = { }
        if all_codes:
            for r in CbcoRecord.objects.filter(program_number__in = list(all_codes), year = to_year).values('program_number', 'volume'):
                if not r['volume']:
                    r['volume']
                volume_map[r['program_number']] = 0
        common_keys = set(from_map.keys()) & set(to_map.keys())
        total_hours = 0
        for key in common_keys:
            from_bol = from_map[key]
            to_bol = to_map[key]
            if from_bol is not None and to_bol is not None and from_bol <= 0 or to_bol <= 0:
                continue
            to_vol = volume_map.get(key[0], 0)
            bol_reduction = from_bol - to_bol
            hours_saved = to_vol * bol_reduction / 60 if to_vol > 0 else 0
            total_hours += hours_saved
        return round(total_hours, 1)

    
    def _calc_bol_lifecycle(self, current_year, plants = (None,)):
        '''BOL 全链路对比：Budget → Achievable → Target → 实测BOL

        实测BOL 计算方式：
          BOL = CT × HC × (1+1/15) / OEE / 60
          - CT  来自 BottleNeckCt（按 project_code + line_nr 取最新瓶颈工时）
          - HC  来自 BolOverViewByProcess（按 program_code + line_nr + process 取最新提交记录）
          - OEE 来自 BolOverViewByProcess（同上）

        Top10 选择标准：当年 CBCO_record 中 Volume 需求最高的项目
        plants: 标准化工厂短代码列表（None=全部；传多工厂取它们项目的并集综合排序）
        '''
        AchievableTargetBol = AchievableTargetBol
        import apps.budget_bol.models
        budget_map = { }
        for r in BudgetBol.objects.filter(fiscal_year = current_year, bol_type = 'BUDGET').values('project_code', 'process_type', 'budget_bol', 'plant'):
            if not r.get('plant'):
                r.get('plant')
            sp = normalize_plant('')
            if sp or sp == '未知':
                continue
            if plants and sp not in plants:
                continue
            key = (r['project_code'], r['process_type'])
            if not key not in budget_map:
                continue
            budget_map[key] = {
                'value': _f(r['budget_bol']),
                'plant': sp }
        achievable_map = { }
        for r in AchievableTargetBol.objects.filter(fiscal_year = current_year, bol_type = 'ACHIEVABLE').values('project_code', 'process_type', 'bol', 'plant'):
            if not r.get('plant'):
                r.get('plant')
            sp = normalize_plant('')
            if sp or sp == '未知':
                continue
            if plants and sp not in plants:
                continue
            key = (r['project_code'], r['process_type'])
            if not key not in achievable_map:
                continue
            achievable_map[key] = {
                'value': _f(r['bol']),
                'plant': sp }
        target_map = { }
        for r in AchievableTargetBol.objects.filter(fiscal_year = current_year, bol_type = 'TARGET').values('project_code', 'process_type', 'bol', 'plant'):
            if not r.get('plant'):
                r.get('plant')
            sp = normalize_plant('')
            if sp or sp == '未知':
                continue
            if plants and sp not in plants:
                continue
            key = (r['project_code'], r['process_type'])
            if not key not in target_map:
                continue
            target_map[key] = _f(r['bol'])
        bp_qs = BolOverViewByProcess.objects.filter(hc__isnull = False, oee__isnull = False).order_by('-update_time')
        bp_map = { }
        for r in bp_qs.values('program_code', 'process', 'line_nr', 'hc', 'oee', 'update_time'):
            key = (r['program_code'], r['process'])
            if not key not in bp_map:
                continue
            if not r['line_nr']:
                r['line_nr']
            bp_map[key] = {
                'hc': _f(r['hc']),
                'oee': _f(r['oee']),
                'line_nr': ''.strip() }
        bn_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull = False).order_by('-update_time')
        bn_map = { }
        for r in bn_qs.values('project_code', 'line_nr', 'cycle_time_bottleneck'):
            if not r['project_code']:
                r['project_code']
            if not r['line_nr']:
                r['line_nr']
            bn_key = ('', ''.strip())
            if not bn_key not in bn_map:
                continue
            bn_map[bn_key] = _f(r['cycle_time_bottleneck'])
        actual_map = { }
        for key, bp_info in bp_map.items():
            (program_code, process) = key
            line_nr = bp_info.get('line_nr', '')
            hc = bp_info.get('hc')
            oee = bp_info.get('oee')
            bottleneck_ct = bn_map.get((program_code, line_nr)) if line_nr else None
            if bottleneck_ct is None:
                continue
            if hc is None:
                continue
            if oee is None:
                continue
            actual_map[key] = calc_bol(bottleneck_ct, hc, oee)
        volume_map = { }
        name_map = { }
        for r in CbcoRecord.objects.filter(year = current_year, volume__isnull = False).values('program_number', 'volume', 'program_description'):
            code = r['program_number']
            if not code:
                continue
            if code not in volume_map:
                if not r['volume']:
                    r['volume']
                volume_map[code] = 0
            if not code not in name_map:
                continue
            if not r.get('program_description'):
                continue
            name_map[code] = r['program_description']
        common_keys = set(budget_map.keys()) & set(achievable_map.keys())
        items = []
        for key in common_keys:
            b_entry = budget_map.get(key)
            a_entry = achievable_map.get(key)
            budget = b_entry['value'] if b_entry else None
            achievable = a_entry['value'] if a_entry else None
            if b_entry:
                pass
            elif a_entry:
                pass
            
            plant = ''
            target = target_map.get(key)
            actual = actual_map.get(key)
            if budget is not None and achievable is not None or budget <= 0:
                continue
            gap = budget - achievable
            saving_pct = round((gap / budget) * 100, 1) if budget > 0 else None
            volume = volume_map.get(key[0], 0)
            actual_ach_gap_pct = None
            if actual is not None and achievable and achievable > 0:
                actual_ach_gap_pct = round(((actual - achievable) / achievable) * 100, 1)
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
                'actual_ach_gap_pct': actual_ach_gap_pct })
        items.sort(key = (lambda x: (0 if x['process_type'] == 'FA' else 1, -x['volume'])))
        return items[:20]

    
    def _calc_sct_vs_act_top(self):
        '''SCT vs ACT 差距 Top 10'''
        BolOverView = BolOverView
        import apps.dynamic_bol.models
        act_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull = False)
        act_map = { }
        act_info = { }
        for r in act_qs.values('company', 'project_code', 'project_name', 'line_nr', 'cycle_time_bottleneck').order_by('-update_time'):
            if not r.get('company'):
                r.get('company')
            std_company = normalize_plant('')
            key = (r['project_code'], r['line_nr'], std_company)
            if not key not in act_map:
                continue
            act_map[key] = float(r['cycle_time_bottleneck'])
            if not r['project_name']:
                r['project_name']
            act_info[key] = {
                'company': std_company,
                'project_name': '' }
        sct_qs = BolOverView.objects.filter(final_approve_status = 'Approved', ct__isnull = False).values('program_code', 'line_nr', 'process', 'location', 'ct').order_by('-submit_date')
        sct_map = { }
        sct_process = { }
        for r in sct_qs:
            if not r.get('location'):
                r.get('location')
            std_loc = normalize_plant('')
            key = (r['program_code'], r['line_nr'], std_loc)
            if not key not in sct_map:
                continue
            sct_map[key] = float(r['ct'])
            if not r['process']:
                r['process']
            sct_process[key] = ''
        items = []
        for key, sct in sct_map.items():
            act = act_map.get(key)
            if not act:
                continue
            if not act > 0:
                continue
            if not sct > 0:
                continue
            gap = sct - act
            gap_pct = (gap / sct) * 100
            info = act_info.get(key, { })
            items.append({
                'project_code': key[0],
                'project_name': info.get('project_name', ''),
                'line_nr': key[1],
                'process': sct_process.get(key, ''),
                'company': info.get('company', key[2]),
                'sct': round(sct, 2),
                'act': round(act, 2),
                'gap': round(gap, 2),
                'gap_pct': round(gap_pct, 1) })
        items.sort(key = (lambda x: x['gap_pct']))
        return items[:10]

    
    def _calc_yearly_compare(self, current_year, years_n = (3,)):
        '''近 3 年 Budget vs Achievable 总量对比（支持下钻明细）

        返回结构：
          - years/budget/achievable: 年度总量（顶层视图）
          - detail: 扁平明细 [{year, plant, process, budget, achievable}]
            前端按 年 → 工厂 → 工艺 三级钻取聚合
        用于 Tab 2 副图（点击柱子下钻）
        '''
        AchievableTargetBol = AchievableTargetBol
        import apps.budget_bol.models
        defaultdict = defaultdict
        import collections
        years = list(range((current_year - years_n) + 1, current_year + 1))
        agg = defaultdict((lambda : {
'budget': 0,
'achievable': 0 }))
        for y in years:
            for r in BudgetBol.objects.filter(fiscal_year = y, bol_type = 'BUDGET').values('plant', 'process_type', 'budget_bol'):
                if not r['plant']:
                    r['plant']
                std_plant = normalize_plant('')
                if std_plant or std_plant == '未知':
                    continue
                v = _f(r['budget_bol'])
                if not v:
                    continue
                if not r['process_type']:
                    r['process_type']
                if not ''.strip():
                    ''.strip()
                process = 'N/A'
                key = (y, std_plant, process)
            for None in AchievableTargetBol.objects.filter(fiscal_year = y, bol_type = 'ACHIEVABLE').values('plant', 'process_type', 'bol'):
                if not r['plant']:
                    r['plant']
                std_plant = normalize_plant('')
                if std_plant or std_plant == '未知':
                    continue
                v = _f(r['bol'])
                if not v:
                    continue
                if not r['process_type']:
                    r['process_type']
                if not ''.strip():
                    ''.strip()
                process = 'N/A'
                key = (y, std_plant, process)
        for y, p, proc in :
            vals = None
        detail = , []
        proc = sorted(agg.items()), y, p, proc, vals
        p = None
        y = None
        vals = None
        for None in budget_by_year,:
            pass
        budget_by_year, = , { }
        y = years, y
        for None in achievable_by_year,:
            pass
        achievable_by_year, = , { }
        y = years, y
        for d in detail:
            pass
        for None in :
            pass
        for None in :
            pass
        for None in :
            pass
        return {
            'years': years, y,
            'budget': , [], ,
            'achievable': y,,
            'detail': detail }
        
        
        
        
        
        

    _percentile = (lambda sorted_vals, p: n = len(sorted_vals)if n == 1:
sorted_vals[0]k = (None - 1) * pf = int(k)c = min(f + 1, n - 1)sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f]))()
    
    def _calc_plant_compare(self, compare_year, plants, process_types, roof_types = (None, None, None)):
        '''工厂间 Achievable BOL 分布对比（箱线图统计）

        X 轴=工厂，Y 轴=Achievable BOL；各工厂项目 BOL 的 min/Q1/median/Q3/max/mean/count
        筛选：plants（工厂短代码多选）/ process_types（FA/IHR/IHE 多选）/ roof_types（产品类型多选）
        产品类型：cbco_records.typ_of_roof 实际值（program_number ↔ project_code + 同财年关联）
        返回：{year, available_years, roof_type_options, stats}
        '''
        AchievableTargetBol = AchievableTargetBol
        import apps.budget_bol.models
        defaultdict = defaultdict
        import collections
        for None in :
            if y:
                pass
        continue
        , {}, (y,, reverse = True) = AchievableTargetBol.objects.filter(bol_type = 'ACHIEVABLE').values_list('fiscal_year', flat = True).distinct(), y
        for None in :
            if not v:
                v
            if ''.strip():
                if not v:
                    v
        continue
        , {}, (v,) = CbcoRecord.objects.exclude(typ_of_roof__isnull = True).exclude(typ_of_roof = '').values_list('typ_of_roof', flat = True).distinct(), v
        qs = AchievableTargetBol.objects.filter(fiscal_year = compare_year, bol_type = 'ACHIEVABLE').values('project_code', 'process_type', 'plant', 'bol')
        if process_types:
            qs = qs.filter(process_type__in = process_types)
        if plants:
            raw_values = []
            for p in plants:
                raw_values.extend(get_plant_raw_values(p))
            qs = qs.filter(plant__in = raw_values)
        items_map = { }
        for r in qs:
            std_plant = normalize_plant(r['plant'])
            if std_plant or std_plant == '未知':
                continue
            if plants and std_plant not in plants:
                continue
            key = (r['project_code'], std_plant)
            if not key not in items_map:
                continue
            items_map[key] = {
                'project_code': r['project_code'],
                'plant': std_plant,
                'process_type': r['process_type'],
                'bol': _f(r['bol']) }
        all_codes = (lambda .0: for k in .0:
k[0].0)(items_map.keys()())
        roof_map = { }
        volume_map = { }
        name_map = { }
        if all_codes:
            for r in CbcoRecord.objects.filter(program_number__in = list(all_codes), year = compare_year).values('program_number', 'typ_of_roof', 'volume', 'program_description'):
                code = r['program_number']
                if not r.get('typ_of_roof'):
                    r.get('typ_of_roof')
                val = ''.strip()
                if not (code not in roof_map or val) and roof_map[code]:
                    roof_map[code] = val
                if code not in volume_map:
                    if not r.get('volume'):
                        r.get('volume')
                    volume_map[code] = 0
                if not code not in name_map:
                    continue
                if not r.get('program_description'):
                    continue
                name_map[code] = r['program_description']
        vals_by_plant = defaultdict(list)
        details = []
        for project_code, _plant in items_map.items():
            v = None
            if roof_types and roof_map.get(project_code, '') not in roof_types:
                continue
            if v['bol'] is None:
                continue
            vals_by_plant[v['plant']].append(v['bol'])
            details.append({
                'project_code': project_code,
                'project_name': name_map.get(project_code, project_code),
                'plant': v['plant'],
                'process_type': v['process_type'],
                'bol': round(v['bol'], 2),
                'roof_type': roof_map.get(project_code, ''),
                'volume': volume_map.get(project_code, 0) })
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
                'mean': round(sum(vals_sorted) / len(vals_sorted), 2) })
        stats.sort(key = (lambda s: -s['median']))
        details.sort(key = (lambda d: if not d['bol']:
d['bol']-0))
        return {
            'year': compare_year,
            'available_years': available_years,
            'roof_type_options': roof_type_options,
            'stats': stats,
            'details': details }
        
        

    
    def _calc_plant_achievement(self, current_year):
        '''各工厂 Budget 达成率（ΣAchievable / ΣBudget）

        用于 Tab 4 各工厂达成率分组柱状
        '''
        AchievableTargetBol = AchievableTargetBol
        import apps.budget_bol.models
        defaultdict = defaultdict
        import collections
        budget_by_plant = defaultdict(float)
        for r in BudgetBol.objects.filter(fiscal_year = current_year, bol_type = 'BUDGET').values('plant', 'budget_bol'):
            std_plant = normalize_plant(r['plant'])
            if not std_plant:
                continue
            if not std_plant != '未知':
                continue
            v = _f(r['budget_bol'])
            if not v:
                continue
        defaultdict(float) = None
        for r in AchievableTargetBol.objects.filter(fiscal_year = current_year, bol_type = 'ACHIEVABLE').values('plant', 'bol'):
            std_plant = normalize_plant(r['plant'])
            if not std_plant:
                continue
            if not std_plant != '未知':
                continue
            v = _f(r['bol'])
            if not v:
                continue
        set(budget_by_plant.keys()) | set(ach_by_plant.keys()) = None
        result = []
        for plant in sorted(all_plants):
            budget = budget_by_plant.get(plant, 0)
            achievable = ach_by_plant.get(plant, 0)
            achievement_rate = round((budget / achievable) * 100, 1) if achievable > 0 else 0
            result.append({
                'plant': plant,
                'budget': round(budget, 2),
                'achievable': round(achievable, 2),
                'achievement_rate': achievement_rate })
        return result

    AME_KPI_NAMES = ('Acutal CT Rate', 'BOL Reduction Rate', 'BOL Updates Rate')
    
    def _load_ame_kpis(self, current_year):
        """从 HRDB CN_AME_KPI_monthlyHistory 读取 BOL 相关官方 KPI 值

        每个指标取本年最新月份，按工厂返回；kpi_value 为小数，转为百分比。
        返回 {kpi_name: {'month': m, 'by_plant': {plant: pct}, 'avg_pct': x, 'cmc_pct': y}}
        用于 KPI 卡（CMC 区域值）+ Tab 4 图表（分工厂，CMC 由前端追加在最后）
        """
        result = { }
        for kpi_name in self.AME_KPI_NAMES:
            qs = KpiMonthlyHistory.objects.filter(year = current_year, kpi_name = kpi_name)
            latest_month = qs.order_by('-month').values_list('month', flat = True).first()
            if latest_month is None:
                result[kpi_name] = {
                    'month': None,
                    'by_plant': { },
                    'avg_pct': 0,
                    'cmc_pct': None }
                continue
            by_plant = { }
            for r in qs.filter(month = latest_month).values('location', 'kpi_value'):
                if not r['location']:
                    r['location']
                plant = normalize_plant('')
                v = _f(r['kpi_value'])
                if not plant:
                    continue
                if not plant != '未知':
                    continue
                if v is None:
                    continue
                by_plant[plant] = round(v * 100, 1)
            cmc_pct = by_plant.pop('CMC', None)
            avg_pct = round(sum(by_plant.values()) / len(by_plant), 1) if by_plant else 0
            result[kpi_name] = {
                'month': latest_month,
                'by_plant': by_plant,
                'avg_pct': avg_pct,
                'cmc_pct': cmc_pct }
        return result

    
    def _calc_improvement_opportunities(self, current_year, plants, direction = (None, 'down')):
        """Achievable BOL 同比项目清单（全量，按变动幅度降序）

        仅做客观的 BOL 同比对比（本年 vs 上年），不做人年（HC）换算。
        用于 同/环比趋势 Tab 副表。
        direction: 'down'=下降清单（改善，本年<上年）；'up'=上升清单（恶化，本年>上年）
        plants: 标准化工厂短代码列表（None=全部）
        """
        AchievableTargetBol = AchievableTargetBol
        import apps.budget_bol.models
        from_year = current_year - 1
        to_year = current_year
        
        def _build_ach_map(fy = None):
            m = { }
            for r in AchievableTargetBol.objects.filter(fiscal_year = fy, bol_type = 'ACHIEVABLE').values('project_code', 'process_type', 'bol', 'plant'):
                key = (r['project_code'], r['process_type'])
                sp = normalize_plant(r['plant'])
                if plants:
                    if sp and sp == '未知' or sp not in plants:
                        continue
                if not key not in m:
                    continue
                m[key] = {
                    'bol': _f(r['bol']),
                    'plant': sp }
            return m

        from_map = _build_ach_map(from_year)
        to_map = _build_ach_map(to_year)
        name_map = { }
        volume_map = { }
        all_codes = set | (lambda .0: for k in .0:
k[0].0)(to_map.keys()())
        if all_codes:
            for r in CbcoRecord.objects.filter(program_number__in = list(all_codes), year = to_year).values('program_number', 'volume', 'program_description'):
                if not r['volume']:
                    r['volume']
                volume_map[r['program_number']] = 0
                if not r.get('program_description'):
                    continue
                name_map[r['program_number']] = r['program_description']
        common_keys = set(from_map.keys()) & set(to_map.keys())
        items = []
        for key in common_keys:
            from_bol = from_map[key]['bol']
            to_bol = to_map[key]['bol']
            if from_bol is not None and to_bol is not None or from_bol <= 0:
                continue
            if direction == 'down' and to_bol >= from_bol:
                continue
            if direction == 'up' and to_bol <= from_bol:
                continue
            bol_reduction = from_bol - to_bol
            items.append({
                'project_code': key[0],
                'process_type': key[1],
                'project_name': name_map.get(key[0], key[0]),
                'plant': to_map[key]['plant'],
                'volume': volume_map.get(key[0], 0),
                'from_bol': round(from_bol, 2),
                'to_bol': round(to_bol, 2),
                'bol_reduction': round(bol_reduction, 2) })
        items.sort(key = (lambda x: x['bol_reduction']), reverse = True)
        return items



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
        if top_n is not None or top_n < 0:
            top_n = 10
        years = []
        if years_param:
            for part in years_param.split(','):
                part = part.strip()
                if not part.isdigit():
                    continue
                years.append(int(part))
        if not years:
            years = [
                timezone.now().year]
        plants = None
        if plants_param:
            for None in plants,:
                if not p.strip():
                    continue
            plants, = , []
            p = plants_param.split(','), p
        data = _calc_achievable_yoy_multi(years, plants = plants, top_n = top_n)
        return Response(data)
        



def _calculate_improve_target_achievable_bol(row):

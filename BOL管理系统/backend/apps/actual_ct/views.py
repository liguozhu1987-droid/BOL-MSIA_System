# -*- coding: utf-8 -*-
"""实测CT 视图（HRDB 只读）"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend

from apps.actual_ct.models import RealCtExtract, RealCtExtractPerDay, BottleNeckCt, CtRealtimeStatus, ProjectAcquisition
from apps.actual_ct.serializers import (
    RealCtExtractSerializer, RealCtExtractPerDaySerializer,
    BottleNeckCtSerializer, CtRealtimeStatusSerializer,
)
from apps.actual_ct.analysis import (
    fetch_ct_analysis_from_db, fetch_filter_options,
    execute_ope_query, OPE_CLEAN_WHERE, build_histogram, build_station_ct_analysis,
    compute_represent_ct, filter_outliers_iqr, build_xbar_r_chart,
    quote_sql_value,
)
from bol_platform.plant_utils import normalize_plant, get_plant_raw_values


class RealCtExtractViewSet(viewsets.ReadOnlyModelViewSet):
    """工位级实测CT（HRDB 只读）"""
    queryset = RealCtExtract.objects.all()
    serializer_class = RealCtExtractSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['project_code', 'line_nr', 'station_nr', 'company']
    search_fields = ['project_code', 'project_name', 'line_nr', 'station_nr']
    ordering_fields = ['update_time', 'cycle_time', 'count', 'project_code']
    ordering = ['-update_time']

    def get_queryset(self):
        queryset = super().get_queryset()
        months = self.request.query_params.get('months', '1')
        try:
            month_value = int(months)
        except (TypeError, ValueError):
            month_value = 1
        month_value = max(month_value, 1)
        from datetime import date, timedelta
        start_date = (date.today() - timedelta(days=month_value * 30)).replace(day=1)
        return queryset.filter(update_time__gte=start_date)


class RealCtExtractPerDayViewSet(viewsets.ReadOnlyModelViewSet):
    """按天的实测CT（HRDB 只读）"""
    queryset = RealCtExtractPerDay.objects.all()
    serializer_class = RealCtExtractPerDaySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['project_code', 'line_nr', 'station_nr', 'company', 'start_time']
    search_fields = ['project_code', 'project_name', 'line_nr', 'station_nr']
    ordering_fields = ['start_time', 'cycle_time', 'update_time']
    ordering = ['-start_time', '-update_time']

    def get_queryset(self):
        queryset = super().get_queryset()
        months = self.request.query_params.get('months', '1')
        try:
            month_value = int(months)
        except (TypeError, ValueError):
            month_value = 1
        month_value = max(month_value, 1)
        from datetime import date, timedelta
        start_date = (date.today() - timedelta(days=month_value * 30)).replace(day=1)
        return queryset.filter(start_time__gte=start_date)


class BottleNeckCtViewSet(viewsets.ReadOnlyModelViewSet):
    """瓶颈工位CT（HRDB 只读）"""
    queryset = BottleNeckCt.objects.all()
    serializer_class = BottleNeckCtSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['project_code', 'line_nr', 'company']
    search_fields = ['project_code', 'project_name', 'line_nr']
    ordering_fields = ['update_time', 'cycle_time_bottleneck']
    ordering = ['-update_time']

    def get_queryset(self):
        queryset = super().get_queryset()
        months = self.request.query_params.get('months', '1')
        try:
            month_value = int(months)
        except (TypeError, ValueError):
            month_value = 1
        month_value = max(month_value, 1)
        from datetime import date, timedelta
        start_date = (date.today() - timedelta(days=month_value * 30)).replace(day=1)
        return queryset.filter(update_time__gte=start_date)


class CtRealtimeStatusViewSet(viewsets.ReadOnlyModelViewSet):
    """产线实时状态（HRDB 只读）"""
    queryset = CtRealtimeStatus.objects.all()
    serializer_class = CtRealtimeStatusSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['company', 'line_nr', 'project_code', 'state']
    ordering_fields = ['company', 'line_nr']


class CtAnalysisViewSet(viewsets.ViewSet):
    """实测CT近3个月清洗后分析。"""

    @action(detail=False, methods=['get'])
    def summary(self, request):
        try:
            months = int(request.query_params.get('months', 3))
        except (TypeError, ValueError):
            months = 3
        months = max(months, 1)
        filters = {
            'company': request.query_params.get('company', ''),
            'project_code': request.query_params.get('project_code', ''),
            'line_nr': request.query_params.get('line_nr', ''),
            'station_nr': request.query_params.get('station_nr', ''),
        }
        payload = fetch_ct_analysis_from_db(filters=filters, months=months, bin_count=10)
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def filter_options(self, request):
        try:
            months = int(request.query_params.get('months', 3))
        except (TypeError, ValueError):
            months = 3
        months = max(months, 1)
        filters = {
            'company': request.query_params.get('company', ''),
            'project_code': request.query_params.get('project_code', ''),
            'line_nr': request.query_params.get('line_nr', ''),
            'station_nr': request.query_params.get('station_nr', ''),
        }
        payload = fetch_filter_options(filters=filters, months=months)
        return Response(payload, status=status.HTTP_200_OK)


# ======================== 新API：实测CT重构 ========================

from collections import defaultdict
import statistics
from datetime import date, timedelta
from django.db.models import Max, Q
from apps.dynamic_bol.models import BolOverView


def _split_csv(param_value):
    """将逗号分隔的参数拆分为列表（支持多选）"""
    if not param_value:
        return []
    return [x.strip() for x in param_value.split(',') if x.strip()]


def _build_in_clause(values):
    """构建 SQL IN 子句的值列表，如 ('BJ','SH')；空则返回 None"""
    if not values:
        return None
    escaped = [str(v).replace("'", "''") for v in values]
    return "('{}')".format("','".join(escaped))


def _build_ope_distinct_sql(column, label_column, parent_filters):
    """构建 OPE 视图去重查询 SQL（不执行，仅返回 SQL 字符串）

    parent_filters: dict，键为 company/line_nr/project_code/project_name，值为列表
    """
    where_clauses = [OPE_CLEAN_WHERE]
    col_map = {
        'company': 'company',
        'line_nr': 'lineNr',
        'project_code': 'projectCode',
        'project_name': 'projectName',
    }
    for key, col in col_map.items():
        vals = parent_filters.get(key)
        in_clause = _build_in_clause(vals)
        if in_clause:
            where_clauses.append(f"{col} IN {in_clause}")

    where_sql = ' AND '.join(where_clauses)
    select_parts = [f"DISTINCT {column} AS value"]
    if label_column and label_column != column:
        select_parts.append(f"{label_column} AS label")
    return f"SELECT {', '.join(select_parts)} FROM OPE.V_fact_cn_realTimeCT_overView WHERE {where_sql} ORDER BY value"


def _query_ope_distinct(column, label_column, parent_filters):
    """从 OPE.V_fact_cn_realTimeCT_overView 查询去重列（应用数据清洗）

    parent_filters: dict，键为 company/line_nr/project_code/project_name，值为列表
    """
    sql = _build_ope_distinct_sql(column, label_column, parent_filters)
    rows = execute_ope_query(sql)
    return rows


def _query_ope_distinct_batch(queries):
    """批量执行多个 OPE 去重查询，复用同一个数据库连接。

    Args:
        queries: list of (column, label_column, parent_filters) 元组

    Returns:
        list of rows 列表，与 queries 一一对应
    """
    from apps.actual_ct.analysis import get_ope_connection
    conn = None
    cursor = None
    try:
        conn = get_ope_connection()
        cursor = conn.cursor()
        results = []
        for column, label_column, parent_filters in queries:
            sql = _build_ope_distinct_sql(column, label_column, parent_filters)
            cursor.execute(sql)
            columns = [c[0] for c in cursor.description]
            results.append([dict(zip(columns, row)) for row in cursor.fetchall()])
        return results
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


class CascadeFilterView(APIView):
    """级联筛选器：工厂 → 产线 → 项目编号 → 项目名称 → 工位名称（支持多选级联）

    数据来源（HRDB 本地表，替代原 OPE 远程视图，显著提升查询速度）：
        - 前4层（company/lineNr/projectCode/projectName）：CN_IE_realTime_projects_acquisition（136条配置记录）
        - 第5层（stationNr）：CN_IE_CT_realCT_extract（工位级CT数据）
    数据清洗：项目代号 T/S 开头、字段非空
    入参（均支持逗号分隔的多选值）：company, line_nr, project_code, project_name
    """

    def get(self, request):
        from django.db.models import Q

        companies_sel = _split_csv(request.query_params.get('company', ''))
        lines_sel = _split_csv(request.query_params.get('line_nr', ''))
        project_codes_sel = _split_csv(request.query_params.get('project_code', ''))
        project_names_sel = _split_csv(request.query_params.get('project_name', ''))

        # 工厂筛选：将标准代码展开为所有变体（如 CJ → CJ, CC, Changchun）
        if companies_sel:
            expanded = set()
            for c in companies_sel:
                expanded.update(get_plant_raw_values(c))
            companies_sel = sorted(expanded)

        # 项目代号清洗条件：T/S 开头
        code_clean = (
            Q(project_code__startswith='T') | Q(project_code__startswith='S') |
            Q(project_code__startswith='t') | Q(project_code__startswith='s')
        )

        try:
            # 1. company 查询：仅当未传 company 时才查全部工厂列表
            if not companies_sel:
                raw_companies = ProjectAcquisition.objects.exclude(company='').values_list('company', flat=True).distinct()
                companies = sorted(set(normalize_plant(c) for c in raw_companies if normalize_plant(c)))
            else:
                companies = []

            # 2. lineNr 查询：传了 company 才需要查产线
            if companies_sel:
                qs = ProjectAcquisition.objects.filter(company__in=companies_sel).filter(code_clean).exclude(line_nr='')
                lines = sorted(set(qs.values_list('line_nr', flat=True)), key=_sort_key)
            else:
                lines = []

            # 3. projectCode + projectName 查询：传了 company 或 line 才需要查
            if companies_sel or lines_sel:
                qs = ProjectAcquisition.objects.filter(code_clean).exclude(project_code='')
                if companies_sel:
                    qs = qs.filter(company__in=companies_sel)
                if lines_sel:
                    qs = qs.filter(line_nr__in=lines_sel)
                proj_rows = list(qs.values('project_code', 'project_name').distinct().order_by('project_code'))
                project_codes = sorted(set(r['project_code'] for r in proj_rows if r['project_code']))
                projects = dedupe_project_options([
                    {'code': r['project_code'], 'name': r['project_name'] or ''}
                    for r in proj_rows
                    if r['project_code']
                ])
            else:
                project_codes = []
                projects = []

            # 4. projectName 查询：传了 project_code 才需要查项目名称
            if project_codes_sel:
                qs = ProjectAcquisition.objects.filter(project_code__in=project_codes_sel).exclude(project_name='')
                if companies_sel:
                    qs = qs.filter(company__in=companies_sel)
                if lines_sel:
                    qs = qs.filter(line_nr__in=lines_sel)
                project_names = sorted(set(qs.values_list('project_name', flat=True)))
            else:
                project_names = []

            # 5. stationNr 查询：传了 project_name 才需要查工位（从 RealCtExtract 查询）
            if project_names_sel:
                qs = RealCtExtract.objects.filter(code_clean).exclude(station_nr='')
                if companies_sel:
                    qs = qs.filter(company__in=companies_sel)
                if lines_sel:
                    qs = qs.filter(line_nr__in=lines_sel)
                if project_codes_sel:
                    qs = qs.filter(project_code__in=project_codes_sel)
                if project_names_sel:
                    qs = qs.filter(project_name__in=project_names_sel)
                station_nrs = sorted(set(qs.values_list('station_nr', flat=True)), key=_sort_key)
            else:
                station_nrs = []
        except Exception as e:
            return Response({'error': f'加载筛选器失败: {str(e)}'}, status=500)

        return Response({
            'companies': companies,
            'lines': lines,
            'project_codes': project_codes,
            'project_names': project_names,
            'station_nrs': station_nrs,
            'projects': projects,
        })


def dedupe_project_options(projects):
    """按项目编号去重，保留首个出现的项目名称。"""
    seen = set()
    results = []
    for item in projects or []:
        code = str(item.get('code') or '').strip() if isinstance(item, dict) else str(item or '').strip()
        if not code or code in seen:
            continue
        seen.add(code)
        if isinstance(item, dict):
            results.append({'code': code, 'name': str(item.get('name') or '').strip()})
        else:
            results.append({'code': code, 'name': ''})
    results.sort(key=lambda x: x['code'])
    return results


def _sort_key(name):
    """产线名称排序：字符串+数字按数字排序"""
    import re
    m = re.match(r'^([^\d]*?)(\d+)$', str(name))
    if m:
        return (m.group(1), int(m.group(2)))
    return (str(name), 0)


def _clean_ct_queryset(qs):
    """数据清洗：过滤无效数据
    1. 项目编号以 T 或 S 开头（排除 O 开头或无字母开头）
    2. project_code, project_name, line_nr, station_nr, cycle_time 非空非空字符串
    3. cycle_time 在 10s-1000s 以内
    """
    from django.db.models import Q

    # 项目编号以 T 或 S 开头
    qs = qs.filter(
        Q(project_code__istartswith='T') | Q(project_code__istartswith='S')
    )
    # 必填字段非空
    qs = qs.filter(
        project_code__isnull=False,
    ).exclude(
        project_code=''
    ).filter(
        project_name__isnull=False,
    ).exclude(
        project_name=''
    ).filter(
        line_nr__isnull=False,
    ).exclude(
        line_nr=''
    ).filter(
        station_nr__isnull=False,
    ).exclude(
        station_nr=''
    ).filter(
        cycle_time__isnull=False,
    )
    # CT 在 10s-1000s 以内
    qs = qs.filter(cycle_time__gte=10, cycle_time__lte=1000)
    return qs


class SctVsActView(APIView):
    """SCT vs ACT 对比列表：按工厂筛选（空=全部），返回所有项目+产线+工艺的对比"""

    def get(self, request):
        company = request.query_params.get('company', '').strip()

        # 1. 获取所有瓶颈工位 ACT 数据（最新记录）
        act_qs = BottleNeckCt.objects.filter(
            cycle_time_bottleneck__isnull=False
        )
        if company:
            # 支持标准代码匹配所有变体（如 CJ 匹配 CC）
            raw_values = get_plant_raw_values(company)
            act_qs = act_qs.filter(company__in=raw_values)

        # 按 project_code+line_nr 去重，取最新
        act_records = {}
        for r in act_qs.values('company', 'project_code', 'project_name', 'line_nr', 'cycle_time_bottleneck', 'update_time').order_by('-update_time'):
            key = (r['project_code'], r['line_nr'])
            if key not in act_records:
                act_records[key] = {
                    'company': normalize_plant(r['company']),
                    'project_code': r['project_code'],
                    'project_name': r['project_name'] or '',
                    'line_nr': r['line_nr'],
                    'act': float(r['cycle_time_bottleneck']),
                    'act_update_time': r['update_time'].isoformat() if r['update_time'] else None,
                }

        # 2. 获取所有 SCT 数据（BOL审批最新通过CT，按 project_code+line_nr+process）
        all_project_codes = list(set(v['project_code'] for v in act_records.values()))
        sct_qs = BolOverView.objects.filter(
            program_code__in=all_project_codes,
            final_approve_status='Approved',
            ct__isnull=False
        ).values('program_code', 'line_nr', 'process', 'ct', 'submit_date', 'bol_nr').order_by('-submit_date')

        sct_map = {}  # (project_code, line_nr, process) → sct_data
        for r in sct_qs:
            key = (r['program_code'], r['line_nr'], r['process'])
            if key not in sct_map:
                sct_map[key] = {
                    'sct': float(r['ct']),
                    'submit_date': r['submit_date'].isoformat() if r['submit_date'] else None,
                    'bol_nr': r['bol_nr'],
                }

        # 3. 组装列表：以 BottleNeckCt(ACT)为基准，匹配 BOL审批(SCT)
        items = []
        matched_act_keys = set()  # 追踪已匹配的 (project_code, line_nr)

        for (proj, line), act_data in act_records.items():
            act_val = act_data['act']
            has_match = False
            # 找到所有匹配的 process-SCT
            for (sct_proj, sct_line, process), sct_data in sct_map.items():
                if sct_proj == proj and sct_line == line:
                    has_match = True
                    matched_act_keys.add((proj, line))
                    gap = round(sct_data['sct'] - act_val, 2)
                    gap_pct = round(gap / sct_data['sct'] * 100, 2) if sct_data['sct'] > 0 else None
                    items.append({
                        'company': act_data['company'],
                        'project_code': proj,
                        'project_name': act_data['project_name'],
                        'line_nr': line,
                        'process': process,
                        'sct': sct_data['sct'],
                        'act': act_val,
                        'gap': gap,
                        'gap_pct': gap_pct,
                        'sct_submit_date': sct_data['submit_date'],
                        'act_update_time': act_data['act_update_time'],
                        'bol_nr': sct_data['bol_nr'],
                    })
            # 如果没有匹配的 SCT，也展示 ACT（SCT 为空）
            if not has_match:
                items.append({
                    'company': act_data['company'],
                    'project_code': proj,
                    'project_name': act_data['project_name'],
                    'line_nr': line,
                    'process': '-',
                    'sct': None,
                    'act': act_val,
                    'gap': None,
                    'gap_pct': None,
                    'sct_submit_date': None,
                    'act_update_time': act_data['act_update_time'],
                    'bol_nr': None,
                })

        # 按公司、产线、项目排序
        items.sort(key=lambda x: (x['company'] or '', _sort_key(x['line_nr']), x['project_code'] or '', x['process'] or ''))

        return Response({
            'company': normalize_plant(company) if company else '全部',
            'total': len(items),
            'items': items,
        })


class LineBalanceView(APIView):
    """Real Line Balance：基于 RealCtExtract 计算线平衡率

    IE 最佳实践：
        - 工位代表CT = P1-P99 百分位剔除 + Tukey IQR 双重过滤后的中位数
        - 线平衡率基于工位代表CT计算，抗离群点能力强于均值
    """

    def get(self, request):
        company = request.query_params.get('company', '').strip()
        line_nr = request.query_params.get('line_nr', '').strip()
        project_code = request.query_params.get('project_code', '').strip()

        if not all([company, line_nr, project_code]):
            return Response({'error': '请选择工厂、产线和项目编号'}, status=400)

        # 查询工位数据（清洗后）
        records = _clean_ct_queryset(RealCtExtract.objects.filter(
            company=company,
            line_nr=line_nr,
            project_code=project_code
        )).values('station_nr', 'cycle_time', 'count', 'update_time', 'project_name')

        # 按工位聚合
        station_data = defaultdict(list)
        for r in records:
            if r['cycle_time'] is not None and r['cycle_time'] > 0:
                station_data[r['station_nr']].append(float(r['cycle_time']))

        stations = []
        for sn, cts in sorted(station_data.items(), key=lambda x: _sort_key(x[0])):
            # IE 最佳实践：P1-P99 + IQR 双重剔除后取中位数作为工位代表CT
            rep = compute_represent_ct(cts)
            stations.append({
                'station_nr': sn,
                'avg_ct': rep['represent_ct'],  # 兼容字段：代表CT（中位数）
                'median_ct': rep['median'],
                'mean_ct': rep['mean'],
                'min_ct': rep['min'],
                'max_ct': rep['max'],
                'sample_count': rep['sample_count'],
                'kept_count': rep['kept_count'],
                'filtered_out': rep['filtered_out'],
                'p1': rep['p1'],
                'p99': rep['p99'],
                'iqr_lower': rep['iqr_lower'],
                'iqr_upper': rep['iqr_upper'],
            })

        if not stations:
            return Response({'error': '无数据'}, status=404)

        # 线平衡率 = sum(所有工位代表CT) / (工位数 × 最大瓶颈CT) × 100%
        bottleneck = max(stations, key=lambda x: x['avg_ct'])
        total_ct = sum(s['avg_ct'] for s in stations)
        station_count = len(stations)
        line_balance_rate = round(total_ct / (bottleneck['avg_ct'] * station_count) * 100, 2) if bottleneck['avg_ct'] > 0 else 0

        project_name = records[0]['project_name'] if records else ''

        return Response({
            'company': company,
            'line_nr': line_nr,
            'project_code': project_code,
            'project_name': project_name or '',
            'line_balance_rate': line_balance_rate,
            'station_count': station_count,
            'bottleneck_station': bottleneck['station_nr'],
            'bottleneck_ct': bottleneck['avg_ct'],
            'total_ct': round(total_ct, 2),
            'stations': stations,
        })


class BoxPlotView(APIView):
    """箱线图：基于 RealCtExtract，按工位计算 min/Q1/median/Q3/max"""

    def get(self, request):
        company = request.query_params.get('company', '').strip()
        line_nr = request.query_params.get('line_nr', '').strip()
        project_code = request.query_params.get('project_code', '').strip()

        if not all([company, line_nr, project_code]):
            return Response({'error': '请选择工厂、产线和项目编号'}, status=400)

        records = _clean_ct_queryset(RealCtExtract.objects.filter(
            company=company,
            line_nr=line_nr,
            project_code=project_code
        )).values('station_nr', 'cycle_time', 'project_name')

        station_data = defaultdict(list)
        for r in records:
            if r['cycle_time'] is not None and r['cycle_time'] > 0:
                station_data[r['station_nr']].append(float(r['cycle_time']))

        box_data = []
        for sn, cts in sorted(station_data.items(), key=lambda x: _sort_key(x[0])):
            cts_sorted = sorted(cts)
            n = len(cts_sorted)
            q1 = statistics.median(cts_sorted[:n // 2]) if n >= 2 else cts_sorted[0]
            q3 = statistics.median(cts_sorted[(n + 1) // 2:]) if n >= 2 else cts_sorted[0]
            box_data.append({
                'station_nr': sn,
                'min': round(min(cts), 2),
                'q1': round(q1, 2),
                'median': round(statistics.median(cts), 2),
                'q3': round(q3, 2),
                'max': round(max(cts), 2),
                'avg': round(sum(cts) / len(cts), 2),
                'sample_count': n,
            })

        project_name = records[0]['project_name'] if records else ''

        return Response({
            'company': company,
            'line_nr': line_nr,
            'project_code': project_code,
            'project_name': project_name or '',
            'box_data': box_data,
        })


class StationCtDetailView(APIView):
    """工位级工时分析：以指定时间范围数据绘制直方图和均值/极差图。

    时间范围参数：
        - date_range: 预设范围，3m（默认，近3月）/ 6m / 1y / 2y / all
        - start_date / end_date: 自定义日期（YYYY-MM-DD），优先级高于 date_range
    """

    # 预设范围映射（天数）
    RANGE_PRESETS = {
        '3m': 90,
        '6m': 180,
        '1y': 365,
        '2y': 730,
        'all': None,  # None 表示不限
    }

    def get(self, request):
        company = request.query_params.get('company', '').strip()
        line_nr = request.query_params.get('line_nr', '').strip()
        project_code = request.query_params.get('project_code', '').strip()
        station_nr = request.query_params.get('station_nr', '').strip()
        # 直方图分组宽度（秒）：5/10/20 等；不传或 auto 表示按 bin_count=10 均分
        bin_size_param = request.query_params.get('bin_size', '').strip().lower()

        # 时间范围解析
        date_range = request.query_params.get('date_range', '3m').strip().lower()
        custom_start = request.query_params.get('start_date', '').strip()
        custom_end = request.query_params.get('end_date', '').strip()

        if not all([company, line_nr, project_code, station_nr]):
            return Response({'error': '请选择工厂、产线、项目编号和工位'}, status=400)

        # 解析 bin_size
        bin_size = None
        if bin_size_param and bin_size_param not in ('auto', '0', ''):
            try:
                bin_size = float(bin_size_param)
                if bin_size <= 0:
                    bin_size = None
            except (TypeError, ValueError):
                bin_size = None

        company_values = []
        if company:
            company_values = sorted({c for c in get_plant_raw_values(company) if c})

        # 计算时间范围
        end_date = date.today()
        start_date = None
        if custom_start and custom_end:
            try:
                start_date = date.fromisoformat(custom_start)
                end_date = date.fromisoformat(custom_end)
            except ValueError:
                start_date = None
        elif custom_start:
            try:
                start_date = date.fromisoformat(custom_start)
            except ValueError:
                start_date = None
        elif custom_end:
            try:
                end_date = date.fromisoformat(custom_end)
            except ValueError:
                pass

        if start_date is None:
            days = self.RANGE_PRESETS.get(date_range, 90)
            if days is not None:
                start_date = end_date - timedelta(days=days)

        where_clauses = [OPE_CLEAN_WHERE]
        if company_values:
            where_clauses.append(f"company IN {_build_in_clause(company_values)}")
        where_clauses.extend([
            f"lineNr = {quote_sql_value(line_nr)}",
            f"projectCode = {quote_sql_value(project_code)}",
            f"stationNr = {quote_sql_value(station_nr)}",
        ])
        # 仅在非 all 模式下添加时间过滤
        if start_date is not None:
            where_clauses.append(f"[Update Date] >= {quote_sql_value(start_date)}")
        where_clauses.append(f"[Update Date] <= {quote_sql_value(end_date)}")
        query = (
            f"SELECT company, lineNr AS line_nr, projectCode AS project_code, "
            f"projectName AS project_name, stationNr AS station_nr, cycleTime AS cycle_time, "
            f"startTime AS start_time, [Update Date] AS update_time "
            f"FROM OPE.V_fact_cn_realTimeCT_overView WHERE {' AND '.join(where_clauses)} "
            f"ORDER BY [Update Date] DESC"
        )

        try:
            rows = execute_ope_query(query)
            # 计算实际月份跨度（用于分析函数）
            if start_date:
                months_span = max(1, round((end_date - start_date).days / 30))
            else:
                months_span = 12
            payload = build_station_ct_analysis([
                {
                    'cycle_time': row.get('cycle_time'),
                    'update_time': row.get('update_time'),
                    'start_time': row.get('start_time'),
                }
                for row in rows
            ], months=months_span, bin_size=bin_size)
            payload.update({
                'company': normalize_plant(company),
                'line_nr': line_nr,
                'project_code': project_code,
                'station_nr': station_nr,
                'project_name': rows[0].get('project_name') if rows else '',
                'period': {
                    'start_date': (start_date or date(2000, 1, 1)).isoformat(),
                    'end_date': end_date.isoformat(),
                    'date_range': date_range,
                    'months': months_span,
                    'sample_count': len(rows),
                },
            })
            return Response(payload)
        except Exception as e:
            return Response({'error': f'工位分析失败: {str(e)}'}, status=500)


class ActualCtSearchView(APIView):
    """Actual CT 检索：从数据仓库 OPE.V_fact_cn_realTimeCT_overView 查询

    数据清洗：项目代号 T/S 开头、字段非空、CT 10-1000s
    入参（均支持逗号分隔的多选值）：company, line_nr, project_code, project_name, station_nr, page, page_size
    返回：分页列表 + CT分布直方图
    """

    def get(self, request):
        companies_sel = _split_csv(request.query_params.get('company', ''))
        lines_sel = _split_csv(request.query_params.get('line_nr', ''))
        project_codes_sel = _split_csv(request.query_params.get('project_code', ''))
        project_names_sel = _split_csv(request.query_params.get('project_name', ''))
        station_nrs_sel = _split_csv(request.query_params.get('station_nr', ''))

        # 分页参数
        try:
            page = int(request.query_params.get('page', 1))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get('page_size', 50))
        except (TypeError, ValueError):
            page_size = 50
        page_size = min(max(page_size, 1), 200)
        page = max(page, 1)

        # 构建 WHERE 子句（数据清洗 + 筛选条件）
        where_clauses = [OPE_CLEAN_WHERE]
        # 工厂筛选：将标准代码展开为所有变体（如 CJ → CJ, CC, Changchun）
        if companies_sel:
            expanded_companies = set()
            for c in companies_sel:
                expanded_companies.update(get_plant_raw_values(c))
            companies_sel = sorted(expanded_companies)
        filter_map = [
            ('company', 'company', companies_sel),
            ('line_nr', 'lineNr', lines_sel),
            ('project_code', 'projectCode', project_codes_sel),
            ('project_name', 'projectName', project_names_sel),
            ('station_nr', 'stationNr', station_nrs_sel),
        ]
        for _, col, vals in filter_map:
            in_clause = _build_in_clause(vals)
            if in_clause:
                where_clauses.append(f"{col} IN {in_clause}")

        where_sql = ' AND '.join(where_clauses)

        # COUNT 查询
        count_sql = f"SELECT COUNT(*) AS cnt FROM OPE.V_fact_cn_realTimeCT_overView WHERE {where_sql}"

        # 直方图查询：获取所有 CT 值（不分页）
        hist_sql = (
            f"SELECT cycleTime FROM OPE.V_fact_cn_realTimeCT_overView WHERE {where_sql}"
        )

        # 分页数据查询
        offset = (page - 1) * page_size
        data_sql = (
            f"SELECT company, lineNr AS line_nr, projectCode AS project_code, "
            f"projectName AS project_name, stationNr AS station_nr, "
            f"cycleTime AS cycle_time, startTime AS start_time, "
            f"[Update Date] AS update_time "
            f"FROM OPE.V_fact_cn_realTimeCT_overView WHERE {where_sql} "
            f"ORDER BY [Update Date] DESC OFFSET {offset} ROWS FETCH NEXT {page_size} ROWS ONLY"
        )

        try:
            # 总数
            count_rows = execute_ope_query(count_sql)
            total = count_rows[0]['cnt'] if count_rows else 0

            # 直方图：取所有 CT 值，先做 IQR 异常剔除避免离群点拉宽值域
            hist_rows = execute_ope_query(hist_sql)
            ct_values = [float(r['cycleTime']) for r in hist_rows if r['cycleTime'] is not None]
            kept_ct_values, filtered_out, iqr_lower, iqr_upper = filter_outliers_iqr(ct_values)
            histogram = build_histogram(kept_ct_values, bin_count=20)
            histogram['filtered_out'] = filtered_out
            histogram['iqr_lower'] = round(iqr_lower, 2) if iqr_lower is not None else None
            histogram['iqr_upper'] = round(iqr_upper, 2) if iqr_upper is not None else None
            histogram['total'] = len(ct_values)

            # 分页数据
            data_rows = execute_ope_query(data_sql)
            results = []
            for r in data_rows:
                results.append({
                    'company': normalize_plant(str(r.get('company') or '').strip()),
                    'project_code': str(r.get('project_code') or '').strip(),
                    'project_name': str(r.get('project_name') or '').strip(),
                    'line_nr': str(r.get('line_nr') or '').strip(),
                    'station_nr': str(r.get('station_nr') or '').strip(),
                    'cycle_time': float(r['cycle_time']) if r.get('cycle_time') is not None else None,
                    'start_time': r['start_time'].isoformat() if r.get('start_time') else None,
                    'update_time': r['update_time'].isoformat() if r.get('update_time') else None,
                })
        except Exception as e:
            return Response({'error': f'检索失败: {str(e)}'}, status=500)

        return Response({
            'total': total,
            'page': page,
            'page_size': page_size,
            'results': results,
            'histogram': histogram,
        })


def _ym_shift(ym, delta_months):
    """年月字符串平移：'2026-08' 平移 -3 → '2026-05'"""
    y, m = ym.split('-')
    total = int(y) * 12 + (int(m) - 1) + delta_months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


class CtTrendTopView(APIView):
    """ACT CT 近3个月 同比/环比 上升/下降 TOP10（项目+产线粒度）

    数据源：BottleNeckCt 历史快照（每 project+line 每月取瓶颈CT中位数，抗离群）
    对比口径（3月均值 vs 3月均值）：
      - 近3个月 = 数据中最近3个有记录的自然月
      - 环比(MoM) = 近3个月均值 vs 其前3个自然月均值
      - 同比(YoY) = 近3个月均值 vs 去年同期3个月均值
      - 变化率 = (近3月均值 - 基期均值) / 基期均值 × 100
        正 = ACT CT 上升（恶化），负 = 下降（改善）
    任一窗口无数据则该方向不计算（无兜底）。
    GET /api/actual-ct/ct-trend-top/?top=N&company=CJ
    """

    def get(self, request):
        top_n = 10
        try:
            top_n = min(max(int(request.query_params.get('top', 10)), 1), 50)
        except (TypeError, ValueError):
            pass
        company = request.query_params.get('company', '').strip()

        qs = BottleNeckCt.objects.filter(
            cycle_time_bottleneck__isnull=False,
            update_time__isnull=False,
        )
        if company:
            qs = qs.filter(company__in=get_plant_raw_values(company))

        # 1) 聚合为 (project, line) → {年月: [CT...]}
        monthly_values = defaultdict(lambda: defaultdict(list))
        meta = {}
        for r in qs.values('company', 'project_code', 'project_name',
                           'line_nr', 'cycle_time_bottleneck', 'update_time').order_by('update_time'):
            key = (r['project_code'], r['line_nr'])
            ym = r['update_time'].strftime('%Y-%m')
            monthly_values[key][ym].append(float(r['cycle_time_bottleneck']))
            if key not in meta:
                meta[key] = {
                    'company': normalize_plant(r['company']),
                    'project_code': r['project_code'],
                    'project_name': r['project_name'] or '',
                    'line_nr': r['line_nr'],
                }

        if not monthly_values:
            return Response({'periods': None, 'mom': {'rise': [], 'drop': []},
                             'yoy': {'rise': [], 'drop': []}, 'stats': {}})

        # 2) 月度中位数：dict[(proj,line)] → {ym: median_ct}
        monthly_median = {}
        for key, by_month in monthly_values.items():
            monthly_median[key] = {ym: statistics.median(v) for ym, v in by_month.items()}

        # 3) 确定三个时间窗口（按全库最近3个有数据的自然月）
        all_months = sorted({ym for by_month in monthly_values.values() for ym in by_month})
        recent3 = all_months[-3:]
        first_recent = recent3[0]
        prev3 = [_ym_shift(first_recent, -i) for i in (3, 2, 1)]      # 连续前3个自然月
        yoy3 = [_ym_shift(m, -12) for m in recent3]                    # 去年同期3个月

        def _window_avg(medians, months):
            vals = [medians[ym] for ym in months if ym in medians]
            if not vals:
                return None, 0
            return sum(vals) / len(vals), len(vals)

        # 4) 逐 project+line 计算环比/同比变化率
        mom_rows, yoy_rows = [], []
        for key, medians in monthly_median.items():
            m = meta[key]
            recent_avg, recent_n = _window_avg(medians, recent3)
            if recent_avg is None:
                continue
            base_avg, base_n = _window_avg(medians, prev3)
            if base_avg and base_avg > 0:
                mom_rows.append({
                    **m,
                    'recent_avg': round(recent_avg, 2),
                    'base_avg': round(base_avg, 2),
                    'recent_months': recent_n,
                    'base_months': base_n,
                    'change_pct': round((recent_avg - base_avg) / base_avg * 100, 1),
                })
            yoy_avg, yoy_n = _window_avg(medians, yoy3)
            if yoy_avg and yoy_avg > 0:
                yoy_rows.append({
                    **m,
                    'recent_avg': round(recent_avg, 2),
                    'base_avg': round(yoy_avg, 2),
                    'recent_months': recent_n,
                    'base_months': yoy_n,
                    'change_pct': round((recent_avg - yoy_avg) / yoy_avg * 100, 1),
                })

        def _tops(rows):
            rise = sorted([r for r in rows if r['change_pct'] > 0],
                          key=lambda x: -x['change_pct'])[:top_n]
            drop = sorted([r for r in rows if r['change_pct'] < 0],
                          key=lambda x: x['change_pct'])[:top_n]
            return rise, drop

        mom_rise, mom_drop = _tops(mom_rows)
        yoy_rise, yoy_drop = _tops(yoy_rows)

        return Response({
            'periods': {'recent': recent3, 'prev': prev3, 'yoy': yoy3},
            'mom': {'rise': mom_rise, 'drop': mom_drop},
            'yoy': {'rise': yoy_rise, 'drop': yoy_drop},
            'stats': {
                'tracked': len(monthly_median),
                'mom_computed': len(mom_rows),
                'yoy_computed': len(yoy_rows),
            },
        })


class ActStdDeviationView(APIView):
    """ACT vs Std BOL 偏差清单：|(ACT - Std) / Std| > 阈值（默认10%）

    ACT = BottleNeckCt 每 project+line 最新瓶颈CT
    Std = BOL审批(Approved) 每 project+line+process 最新 CT
    偏差% = (ACT - Std) / Std × 100，正 = ACT 偏高（实际慢于标准），负 = 偏低
    GET /api/actual-ct/act-std-deviation/?threshold=10&company=CJ
    """

    def get(self, request):
        threshold = 10.0
        try:
            threshold = abs(float(request.query_params.get('threshold', 10)))
        except (TypeError, ValueError):
            pass
        company = request.query_params.get('company', '').strip()

        # 1) ACT：每 project+line 取最新
        # 项目键用「数字+后缀」识别（O6248/T6248 同一项目），避免前缀差异漏匹配
        from apps.dynamic_bol.views import _extract_project_key
        act_qs = BottleNeckCt.objects.filter(cycle_time_bottleneck__isnull=False)
        if company:
            act_qs = act_qs.filter(company__in=get_plant_raw_values(company))
        act_map = {}
        for r in act_qs.values('company', 'project_code', 'project_name', 'line_nr',
                               'cycle_time_bottleneck', 'update_time').order_by('-update_time'):
            pkey = _extract_project_key(r['project_code']) or r['project_code']
            key = (pkey, r['line_nr'])
            if key not in act_map:
                act_map[key] = {
                    'company': normalize_plant(r['company']),
                    'project_code': r['project_code'],
                    'project_name': r['project_name'] or '',
                    'line_nr': r['line_nr'],
                    'act': float(r['cycle_time_bottleneck']),
                    'act_update_time': r['update_time'].isoformat() if r['update_time'] else None,
                }

        # 2) Std：Approved 最新 CT（project+line+process），按项目键索引
        std_map = {}
        for r in BolOverView.objects.filter(
            final_approve_status='Approved',
            ct__isnull=False,
        ).values('program_code', 'line_nr', 'process', 'ct', 'submit_date', 'bol_nr').order_by('-submit_date'):
            pkey = _extract_project_key(r['program_code']) or r['program_code']
            std_map.setdefault((pkey, r['line_nr']), []).append({
                'process': r['process'],
                'std': float(r['ct']),
                'submit_date': r['submit_date'].isoformat() if r['submit_date'] else None,
                'bol_nr': r['bol_nr'],
            })

        # 3) 匹配并计算偏差（按 (项目键, 产线) 索引查找）
        items = []
        matched = 0
        for (pkey, line), act in act_map.items():
            for std in std_map.get((pkey, line), []):
                if std['std'] is None or std['std'] <= 0:
                    continue
                matched += 1
                deviation = act['act'] - std['std']
                dev_pct = deviation / std['std'] * 100
                if abs(dev_pct) <= threshold:
                    continue
                items.append({
                    'company': act['company'],
                    'project_code': act['project_code'],
                    'project_name': act['project_name'],
                    'line_nr': line,
                    'process': std['process'],
                    'std': round(std['std'], 2),
                    'act': round(act['act'], 2),
                    'deviation': round(deviation, 2),
                    'deviation_pct': round(dev_pct, 1),
                    'submit_date': std['submit_date'],
                    'act_update_time': act['act_update_time'],
                    'bol_nr': std['bol_nr'],
                })

        items.sort(key=lambda x: -abs(x['deviation_pct']))

        return Response({
            'threshold': threshold,
            'stats': {
                'matched': matched,
                'over_count': len(items),
                'above_count': sum(1 for i in items if i['deviation_pct'] > 0),
                'below_count': sum(1 for i in items if i['deviation_pct'] < 0),
            },
            'items': items,
        })


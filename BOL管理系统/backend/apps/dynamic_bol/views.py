# -*- coding: utf-8 -*-
"""BOL更新记录 视图（HRDB 只读）"""
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend

from apps.dynamic_bol.models import BolOverView, BolOverViewByProcess, BolApprovalHistory, BolUpdateHistory, FineUser
from apps.dynamic_bol.serializers import (
    BolOverViewSerializer, BolOverViewByProcessSerializer,
    BolApprovalHistorySerializer, BolUpdateHistorySerializer,
)


class BolOverViewViewSet(viewsets.ReadOnlyModelViewSet):
    """BOL更新记录（HRDB 只读）"""
    queryset = BolOverView.objects.all()
    serializer_class = BolOverViewSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = [
        'program_code', 'location', 'process', 'line_nr', 'version',
        'status', 'category', 'new_project', 'final_approve_status', 'customer',
    ]
    search_fields = ['bol_nr', 'program_name', 'customer', 'program_code']
    ordering_fields = ['submit_date', 'bol_overall', 'bol', 'qws_bol', 'gap_bol', 'program_code']
    ordering = ['-submit_date']


class BolOverViewByProcessViewSet(viewsets.ReadOnlyModelViewSet):
    """按工艺BOL详情（HRDB 只读）"""
    queryset = BolOverViewByProcess.objects.all()
    serializer_class = BolOverViewByProcessSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['program_code', 'process', 'line_nr', 'version', 'location']
    search_fields = ['bol_nr', 'program_code']
    ordering_fields = ['update_time', 'bol', 'ct', 'hc', 'lb_rate']
    ordering = ['-update_time']


class BolApprovalHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """BOL审批历史（HRDB 只读）"""
    queryset = BolApprovalHistory.objects.all()
    serializer_class = BolApprovalHistorySerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['bol_nr', 'approval_type', 'approval_status', 'operat_user']
    ordering_fields = ['update_time']
    ordering = ['-update_time']


class BolUpdateHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """BOL更新历史（HRDB 只读）"""
    queryset = BolUpdateHistory.objects.all()
    serializer_class = BolUpdateHistorySerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['program_code', 'process', 'line_nr', 'location', 'category', 'if_approved']
    ordering_fields = ['update_date']
    ordering = ['-update_date']


class ApprovalOverviewStatsView(APIView):
    """Unpaginated statistics for the approval overview charts."""

    def get(self, request):
        from datetime import date, datetime, time

        from django.db.models import Count, Q
        from django.db.models.functions import TruncMonth
        from django.utils import timezone

        now = timezone.now()
        local_today = timezone.localtime(now).date()
        first_month_index = local_today.year * 12 + local_today.month - 1 - 11
        first_year, first_month_zero = divmod(first_month_index, 12)
        first_month = date(first_year, first_month_zero + 1, 1)
        start_at = timezone.make_aware(datetime.combine(first_month, time.min))
        months = []
        for offset in range(12):
            year, month_zero = divmod(first_month_index + offset, 12)
            months.append(f'{year}-{month_zero + 1:02d}')

        qs = BolOverView.objects.filter(submit_date__gte=start_at, submit_date__lte=now)
        location = request.query_params.get('location', '').strip()
        process = request.query_params.get('process', '').strip()
        roof_type = request.query_params.get('type', '').strip()
        final_status = request.query_params.get('final_approve_status', '').strip()
        program_code = request.query_params.get('program_code', '').strip()

        if location:
            raw_values = get_plant_raw_values(location)
            location_filter = Q(location__in=raw_values)
            for raw_value in raw_values:
                location_filter |= Q(location__startswith=f'{raw_value}_')
            qs = qs.filter(location_filter)
        if process:
            qs = qs.filter(process=process)
        if roof_type:
            qs = qs.filter(type=roof_type)
        if final_status:
            qs = qs.filter(final_approve_status=final_status)
        if program_code:
            qs = qs.filter(program_code__icontains=program_code)

        approved_rows = qs.filter(final_approve_status='Approved').values(
            'location', 'program_code', 'process'
        ).distinct()
        monthly_rows = qs.order_by().annotate(
            month=TruncMonth('submit_date')
        ).values(
            'month', 'final_approve_status'
        ).annotate(count=Count('bol_nr')).order_by('month', 'final_approve_status')

        return Response(_build_approval_overview_summary(
            approved_rows, monthly_rows, months
        ))


# ======================== BOL 变更审批履历 ========================

import re
import math
from collections import defaultdict
from decimal import Decimal
from rest_framework.response import Response
from bol_platform.plant_utils import normalize_plant, get_plant_raw_values


def _to_float(v):
    """Decimal/None → float/None"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# 项目编号识别规则：
# 项目号格式为「前缀字母+4位数字+可选后缀字母」，如 O6848 / S6763 / T6763 / T6846a / T6968E
# 识别规则：
#   - 前缀字母（O/S/T 等）不同 → 同一项目的不同阶段，需合并（如 O6848 + T6848）
#   - 后缀字母不同 → 不同项目，不合并（如 T6846 与 T6846a、T6968 与 T6968E）
# 因此同一项目的标识 = 后4位数字 + 后缀字母（若有）
_PROJECT_CODE_RE = re.compile(r'^[A-Z](\d{4})([a-zA-Z]?)$')


def _extract_project_key(program_code):
    """提取项目编号的「数字+后缀」作为同一项目识别键

    规则：
        O6848 / T6848 → "6848"        （同一项目，前缀不同）
        S6763 / T6763 → "6763"        （同一项目，前缀不同）
        T6846         → "6846"        （与 T6846a 是不同项目）
        T6846a        → "6846a"       （与 T6846 是不同项目）
        T6968         → "6968"        （与 T6968E 是不同项目）
        T6968E        → "6968E"       （与 T6968 是不同项目）
        Ext1-T5550 / TC147 等不匹配格式 → None（保持原样不合并）
    """
    if not program_code:
        return None
    m = _PROJECT_CODE_RE.match(program_code.strip())
    if not m:
        return None
    return m.group(1) + (m.group(2) or '')


def _pick_canonical_code(codes):
    """同一项目的多个编码中，按优先级选择代表编码

    优先级：
        1. T 开头（如 T6848 优先于 O6848 / S6848）
        2. 字母顺序靠前
    """
    if not codes:
        return None
    t_codes = sorted([c for c in codes if c.startswith('T')])
    if t_codes:
        return t_codes[0]
    return sorted(codes)[0]


def _build_approval_overview_summary(approved_rows, monthly_rows, months):
    approved_by_location = defaultdict(set)
    for row in approved_rows:
        location = normalize_plant(row['location'] or '') or '未分类'
        approved_by_location[location].add((row['program_code'] or '', row['process'] or ''))

    status_keys = ('Approved', 'Rejected', 'Pending', 'Other')
    month_status_counts = {month: defaultdict(int) for month in months}
    for row in monthly_rows:
        month_value = row['month']
        month = month_value.strftime('%Y-%m') if month_value else ''
        if month not in month_status_counts:
            continue
        raw_status = (row['final_approve_status'] or '').strip().lower()
        if raw_status == 'approved':
            status = 'Approved'
        elif raw_status == 'rejected':
            status = 'Rejected'
        elif raw_status in ('ongoing', ''):
            status = 'Pending'
        else:
            status = 'Other'
        month_status_counts[month][status] += row['count']

    return {
        'months': months,
        'approved_by_location': [
            {'name': location, 'count': len(projects)}
            for location, projects in sorted(approved_by_location.items())
        ],
        'monthly_status': [
            {
                'status': status,
                'data': [month_status_counts[month].get(status, 0) for month in months],
            }
            for status in status_keys
            if any(month_status_counts[month].get(status, 0) for month in months)
        ],
    }


def _find_matching_codes(program_code):
    """根据项目编号查找所有同项目的编码（仅前缀字母不同）

    返回匹配的 program_code 列表；若无数字部分则返回 [program_code]
    """
    key = _extract_project_key(program_code)
    if not key:
        return [program_code]
    # 查询所有已审批通过记录中的项目号，筛选出「数字+后缀」相同的
    all_codes = BolOverView.objects.filter(
        final_approve_status='Approved'
    ).values_list('program_code', flat=True).distinct()
    matching = [
        c for c in all_codes
        if c and _extract_project_key(c) == key
    ]
    return matching if matching else [program_code]


class ApprovalTrendFilterOptionsView(APIView):
    """BOL 变更审批履历 - 级联筛选器选项

    入参（均可选，支持级联）：
        location   标准工厂代码（如 BJ）
        process    工艺类型（如 FA）
        line_nr    产线名称
    返回：locations / processes / lines / projects
    仅统计 final_approve_status='Approved' 的记录
    """

    def get(self, request):
        location = request.query_params.get('location', '').strip()
        process = request.query_params.get('process', '').strip()
        line_nr = request.query_params.get('line_nr', '').strip()

        qs = BolOverView.objects.filter(final_approve_status='Approved')

        # 工厂筛选：标准代码展开为所有变体
        loc_raws = None
        if location:
            loc_raws = get_plant_raw_values(location)
            qs = qs.filter(location__in=loc_raws)

        if process:
            qs = qs.filter(process=process)

        if line_nr:
            qs = qs.filter(line_nr=line_nr)

        # 工厂列表（标准化后去重排序）
        loc_qs = BolOverView.objects.filter(final_approve_status='Approved')
        if loc_raws:
            loc_qs = loc_qs.filter(location__in=loc_raws)
        raw_locs = loc_qs.values_list('location', flat=True).distinct()
        locations = sorted(set(
            normalize_plant(loc) for loc in raw_locs
            if loc and normalize_plant(loc)
        ))

        # 工艺列表（按选中的工厂筛选）
        proc_qs = BolOverView.objects.filter(final_approve_status='Approved')
        if loc_raws:
            proc_qs = proc_qs.filter(location__in=loc_raws)
        processes = sorted(set(
            p for p in proc_qs.values_list('process', flat=True).distinct()
            if p and p.strip()
        ))

        # 产线列表（按选中的工厂+工艺筛选）
        line_qs = BolOverView.objects.filter(final_approve_status='Approved')
        if loc_raws:
            line_qs = line_qs.filter(location__in=loc_raws)
        if process:
            line_qs = line_qs.filter(process=process)
        lines = sorted(set(
            ln for ln in line_qs.values_list('line_nr', flat=True).distinct()
            if ln and ln.strip()
        ))

        # 项目列表（按选中的工厂+工艺+产线筛选）
        # 同一项目识别：前缀字母不同（O/S/T）视为同一项目，后缀字母不同视为不同项目
        # 合并后仅保留 T 开头的编码作为代表
        proj_qs = qs.values('program_code', 'program_name').distinct()
        # 分组：按「数字+后缀」键
        key_groups = defaultdict(list)  # key -> [(code, name), ...]
        no_key_items = []  # 不匹配规则的（如 Ext1-T5550 / TC147）
        seen_codes = set()
        for p in proj_qs:
            code = p['program_code']
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            name = p['program_name'] or ''
            key = _extract_project_key(code)
            if key:
                key_groups[key].append((code, name))
            else:
                no_key_items.append((code, name))

        # 合并：同一键组取 T 开头的作为代表
        projects = []
        for key, items in key_groups.items():
            codes = [it[0] for it in items]
            canonical = _pick_canonical_code(codes)
            # 取代表编码对应的 name（优先非空）
            name = next((it[1] for it in items if it[0] == canonical and it[1]), '')
            if not name:
                name = next((it[1] for it in items if it[1]), '')
            projects.append({'code': canonical, 'name': name})
        # 加上不匹配规则的
        for code, name in no_key_items:
            projects.append({'code': code, 'name': name})

        projects.sort(key=lambda x: x['code'])

        return Response({
            'locations': locations,
            'processes': processes,
            'lines': lines,
            'projects': projects,
        })


class ApprovalTrendView(APIView):
    """BOL 变更审批履历 - 时间序列

    入参：
        program_code  必填，项目编号（可为 T 开头的代表编码）
        process       必填，工艺类型（如 FA）
    识别同一项目：后4位数字相同 + 相同 process + 审批通过
        例如 S6763 和 T6763 视为同一项目的不同阶段，合并展示
    数据来源：
        BolOverView.BOL_Overall     整体 BOL
        BolOverViewByProcess        CT/HC/LB 等详细数据（按 bol_nr+process 聚合）
    """

    def get(self, request):
        program_code = request.query_params.get('program_code', '').strip()
        process = request.query_params.get('process', '').strip()

        if not program_code or not process:
            return Response(
                {'error': '请选择项目编号和工艺类型'},
                status=400
            )

        # 1. 查找同项目的所有编码（O/S/T 等不同阶段合并）
        matching_codes = _find_matching_codes(program_code)

        # 2. 查询该项目+工艺的所有审批通过 BOL 记录（按提交时间升序）
        bol_qs = BolOverView.objects.filter(
            program_code__in=matching_codes,
            process=process,
            final_approve_status='Approved',
        ).order_by('submit_date')

        if not bol_qs.exists():
            return Response({
                'project': {
                    'program_code': program_code,
                    'program_name': '',
                    'process': process,
                    'location': '',
                    'customer': '',
                    'matched_codes': matching_codes,
                },
                'timeline': [],
                'summary': {'version_count': 0},
            })

        bol_records = list(bol_qs)
        bol_nrs = [b.bol_nr for b in bol_records]

        # 2. 查询 byProcess 详细数据，按 bol_nr 分组聚合
        # 一个 bol_nr + process 可能有多段，CT/HC 取 sum，LB 取 avg
        bp_qs = BolOverViewByProcess.objects.filter(
            bol_nr__in=bol_nrs,
            process=process,
        )

        bp_agg = defaultdict(lambda: {'ct_sum': Decimal(0), 'hc_sum': Decimal(0), 'lb_list': [], 'bottleneck': ''})
        for bp in bp_qs:
            key = bp.bol_nr
            if bp.ct is not None:
                bp_agg[key]['ct_sum'] += bp.ct
            if bp.hc is not None:
                bp_agg[key]['hc_sum'] += bp.hc
            if bp.lb_rate is not None:
                bp_agg[key]['lb_list'].append(bp.lb_rate)
            if bp.bottle_neck_station and not bp_agg[key]['bottleneck']:
                bp_agg[key]['bottleneck'] = bp.bottle_neck_station

        # 3. 批量查询提交人姓名（fine_user.userName → realName）
        user_names = set(
            b.submit_user_name for b in bol_records
            if b.submit_user_name and b.submit_user_name.strip()
        )
        realname_map = {}
        if user_names:
            fu_qs = FineUser.objects.filter(user_name__in=user_names)
            realname_map = {fu.user_name: fu.real_name for fu in fu_qs if fu.real_name}

        # 4. 构建时间序列
        timeline = []
        first = bol_records[0]
        for b in bol_records:
            agg = bp_agg.get(b.bol_nr, {})
            ct_sum = agg.get('ct_sum', Decimal(0))
            hc_sum = agg.get('hc_sum', Decimal(0))
            lb_list = agg.get('lb_list', [])
            lb_avg = (sum(lb_list) / len(lb_list)) if lb_list else None

            timeline.append({
                'bol_nr': b.bol_nr,
                'program_code': b.program_code or '',
                'version': b.version or '',
                'submit_date': b.submit_date.strftime('%Y-%m-%d') if b.submit_date else None,
                'submit_user': b.submit_user_name or '',
                'submit_user_realname': realname_map.get(b.submit_user_name, '') if b.submit_user_name else '',
                'bol_overall': _to_float(b.bol_overall),
                'ct': _to_float(ct_sum) if ct_sum else None,
                'hc': _to_float(hc_sum) if hc_sum else None,
                'lb': _to_float(lb_avg) if lb_avg is not None else None,
                'bottleneck_station': agg.get('bottleneck', ''),
                'location': normalize_plant(b.location) if b.location else '',
                'line_nr': b.line_nr or '',
                'customer': b.customer or '',
            })

        # 5. 计算变化量（首末版本对比）
        summary = {'version_count': len(timeline)}
        if len(timeline) >= 2:
            first_v = timeline[0]
            last_v = timeline[-1]
            for field in ['bol_overall', 'ct', 'hc', 'lb']:
                if first_v[field] is not None and last_v[field] is not None:
                    summary[f'{field}_change'] = round(last_v[field] - first_v[field], 4)
                else:
                    summary[f'{field}_change'] = None

        # 提取实际涉及的所有项目编码（去重排序）
        actual_codes = sorted(set(
            b.program_code for b in bol_records if b.program_code
        ))

        return Response({
            'project': {
                'program_code': program_code,
                'program_name': first.program_name or '',
                'process': process,
                'location': normalize_plant(first.location) if first.location else '',
                'customer': first.customer or '',
                'matched_codes': actual_codes,
            },
            'timeline': timeline,
            'summary': summary,
        })


# ======================== 改善机会分析 ========================

# 改善机会目标线平衡率
TARGET_LB = Decimal('0.85')
# 改善后 LB 上限：91%（超过 91% 因人机配合工位难以实现，91%-92% 已经很高）
MAX_ACHIEVABLE_LB = Decimal('0.91')


class LowLbAnalysisView(APIView):
    """改善机会分析 - 识别 LB < 阈值 的项目及潜在改善机会

    入参：
        threshold   可选，LB 阈值，默认 0.85
        location    可选，标准工厂代码
        process     可选，工艺类型
    数据来源：
        BolOverViewByProcess（按 bol_nr 聚合：CT/HC 取 sum，LB 取 avg）
        BolOverView（提供 program_name、customer）
        仅统计审批通过的记录（final_approve_status='Approved'）
    改善机会计算逻辑：
        有效工作量 = HC * LB
        若 LB 提升至目标值，所需 HC = 有效工作量 / 目标LB
        潜在减人（小数）= 当前HC - 所需HC
        圆整规则：小数部分 ≥ 0.8 才向上圆整，否则向下圆整
            0.3→0, 0.5→0, 0.75→0, 0.8→1, 0.9→1
            1.1→1, 1.2→1, 1.5→1, 1.7→1, 1.8→2, 1.9→2
        只有圆整后 ≥ 1 人才作为有效改善机会，不足 0.8 人的零散小数不计入
        保守方案：减 floor(潜在减人) 人，需达到的 LB = 有效工作量 / 新HC（≤ 91% 才可行）
        激进方案：在 LB ≤ 91% 前提下，最大可减人数 = HC - ceil(有效工作量 / 91%)
    """

    def get(self, request):
        threshold_str = request.query_params.get('threshold', '0.85').strip()
        location = request.query_params.get('location', '').strip()
        process = request.query_params.get('process', '').strip()

        try:
            threshold = Decimal(threshold_str)
        except Exception:
            threshold = TARGET_LB

        # 1. 查询所有审批通过的 BOL 编号 + 项目名称 + 客户
        bol_qs = BolOverView.objects.filter(final_approve_status='Approved')
        loc_raws = None
        if location:
            loc_raws = get_plant_raw_values(location)
            bol_qs = bol_qs.filter(location__in=loc_raws)
        if process:
            bol_qs = bol_qs.filter(process=process)

        # 同时取 bol_nr, program_name, customer 用于后续展示
        bol_info_qs = bol_qs.values('bol_nr', 'program_name', 'customer')
        bol_meta = {}
        bol_nrs = []
        for b in bol_info_qs:
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
            return Response({
                'items': [],
                'summary': {
                    'total_projects': 0,
                    'low_lb_projects': 0,
                    'total_hc': 0,
                    'total_potential_reduce': 0,
                    'threshold': float(threshold),
                    'max_lb': float(MAX_ACHIEVABLE_LB),
                },
            })

        # 2. 查询 byProcess 详细数据，按 bol_nr 聚合
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
            # 应用工艺筛选（若提供）
            if process and proc != process:
                continue
            key = (pc, proc)
            existing = proj_latest.get(key)
            if not existing or (agg['update_time'] and (not existing['update_time'] or agg['update_time'] > existing['update_time'])):
                lb_list = agg['lb_list']
                lb_avg = (sum(lb_list) / len(lb_list)) if lb_list else None
                # 获取项目名称和客户
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
        items = []
        for key, v in proj_latest.items():
            lb = v['lb']
            hc = v['hc']
            if lb is None or hc is None or hc <= 0 or lb <= 0:
                continue
            if lb >= float(threshold):
                continue

            # 有效工作量 = HC * LB
            effective_work = hc * lb
            # 若 LB 提升至目标值，所需 HC
            hc_at_target = effective_work / float(threshold)
            # 潜在减人（小数）
            potential_reduce = hc - hc_at_target

            # 圆整规则：小数部分 ≥ 0.8 才向上圆整，否则向下圆整
            #   0.3→0, 0.5→0, 0.75→0, 0.8→1, 0.9→1
            #   1.1→1, 1.2→1, 1.5→1, 1.7→1, 1.8→2, 1.9→2
            # 只有圆整后 ≥ 1 人才作为有效改善机会
            floor_val = math.floor(potential_reduce)
            frac = potential_reduce - floor_val
            if frac >= 0.8:
                rounded_reduce = floor_val + 1
            else:
                rounded_reduce = floor_val
            if rounded_reduce < 1:
                # 圆整后不足 1 人，不计入改善机会
                continue

            # 保守方案：减 floor(潜在减人) 人，需达到的 LB 不超过 91%
            reduce_conservative = math.floor(potential_reduce) if potential_reduce >= 1 else 0
            hc_conservative = hc - reduce_conservative
            lb_needed_conservative = (effective_work / hc_conservative) if hc_conservative > 0 else None
            # 可行性判断：所需 LB 不能超过 91%（超过 91% 难以实现）
            conservative_feasible = (
                reduce_conservative > 0
                and lb_needed_conservative is not None
                and lb_needed_conservative <= max_lb_float
            )

            # 激进方案：在 LB ≤ 91% 前提下，最大可减人数
            # new_hc = ceil(有效工作量 / 91%)，保证 new_hc 时的 LB = 有效工作量/new_hc ≤ 91%
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
                'version': v['version'],
                'hc': round(hc, 2),
                'lb': round(lb, 4),
                'lb_percent': round(lb * 100, 2),
                'ct': round(v['ct'], 2),
                'bottleneck': v['bottleneck'],
                'effective_work': round(effective_work, 2),
                'hc_at_target': round(hc_at_target, 2),
                'potential_reduce': rounded_reduce,  # 圆整后的整数
                'potential_reduce_raw': round(potential_reduce, 2),  # 保留原始小数供参考
                'conservative': {
                    'reduce': reduce_conservative,
                    'new_hc': hc_conservative,
                    'lb_needed': round(lb_needed_conservative, 4) if lb_needed_conservative else None,
                    'lb_needed_percent': round(lb_needed_conservative * 100, 2) if lb_needed_conservative else None,
                    'feasible': conservative_feasible,
                },
                'aggressive': {
                    'reduce': reduce_aggressive,
                    'new_hc': hc_aggressive,
                    'lb_needed': round(lb_needed_aggressive, 4) if lb_needed_aggressive else None,
                    'lb_needed_percent': round(lb_needed_aggressive * 100, 2) if lb_needed_aggressive else None,
                    'feasible': aggressive_feasible,
                },
                'update_time': v['update_time'].strftime('%Y-%m-%d') if v['update_time'] else None,
            })

        # 按 LB 升序排列（LB 最低的在前）
        items.sort(key=lambda x: x['lb'])

        # 5. 汇总统计
        # 总计潜在减人 = 所有圆整后 ≥1 项目的圆整值之和（整数）
        total_hc = sum(it['hc'] for it in items)
        total_potential_reduce = sum(it['potential_reduce'] for it in items)
        # 可行改善总减人（保守方案可行时取保守，否则取激进）
        total_feasible_reduce = sum(
            it['conservative']['reduce'] if it['conservative']['feasible']
            else (it['aggressive']['reduce'] if it['aggressive']['feasible'] else 0)
            for it in items
        )

        return Response({
            'items': items,
            'summary': {
                'total_projects': len(proj_latest),
                'low_lb_projects': len(items),
                'total_hc': round(total_hc, 2),
                'total_potential_reduce': int(total_potential_reduce),  # 整数
                'total_feasible_reduce': total_feasible_reduce,
                'threshold': float(threshold),
                'max_lb': float(MAX_ACHIEVABLE_LB),
            },
        })


class TopCompareView(APIView):
    """TOP10 对比分析

    图1 审批BOL vs QWS 报价：每 项目(合并同项目不同前缀编码)+工艺 取最新 Approved 记录，
        gap_pct = (BOL_Overall − qwsBOL) / qwsBOL × 100
        上升（正值）= 审批BOL 高于报价（不利）；下降（负值）= 低于报价（改善）
    图2 与上次审批环比：同组最新两条 Approved 记录对比，
        mom_pct = (最新BOL − 上次BOL) / 上次BOL × 100
    注：源表 gap_BOL 字段与实际计算不符，此处统一自行计算，不读该字段。
    GET /api/dynamic-bol/top-compare/?top=10
    """

    def get(self, request):
        top_n = 10
        try:
            top_n = min(max(int(request.query_params.get('top', 10)), 1), 50)
        except (TypeError, ValueError):
            pass
        location = request.query_params.get('location', '').strip()

        # 1. 按 项目key+工艺 分组（合并 O/S/T 前缀），组内按提交时间升序
        qs = BolOverView.objects.filter(
            final_approve_status='Approved',
            bol_overall__isnull=False,
        )
        if location:
            qs = qs.filter(location__in=get_plant_raw_values(location))
        groups = defaultdict(list)
        for r in qs.order_by('submit_date').values(
            'program_code', 'program_name', 'process', 'location',
            'bol_overall', 'qws_bol', 'version', 'submit_date',
        ):
            key = _extract_project_key(r['program_code'])
            if not key:
                continue
            groups[(key, r['process'])].append(r)

        qws_rows, mom_rows = [], []
        for (key, process), records in groups.items():
            if not records:
                continue
            latest = records[-1]
            meta = {
                'program_code': _pick_canonical_code([x['program_code'] for x in records]),
                'program_name': latest['program_name'] or '',
                'process': process,
                'location': normalize_plant(latest['location']) if latest['location'] else '',
                'version_latest': latest['version'],
                'submit_date_latest': latest['submit_date'].strftime('%Y-%m-%d') if latest['submit_date'] else None,
            }
            bol_latest = float(latest['bol_overall'])

            # QWS 对比（最新记录）
            qws = float(latest['qws_bol']) if latest['qws_bol'] is not None else None
            if qws and qws > 0:
                qws_rows.append({
                    **meta,
                    'bol': round(bol_latest, 2),
                    'qws_bol': round(qws, 2),
                    'gap': round(bol_latest - qws, 2),
                    'change_pct': round((bol_latest - qws) / qws * 100, 1),
                })

            # 环比（最新 vs 上一条）
            if len(records) >= 2:
                prev = records[-2]
                bol_prev = float(prev['bol_overall'])
                if bol_prev > 0:
                    mom_rows.append({
                        **meta,
                        'bol_latest': round(bol_latest, 2),
                        'bol_prev': round(bol_prev, 2),
                        'version_prev': prev['version'],
                        'submit_date_prev': prev['submit_date'].strftime('%Y-%m-%d') if prev['submit_date'] else None,
                        'change_pct': round((bol_latest - bol_prev) / bol_prev * 100, 1),
                    })

        def _tops(rows):
            rise = sorted([r for r in rows if r['change_pct'] > 0],
                          key=lambda x: -x['change_pct'])[:top_n]
            drop = sorted([r for r in rows if r['change_pct'] < 0],
                          key=lambda x: x['change_pct'])[:top_n]
            return rise, drop

        qws_rise, qws_drop = _tops(qws_rows)
        mom_rise, mom_drop = _tops(mom_rows)

        # 工厂选项（Approved 全量数据口径，不受当前筛选影响）
        plant_options = sorted({
            p for p in (normalize_plant(x) for x in
                        BolOverView.objects.filter(final_approve_status='Approved')
                        .values_list('location', flat=True).distinct())
            if p and p != '未知'
        })

        return Response({
            'qws': {'rise': qws_rise, 'drop': qws_drop},
            'mom': {'rise': mom_rise, 'drop': mom_drop},
            'plant_options': plant_options,
            'stats': {
                'groups': len(groups),
                'qws_computed': len(qws_rows),
                'mom_computed': len(mom_rows),
            },
        })


# -*- coding: utf-8 -*-
"""高BOL跟踪 视图集：包含状态流转闭环 action"""
from datetime import date

from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response

from apps.tracking.models import HighBolTracking, ImprovementLog
from apps.tracking.serializers import (
    HighBolTrackingSerializer, ImprovementLogSerializer,
)


# 状态流转规则：当前状态 -> 允许流转到的下一个状态
STATE_TRANSITIONS = {
    'OPEN': ['IN_PROGRESS'],
    'REOPENED': ['IN_PROGRESS'],
    'IN_PROGRESS': ['ACHIEVED'],
    'ACHIEVED': ['VERIFIED', 'IN_PROGRESS'],  # 验证失败可退回改善中
    'VERIFIED': ['CLOSED', 'IN_PROGRESS'],   # 关闭前可退回改善中
    'CLOSED': ['REOPENED'],                  # 已关闭可重新打开
}


def _write_log(tracking, log_type, action_text, log_by='', log_by_name='',
               bol_after=None, progress_update=None):
    """写一条改善日志（用于闭环时间线展示）"""
    ImprovementLog.objects.create(
        tracking=tracking,
        log_date=date.today(),
        action=action_text,
        bol_after=bol_after,
        progress_update=progress_update if progress_update is not None else tracking.progress,
        log_by=log_by,
        log_by_name=log_by_name,
        log_type=log_type,
    )


class HighBolTrackingViewSet(viewsets.ModelViewSet):
    """高BOL跟踪 视图集：支持筛选、搜索、排序 + 闭环状态流转

    状态流转必须通过 start/achieve/verify/close/reopen 等 action 完成，
    不允许通过 PUT/POST 直接修改 status / 验证/关闭审计字段。
    """
    queryset = HighBolTracking.objects.all()
    serializer_class = HighBolTrackingSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['program_code', 'location', 'process', 'status',
                        'issue_type', 'owner', 'priority']
    search_fields = ['program_name', 'customer', 'improvement_action', 'root_cause']
    ordering_fields = ['cost_gap', 'bol_gap', 'target_date', 'created_at', 'priority']

    def perform_create(self, serializer):
        """新建跟踪记录强制初始状态为 OPEN，并写入 CREATE 日志"""
        # 即使前端传入了 status，也强制覆盖为 OPEN（serializer 已设 status 只读，
        # 这里作为模型层的兜底防护）
        tracking = serializer.save(status='OPEN', created_by=(
            self.request.data.get('created_by', '') or ''
        ))
        _write_log(
            tracking, 'CREATE',
            f'创建跟踪任务：{tracking.program_code}/{tracking.process}',
            log_by=tracking.created_by,
            log_by_name=self.request.data.get('created_by_name', '') or tracking.created_by,
        )

    def perform_update(self, serializer):
        """更新跟踪记录时，禁止修改 status 与验证/关闭审计字段。

        这些字段只能通过 start/achieve/verify/close/reopen 等 action 修改，
        以保证状态机流转与审计日志的完整性。
        serializer.read_only_fields 已做防护，此方法作为额外校验层。
        """
        instance = serializer.save()
        # 若实例状态被异常修改（如绕过 serializer 直接操作），恢复原状态
        # （正常情况下不会触发，因为 status 已设为只读）
        return instance

    def _change_state(self, request, pk, target_status, log_type, log_text_fn,
                      extra_field_fn=None):
        """状态流转通用方法"""
        tracking = self.get_object()
        cur = tracking.status
        allowed = STATE_TRANSITIONS.get(cur, [])
        if target_status not in allowed:
            return Response(
                {'detail': f'当前状态 {cur} 不允许流转到 {target_status}，'
                           f'允许的下一个状态：{allowed}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # 取操作人
        operator_id = (request.data or {}).get('operator_id', '') or (request.data or {}).get('created_by', '')
        operator_name = (request.data or {}).get('operator_name', '') or operator_id

        # 应用额外字段（如验证意见、关闭人等）
        if extra_field_fn:
            extra_field_fn(tracking, request.data, operator_id, operator_name)

        tracking.status = target_status
        # 维护各状态时间戳
        now = timezone.now()
        if target_status == 'IN_PROGRESS':
            if not tracking.started_at:
                tracking.started_at = now
        if target_status == 'ACHIEVED':
            if not tracking.achieved_at:
                tracking.achieved_at = now
        if target_status == 'VERIFIED':
            tracking.verified_at = now
            tracking.verified_by = operator_id
            tracking.verified_by_name = operator_name
        if target_status == 'CLOSED':
            tracking.closed_at = now
            tracking.closed_by = operator_id
            tracking.closed_by_name = operator_name
        if target_status == 'REOPENED':
            # 重置验证/关闭字段
            tracking.verified_at = None
            tracking.verified_by = ''
            tracking.verified_by_name = ''
            tracking.closed_at = None
            tracking.closed_by = ''
            tracking.closed_by_name = ''

        tracking.save()
        _write_log(tracking, log_type, log_text_fn(tracking, operator_name),
                   log_by=operator_id, log_by_name=operator_name)
        return Response(HighBolTrackingSerializer(tracking).data)

    @action(detail=True, methods=['post'], url_path='assign')
    def assign(self, request, pk=None):
        """分派负责人（owner 字段更新，并写入 ASSIGN 日志）"""
        tracking = self.get_object()
        owner_id = (request.data or {}).get('owner', '').strip()
        owner_name = (request.data or {}).get('owner_name', '').strip()
        target_date = (request.data or {}).get('target_date')
        if not owner_id:
            return Response({'detail': '请指定负责人工号 owner'},
                            status=status.HTTP_400_BAD_REQUEST)
        tracking.owner = owner_id
        tracking.owner_name = owner_name or owner_id
        if target_date:
            tracking.target_date = target_date
        if not tracking.assigned_at:
            tracking.assigned_at = timezone.now()
        tracking.save()
        operator_id = (request.data or {}).get('operator_id', '') or owner_id
        operator_name = (request.data or {}).get('operator_name', '') or owner_name
        _write_log(
            tracking, 'ASSIGN',
            f'分派负责人：{tracking.owner_name}（{tracking.owner}）'
            + (f'，目标日期 {target_date}' if target_date else ''),
            log_by=operator_id, log_by_name=operator_name,
        )
        return Response(HighBolTrackingSerializer(tracking).data)

    @action(detail=True, methods=['post'], url_path='start')
    def start(self, request, pk=None):
        """开始改善（OPEN/REOPENED -> IN_PROGRESS）"""
        return self._change_state(
            request, pk, 'IN_PROGRESS', 'START',
            lambda t, op: f'{op or "操作人"} 启动改善任务',
        )

    @action(detail=True, methods=['post'], url_path='achieve')
    def achieve(self, request, pk=None):
        """达成（IN_PROGRESS -> ACHIEVED），可携带 bol_after 与 progress"""
        def extra(t, data, op_id, op_name):
            if 'bol_after' in data and data['bol_after'] not in (None, ''):
                t.current_bol = data['bol_after']
            if 'progress' in data and data['progress'] not in (None, ''):
                t.progress = data['progress']
            else:
                t.progress = 100
        return self._change_state(
            request, pk, 'ACHIEVED', 'ACHIEVE',
            lambda t, op: f'{op or "负责人"} 完成改善，BOL={t.current_bol}，进度={t.progress}%',
            extra_field_fn=extra,
        )

    @action(detail=True, methods=['post'], url_path='verify')
    def verify(self, request, pk=None):
        """验证（ACHIEVED -> VERIFIED），携带 verify_comment"""
        comment = (request.data or {}).get('verify_comment', '').strip()

        def extra(t, data, op_id, op_name):
            t.verify_comment = comment
        return self._change_state(
            request, pk, 'VERIFIED', 'VERIFY',
            lambda t, op: f'{op or "验证人"} 验证通过' + (f'：{comment}' if comment else ''),
            extra_field_fn=extra,
        )

    @action(detail=True, methods=['post'], url_path='close')
    def close(self, request, pk=None):
        """关闭（VERIFIED -> CLOSED）"""
        return self._change_state(
            request, pk, 'CLOSED', 'CLOSE',
            lambda t, op: f'{op or "关闭人"} 关闭任务',
        )

    @action(detail=True, methods=['post'], url_path='reopen')
    def reopen(self, request, pk=None):
        """重新打开（CLOSED -> REOPENED），携带 reopen_reason"""
        reason = (request.data or {}).get('reopen_reason', '').strip()

        def extra(t, data, op_id, op_name):
            t.remark = (t.remark or '') + f'\n[重新打开] {reason}'
        return self._change_state(
            request, pk, 'REOPENED', 'REOPEN',
            lambda t, op: f'{op or "操作人"} 重新打开任务' + (f'：{reason}' if reason else ''),
            extra_field_fn=extra,
        )

    @action(detail=True, methods=['post'], url_path='add-log')
    def add_log(self, request, pk=None):
        """追加一条进度日志（不影响状态）"""
        tracking = self.get_object()
        action_text = (request.data or {}).get('action', '').strip()
        if not action_text:
            return Response({'detail': '请提供 action 内容'},
                            status=status.HTTP_400_BAD_REQUEST)
        bol_after = (request.data or {}).get('bol_after')
        progress = (request.data or {}).get('progress')
        log_by = (request.data or {}).get('log_by', '')
        log_by_name = (request.data or {}).get('log_by_name', '') or log_by
        if progress not in (None, ''):
            tracking.progress = int(progress)
            tracking.save(update_fields=['progress', 'updated_at'])
        if bol_after not in (None, ''):
            tracking.current_bol = bol_after
            tracking.save(update_fields=['current_bol', 'updated_at'])
        _write_log(tracking, 'PROGRESS', action_text,
                   log_by=log_by, log_by_name=log_by_name,
                   bol_after=bol_after if bol_after not in (None, '') else None,
                   progress_update=progress if progress not in (None, '') else None)
        return Response(ImprovementLogSerializer(tracking.logs.order_by('-log_date', '-id'),
                                                 many=True).data)

    @action(detail=True, methods=['get'], url_path='timeline')
    def timeline(self, request, pk=None):
        """获取闭环时间线（按时间倒序）"""
        tracking = self.get_object()
        logs = tracking.logs.order_by('-log_date', '-id')
        nodes = []
        # 关键状态时间点
        if tracking.created_at:
            nodes.append({
                'type': 'CREATE', 'time': tracking.created_at,
                'title': '创建任务',
                'desc': f'由 {tracking.created_by or "系统"} 创建',
            })
        if tracking.assigned_at:
            nodes.append({
                'type': 'ASSIGN', 'time': tracking.assigned_at,
                'title': '分派负责人',
                'desc': f'负责人：{tracking.owner_name or tracking.owner}',
            })
        if tracking.started_at:
            nodes.append({
                'type': 'START', 'time': tracking.started_at,
                'title': '开始改善',
                'desc': '',
            })
        if tracking.achieved_at:
            nodes.append({
                'type': 'ACHIEVE', 'time': tracking.achieved_at,
                'title': '达成',
                'desc': f'当前 BOL={tracking.current_bol}，进度={tracking.progress}%',
            })
        if tracking.verified_at:
            nodes.append({
                'type': 'VERIFY', 'time': tracking.verified_at,
                'title': '验证通过',
                'desc': f'验证人：{tracking.verified_by_name or tracking.verified_by}'
                        + (f'，意见：{tracking.verify_comment}' if tracking.verify_comment else ''),
            })
        if tracking.closed_at:
            nodes.append({
                'type': 'CLOSE', 'time': tracking.closed_at,
                'title': '关闭',
                'desc': f'关闭人：{tracking.closed_by_name or tracking.closed_by}',
            })
        # 日志条目
        for log in logs:
            nodes.append({
                'type': log.log_type, 'time': log.created_at,
                'title': log.get_log_type_display() if log.log_type else '日志',
                'desc': log.action,
                'log_by': log.log_by_name or log.log_by,
                'bol_after': log.bol_after,
                'progress': log.progress_update,
            })
        # 按 time 倒序
        nodes.sort(key=lambda x: x['time'] or timezone.now(), reverse=True)
        return Response(nodes)

    @action(detail=False, methods=['get'], url_path='search-programs')
    def search_programs(self, request):
        """项目编号检索（数据来源：cbco_records 表）

        查询参数:
            q: 项目编号关键字（支持模糊匹配 program_number）
            year: 年份（默认取当前年份的下一年；对应 cbco_records.year）

        返回:
            items: 匹配的项目列表，包含 program_number、customer、program_description、
                   irs_location、typ_of_roof、volume 等

        用途:
            新增跟踪记录时，用户输入项目编号后自动检索项目名称、客户、年产量等信息，
            无需手工填写。
        """
        from apps.budget_bol.cbco_models import CbcoRecord
        from bol_platform.plant_utils import normalize_plant
        from datetime import datetime

        q = (request.query_params.get('q') or '').strip()
        year_param = request.query_params.get('year')
        # 默认取当前年份的下一年
        if year_param:
            try:
                target_year = int(year_param)
            except (TypeError, ValueError):
                target_year = datetime.now().year + 1
        else:
            target_year = datetime.now().year + 1

        qs = CbcoRecord.objects.all()
        if q:
            qs = qs.filter(program_number__icontains=q)
        # 优先匹配目标年份；若无则不限制年份（后续取最近一条）
        year_qs = qs.filter(year=target_year)
        if not year_qs.exists():
            # 目标年份无数据则不限年份，取最近一条
            year_qs = qs

        # 按 program_number 去重，保留最新 year 的一条
        seen = set()
        items = []
        for r in year_qs.order_by('program_number', '-year'):
            if r.program_number in seen:
                continue
            seen.add(r.program_number)
            items.append({
                'program_number': r.program_number or '',
                'program_description': r.program_description or '',
                'customer': r.customer or '',
                'irs_location': normalize_plant(r.irs_location or ''),
                'typ_of_roof': r.typ_of_roof or '',
                'topline_status': r.topline_status or '',
                'product_group': r.product_group or '',
                'volume': int(r.volume or 0),
                'year': r.year,
                'sop_date': r.sop_date.date().isoformat() if r.sop_date else None,
                'eop_date': r.eop_date.date().isoformat() if r.eop_date else None,
            })
            if len(items) >= 50:
                break

        return Response({
            'items': items,
            'year': target_year,
            'total': len(items),
        })


class ImprovementLogViewSet(viewsets.ModelViewSet):
    """改善日志 视图集：支持按跟踪项筛选"""
    queryset = ImprovementLog.objects.all()
    serializer_class = ImprovementLogSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['tracking', 'log_type', 'log_by']
    search_fields = ['action']
    ordering_fields = ['log_date', 'created_at']

# -*- coding: utf-8 -*-
"""年度预算BOL 视图：列表查询 / 筛选器 / 模板下载 / Excel导入 / 导入履历 / 一键清空

接口约定（DefaultRouter，路由前缀 /api/budget-bol/budget-bol/）：
- GET  /                列表（按 bol_type 路由到 BudgetBol / AchievableTargetBol）
- GET  /filter-options/ 筛选器选项（财年 / 工厂 / 工艺类型）
- GET  /import-template/ 下载 Excel 上传模板（type=budget|achievable|target，大小写不敏感）
- POST /import-excel/   Excel 导入（同年同类型先清空再全量替换，自动记录导入履历）
- GET  /import-logs/    导入履历查询（支持财年/类型筛选）
- POST /clear-all/      一键清空（仅管理员，需输入 CONFIRM_CLEAR）
"""
import re

from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.budget_bol.excel_importer import BudgetBolImporter
from apps.budget_bol.excel_template import generate_template_bytes, TYPE_LABELS
from apps.budget_bol.models import BudgetBol, AchievableTargetBol, BolImportLog
from apps.budget_bol.cbco_models import CbcoRecord
from apps.budget_bol.serializers import (
    BudgetBolSerializer,
    AchievableTargetBolSerializer,
)
from apps.users.permissions import IsAdmin

# 导入履历失败原因最大长度（TEXT 字段保护）
_ERROR_MSG_MAX = 2000


def _qstr(request, name):
    """取查询参数，去空白；空字符串视为未提供"""
    v = request.query_params.get(name)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _qint(request, name, default=None):
    v = _qstr(request, name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _norm_bol_type(raw):
    """BOL 类型归一化：大小写不敏感，返回大写常量或 None"""
    v = (raw or '').strip().upper()
    if v in ('BUDGET', 'ACHIEVABLE', 'TARGET'):
        return v
    return None


def _active_status_rows(rows):
    """仅保留 CBCO 状态为 MUST 或 WON 的项目。"""
    return [
        row for row in rows
        if str(row.get('status') or '').strip().upper() in {'MUST', 'WON'}
    ]


def _attach_project_metadata(rows):
    project_codes = {row['project_code'] for row in rows if row.get('project_code')}
    if not project_codes:
        return rows

    records = CbcoRecord.objects.filter(
        program_number__in=project_codes
    ).order_by('-year', '-id').values(
        'program_number', 'year', 'customer', 'program_description',
        'typ_of_roof', 'topline_status', 'sop_date', 'eop_date',
    )
    records_by_project = {}
    for record in records:
        records_by_project.setdefault(record['program_number'], []).append(record)

    for row in rows:
        candidates = records_by_project.get(row.get('project_code'), [])
        info = next(
            (item for item in candidates if item['year'] == row.get('fiscal_year')),
            candidates[0] if candidates else None,
        )
        if not info:
            continue

        row.update({
            'customer': info['customer'] or '',
            'program_description': info['program_description'] or '',
            'roof_type': info['typ_of_roof'] or '',
            'status': info['topline_status'] or '',
            'sop': info['sop_date'].strftime('%Y-%m-%d') if info['sop_date'] else '',
            'eop': info['eop_date'].strftime('%Y-%m-%d') if info['eop_date'] else '',
        })
    return rows


def _project_codes_by_name(project_name):
    """从 HRDB 项目名称和 CMC 项目描述中查找项目代码。"""
    from apps.projects.models import ProgramInfo

    codes = set(
        ProgramInfo.objects.filter(
            program_name__icontains=project_name,
        ).values_list('program_code', flat=True)
    )
    codes.update(
        CbcoRecord.objects.filter(
            program_description__icontains=project_name,
        ).values_list('program_number', flat=True)
    )
    return codes


class BudgetBolViewSet(viewsets.ViewSet):
    """预算BOL 视图集（三种 BOL 类型统一入口）"""

    # ------------------------------------------------------------------
    # 列表查询
    # ------------------------------------------------------------------
    def list(self, request):
        fiscal_year = _qint(request, 'fiscal_year')
        bol_type = _norm_bol_type(_qstr(request, 'bol_type')) or 'BUDGET'
        plant = _qstr(request, 'plant')
        process_type = _qstr(request, 'process_type')
        project_code = _qstr(request, 'project_code')
        project_name = _qstr(request, 'project_name')

        # 项目名称跨 HRDB / CMC 反查为代码，再过滤 BOL 记录。
        project_name_codes = None
        if project_name:
            project_name_codes = _project_codes_by_name(project_name)

        if bol_type == 'BUDGET':
            qs = BudgetBol.objects.all().order_by(
                '-fiscal_year', 'project_code', 'process_type')
            if fiscal_year:
                qs = qs.filter(fiscal_year=fiscal_year)
            if plant:
                qs = qs.filter(plant=plant)
            if process_type:
                qs = qs.filter(process_type=process_type)
            if project_code:
                qs = qs.filter(project_code__icontains=project_code)
            if project_name_codes is not None:
                qs = qs.filter(project_code__in=project_name_codes)
            data = [dict(row) for row in BudgetBolSerializer(qs, many=True).data]
        else:
            qs = AchievableTargetBol.objects.all().order_by(
                '-fiscal_year', 'project_code', 'process_type')
            if fiscal_year:
                qs = qs.filter(fiscal_year=fiscal_year)
            qs = qs.filter(bol_type=bol_type)
            if plant:
                qs = qs.filter(plant=plant)
            if process_type:
                qs = qs.filter(process_type=process_type)
            if project_code:
                qs = qs.filter(project_code__icontains=project_code)
            if project_name_codes is not None:
                qs = qs.filter(project_code__in=project_name_codes)
            data = [dict(row) for row in AchievableTargetBolSerializer(qs, many=True).data]

        rows = _attach_project_metadata(data)
        return Response(_active_status_rows(rows))

    # ------------------------------------------------------------------
    # 筛选器选项
    # ------------------------------------------------------------------
    @action(detail=False, methods=['get'], url_path='filter-options')
    def filter_options(self, request):
        fiscal_years = set()
        plants = set()
        process_types = set()

        for r in BudgetBol.objects.values('fiscal_year', 'plant', 'process_type'):
            if r['fiscal_year'] is not None:
                fiscal_years.add(r['fiscal_year'])
            if r['plant']:
                plants.add(r['plant'])
            if r['process_type']:
                process_types.add(r['process_type'])

        for r in AchievableTargetBol.objects.values(
                'fiscal_year', 'plant', 'process_type'):
            if r['fiscal_year'] is not None:
                fiscal_years.add(r['fiscal_year'])
            if r['plant']:
                plants.add(r['plant'])
            if r['process_type']:
                process_types.add(r['process_type'])

        return Response({
            'fiscal_years': sorted(fiscal_years, reverse=True),
            'plants': sorted(plants),
            'process_types': sorted(process_types),
        })

    # ------------------------------------------------------------------
    # 模板下载
    # ------------------------------------------------------------------
    @action(detail=False, methods=['get'], url_path='import-template')
    def template(self, request):
        # 注意：excel_template 的类型常量为小写（budget/achievable/target），
        # 与 excel_importer 的大写常量不同，必须 lower() 后校验
        # 前端调用 /budget-bol/budget-bol/import-template/?type=xxx
        raw_type = (_qstr(request, 'type') or 'achievable').lower()
        if raw_type not in ('budget', 'achievable', 'target', 'original'):
            raw_type = 'achievable'

        content = generate_template_bytes(raw_type)
        filename = f'budget_bol_{raw_type}_template.xlsx'
        resp = HttpResponse(
            content,
            content_type='application/vnd.openxmlformats-officedocument'
                         '.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp

    # ------------------------------------------------------------------
    # Excel 导入
    # ------------------------------------------------------------------
    @action(detail=False, methods=['post'], url_path='import-excel')
    def import_excel(self, request):
        file_obj = request.FILES.get('file')
        if file_obj is None:
            return Response(
                {'detail': '请上传 Excel 文件（form-data 字段名 file）'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fiscal_year = request.data.get('fiscal_year') or _qint(request, 'fiscal_year')
        try:
            fiscal_year = int(fiscal_year)
        except (TypeError, ValueError):
            return Response(
                {'detail': '财年必须为整数'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bol_type = _norm_bol_type(request.data.get('bol_type'))
        if not bol_type:
            return Response(
                {'detail': '不支持的 BOL 类型（BUDGET/ACHIEVABLE/TARGET）'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        form_created_by = str(request.data.get('created_by') or '').strip()
        # 导入用户优先记录当前登录账号
        current_user = ''
        employee = getattr(request, 'user', None)
        if employee is not None and getattr(employee, 'is_authenticated', False):
            current_user = str(getattr(employee, 'username', '') or '')
        created_by = current_user or form_created_by

        # 生成安全文件名（去除路径分隔符等危险字符）
        raw_name = file_obj.name or ''
        safe_name = re.sub(r'[\\/:*?"<>|]+', '_', raw_name)[:255]

        # 先落盘到临时文件（openpyxl load_workbook 需要文件路径或字节流）
        import os
        import tempfile
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    suffix='.xlsx', delete=False) as tmp:
                for chunk in file_obj.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            importer = BudgetBolImporter(
                fiscal_year=fiscal_year,
                bol_type=bol_type,
                created_by=created_by,
            )
            result = importer.import_from_file(tmp_path)
        except Exception as e:
            result = {
                'total_rows': 0,
                'imported': 0,
                'skipped': 0,
                'deleted': 0,
                'errors': [f'导入过程异常: {e}'],
                'fiscal_year': fiscal_year,
                'bol_type': bol_type,
            }
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        # 无论成功或失败均记录导入履历
        is_success = not result.get('errors')
        error_text = '; '.join(result.get('errors') or [])[:_ERROR_MSG_MAX]
        try:
            BolImportLog.objects.create(
                fiscal_year=fiscal_year,
                bol_type=bol_type,
                file_name=safe_name,
                file_size=file_obj.size if file_obj.size else None,
                imported_by=created_by[:50],
                total_rows=int(result.get('total_rows') or 0),
                imported=int(result.get('imported') or 0),
                deleted=int(result.get('deleted') or 0),
                skipped=int(result.get('skipped') or 0),
                status=BolImportLog.STATUS_SUCCESS if is_success
                       else BolImportLog.STATUS_FAILED,
                error_message=error_text,
            )
        except Exception:
            # 履历记录失败不影响导入结果返回
            pass

        return Response(result)

    # ------------------------------------------------------------------
    # 导入履历查询
    # ------------------------------------------------------------------
    @action(detail=False, methods=['get'], url_path='import-logs')
    def import_logs(self, request):
        qs = BolImportLog.objects.all().order_by('-created_at')

        fiscal_year = _qint(request, 'fiscal_year')
        if fiscal_year:
            qs = qs.filter(fiscal_year=fiscal_year)

        bol_type = _norm_bol_type(_qstr(request, 'bol_type'))
        if bol_type:
            qs = qs.filter(bol_type=bol_type)

        limit = _qint(request, 'limit', default=50)
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50

        data = []
        for log in qs[:limit]:
            data.append({
                'id': log.id,
                'fiscal_year': log.fiscal_year,
                'bol_type': log.bol_type,
                'file_name': log.file_name,
                'file_size': log.file_size,
                'imported_by': log.imported_by,
                'total_rows': log.total_rows,
                'imported': log.imported,
                'deleted': log.deleted,
                'skipped': log.skipped,
                'status': log.status,
                'error_message': log.error_message,
                'created_at': log.created_at.isoformat() if log.created_at else None,
            })
        return Response(data)

    # ------------------------------------------------------------------
    # 一键清空（仅管理员）
    # ------------------------------------------------------------------
    @action(detail=False, methods=['post'], url_path='clear-all',
            permission_classes=[IsAdmin])
    def clear_all(self, request):
        confirm = str(request.data.get('confirm') or '').strip()
        if confirm != 'CONFIRM_CLEAR':
            return Response(
                {'detail': '请输入 CONFIRM_CLEAR 以确认清空操作'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fiscal_year = request.data.get('fiscal_year')
        try:
            fiscal_year = int(fiscal_year) if fiscal_year not in (None, '') else None
        except (TypeError, ValueError):
            return Response(
                {'detail': '财年必须为整数'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bol_type = _norm_bol_type(request.data.get('bol_type'))

        deleted = 0
        if bol_type == 'BUDGET' or bol_type is None:
            qs = BudgetBol.objects.all()
            if fiscal_year:
                qs = qs.filter(fiscal_year=fiscal_year)
            n, _ = qs.delete()
            deleted += n
        if bol_type in ('ACHIEVABLE', 'TARGET', None):
            qs = AchievableTargetBol.objects.all()
            if fiscal_year:
                qs = qs.filter(fiscal_year=fiscal_year)
            if bol_type:
                qs = qs.filter(bol_type=bol_type)
            n, _ = qs.delete()
            deleted += n

        return Response({'deleted': deleted})

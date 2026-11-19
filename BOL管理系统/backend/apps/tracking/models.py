# -*- coding: utf-8 -*-
"""高BOL项目跟踪闭环模型 - CMC库可读写"""
from django.db import models
from django.utils import timezone

from bol_platform.bol_calc import calc_labor_cost_gap


class HighBolTracking(models.Model):
    """
    高BOL项目跟踪（CMC 读写，对应 CN_IE_BOL_HighBolTracking）
    记录BOL超标项目的改善目标、措施、进度，形成完整闭环：
    OPEN → IN_PROGRESS → ACHIEVED → VERIFIED → CLOSED
    """
    id = models.BigAutoField(primary_key=True)

    # ---- 基本信息 ----
    program_code = models.CharField(max_length=15, verbose_name='项目代码')
    program_name = models.CharField(max_length=200, blank=True, verbose_name='项目名称')
    customer = models.CharField(max_length=100, blank=True, verbose_name='客户')
    location = models.CharField(max_length=20, blank=True, verbose_name='地点')
    process = models.CharField(max_length=20, blank=True, verbose_name='工艺')
    line_nr = models.CharField(max_length=15, blank=True, verbose_name='产线编号')

    # ---- 问题与目标 ----
    issue_type = models.CharField(
        max_length=30, verbose_name='问题类型',
        choices=[
            ('QWS_GAP', 'QWS报价BOL低于实际'),
            ('BUDGET_GAP', '预算BOL低于实际'),
            ('OTHER', '其他'),
        ],
    )
    current_bol = models.DecimalField(max_digits=10, decimal_places=4, verbose_name='当前实际BOL')
    target_bol = models.DecimalField(max_digits=10, decimal_places=4, verbose_name='目标BOL')
    target_source = models.CharField(
        max_length=20, verbose_name='目标来源',
        choices=[
            ('QWS', 'QWS报价'),
            ('BUDGET', '年度预算'),
        ],
    )
    bol_gap = models.DecimalField(max_digits=10, decimal_places=4, default=0, verbose_name='BOL差值')
    annual_volume = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='年产量')
    labor_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name='工时单价(元/小时)')
    cost_gap = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='年化成本差异估算')

    # ---- 优先级与原因分析 ----
    priority = models.CharField(
        max_length=10, default='MEDIUM', verbose_name='优先级',
        choices=[
            ('HIGH', '高'),
            ('MEDIUM', '中'),
            ('LOW', '低'),
        ],
    )
    # 变更类型：ECR / 过程变更
    change_type = models.CharField(
        max_length=20, blank=True, verbose_name='变更类型',
        choices=[
            ('ECR', 'ECR'),
            ('PROCESS_CHANGE', '过程变更'),
        ],
    )
    # 费用承担方：customer / internal
    paid_by = models.CharField(
        max_length=20, blank=True, verbose_name='费用承担方',
        choices=[
            ('CUSTOMER', 'customer'),
            ('INTERNAL', 'internal'),
        ],
    )
    # 变更原因：design / quality / VAVE / manufacturing 等
    change_reason = models.CharField(
        max_length=30, blank=True, verbose_name='变更原因',
        choices=[
            ('DESIGN', 'design'),
            ('QUALITY', 'quality'),
            ('VAVE', 'VAVE'),
            ('MANUFACTURING', 'manufacturing'),
            ('OTHER', '其他'),
        ],
    )
    root_cause = models.TextField(blank=True, verbose_name='根本原因分析')

    # ---- 改善方案 ----
    improvement_action = models.TextField(blank=True, verbose_name='改善措施')
    improvement_plan = models.TextField(blank=True, verbose_name='改善计划')
    improvement_type = models.CharField(
        max_length=20, blank=True, verbose_name='改善类型',
        choices=[
            ('CAPEX', '设备投资'),
            ('OPEX', '运营优化'),
            ('PROCESS', '工艺改进'),
            ('STAFFING', '人员调整'),
            ('OTHER', '其他'),
        ],
    )

    # ---- 责任人 ----
    owner = models.CharField(max_length=30, blank=True, verbose_name='负责人工号')
    owner_name = models.CharField(max_length=50, blank=True, verbose_name='负责人姓名')
    target_date = models.DateField(null=True, blank=True, verbose_name='目标达成日期')

    # ---- 状态流转 ----
    status = models.CharField(
        max_length=20, default='OPEN', verbose_name='状态',
        choices=[
            ('OPEN', '待处理'),
            ('IN_PROGRESS', '改善中'),
            ('ACHIEVED', '已达成'),
            ('VERIFIED', '已验证'),
            ('CLOSED', '已关闭'),
            ('REOPENED', '已重新打开'),
        ],
    )
    progress = models.IntegerField(default=0, verbose_name='进度')

    # ---- 流转时间节点（闭环跟踪） ----
    assigned_at = models.DateTimeField(null=True, blank=True, verbose_name='分派时间')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始改善时间')
    achieved_at = models.DateTimeField(null=True, blank=True, verbose_name='达成时间')
    verified_by = models.CharField(max_length=30, blank=True, verbose_name='验证人工号')
    verified_by_name = models.CharField(max_length=50, blank=True, verbose_name='验证人姓名')
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name='验证时间')
    verify_comment = models.TextField(blank=True, verbose_name='验证意见')
    closed_by = models.CharField(max_length=30, blank=True, verbose_name='关闭人工号')
    closed_by_name = models.CharField(max_length=50, blank=True, verbose_name='关闭人姓名')
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name='关闭时间')

    # ---- 审计字段 ----
    created_by = models.CharField(max_length=30, blank=True, verbose_name='创建人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    remark = models.TextField(blank=True, verbose_name='备注')

    class Meta:
        managed = True
        db_table = 'CN_IE_BOL_HighBolTracking'
        app_label = 'tracking'
        verbose_name = '高BOL跟踪'
        verbose_name_plural = verbose_name
        ordering = ['-cost_gap']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['owner']),
            models.Index(fields=['priority']),
            models.Index(fields=['target_date']),
            models.Index(fields=['program_code']),
        ]

    def __str__(self):
        return f"{self.program_code} {self.process} {self.issue_type}"

    def save(self, *args, **kwargs):
        """保存时自动计算 bol_gap、cost_gap，并维护达成时间"""
        # 计算 BOL 差值 = 当前 - 目标（正值表示超标）
        try:
            current = float(self.current_bol) if self.current_bol is not None else 0.0
            target = float(self.target_bol) if self.target_bol is not None else 0.0
            self.bol_gap = round(current - target, 4)
        except (TypeError, ValueError):
            self.bol_gap = 0

        # BOL 差异为分钟/件，工时单价为元/小时，换算后得到年化成本差异。
        try:
            annual_volume = float(self.annual_volume) if self.annual_volume is not None else 0.0
            labor_rate = float(self.labor_rate) if self.labor_rate is not None else 0.0
            self.cost_gap = calc_labor_cost_gap(float(self.bol_gap or 0), annual_volume, labor_rate)
        except (TypeError, ValueError):
            self.cost_gap = 0

        # 状态为已达成且达成时间为空时，自动设置达成时间
        if self.status in ('ACHIEVED', 'VERIFIED', 'CLOSED') and not self.achieved_at:
            self.achieved_at = timezone.now()

        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {'bol_gap', 'cost_gap'}

        super().save(*args, **kwargs)


class ImprovementLog(models.Model):
    """
    改善进展日志（CMC 读写，对应 CN_IE_BOL_ImprovementLog）
    记录高BOL跟踪项每次改善行动及行动后的BOL值，作为闭环时间线的依据
    """
    id = models.BigAutoField(primary_key=True)
    tracking = models.ForeignKey(
        HighBolTracking, on_delete=models.CASCADE, related_name='logs',
        verbose_name='关联跟踪记录',
    )
    log_date = models.DateField(verbose_name='日志日期')
    action = models.TextField(verbose_name='本次采取的行动')
    bol_after = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True, verbose_name='行动后BOL',
    )
    progress_update = models.IntegerField(default=0, verbose_name='进度更新')
    log_by = models.CharField(max_length=30, blank=True, verbose_name='记录人工号')
    log_by_name = models.CharField(max_length=50, blank=True, verbose_name='记录人姓名')
    # 日志类型：用于在时间线上区分节点
    log_type = models.CharField(
        max_length=20, default='PROGRESS', verbose_name='日志类型',
        choices=[
            ('CREATE', '创建'),
            ('ASSIGN', '分派'),
            ('START', '开始'),
            ('PROGRESS', '进度更新'),
            ('ACHIEVE', '达成'),
            ('VERIFY', '验证'),
            ('CLOSE', '关闭'),
            ('REOPEN', '重新打开'),
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        managed = True
        db_table = 'CN_IE_BOL_ImprovementLog'
        app_label = 'tracking'
        verbose_name = '改善日志'
        verbose_name_plural = verbose_name
        ordering = ['-log_date', '-id']

    def __str__(self):
        return f"{self.tracking_id} {self.log_date} {self.log_type}"

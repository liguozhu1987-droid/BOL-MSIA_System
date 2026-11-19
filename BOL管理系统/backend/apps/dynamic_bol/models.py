# -*- coding: utf-8 -*-
"""BOL审批更新记录模型 - 映射 HRDB.CN_IE_BOLOverView 与 CN_IE_BOLOverView_byProcess 表（只读）

说明：所谓"动态BOL"实际是 BOL 审批更新的历史记录：
工厂做完改善后在系统提交 BOL 变更，经审批后形成更新记录。
本模块统一读为"BOL更新记录"。
"""
from django.db import models


class BolOverView(models.Model):
    """
    BOL更新记录总览（HRDB 只读，对应 CN_IE_BOLOverView，92字段）
    每次 BOL 审批更新的完整记录，含QWS报价BOL、审批状态、CT优化申请等
    """
    bol_nr = models.CharField(max_length=50, primary_key=True, db_column='BOL_Nr')
    program_code = models.CharField(max_length=15, db_column='programCode')
    program_name = models.CharField(max_length=200, blank=True, db_column='programName')
    customer = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=20, blank=True)
    type = models.CharField(max_length=50, blank=True)
    version = models.CharField(max_length=5)
    bol_overall = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, db_column='BOL_Overall')
    submit_date = models.DateTimeField(null=True, blank=True, db_column='submitDate')
    submit_user_name = models.CharField(max_length=30, blank=True, db_column='submitUseName')
    # 审批状态
    pro_approve_status = models.CharField(max_length=5, blank=True, db_column='pro_approveStatus')
    scm_approve_status = models.CharField(max_length=5, blank=True, db_column='scm_approveStatus')
    hr_approve_status = models.CharField(max_length=5, blank=True, db_column='hr_approveStatus')
    manager_approve_status = models.CharField(max_length=5, blank=True, db_column='manager_approveStatus')
    final_approve_status = models.CharField(max_length=20, blank=True, db_column='final_approve_status')
    # 业务字段
    customer_location = models.CharField(max_length=50, blank=True, db_column='customerLocation')
    net_production_time = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, db_column='net_productionTime')
    peak_volume = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, db_column='peakVolume')
    status = models.CharField(max_length=20, blank=True)
    line_coordinator = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, db_column='lineCoordinator')
    total_hc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, db_column='totalHC')
    customer_requirement = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, db_column='customerRequirement')
    design_ct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, db_column='designCT')
    fa_oee = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, db_column='FA_OEE')
    qws_bol = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, db_column='qwsBOL')
    # 工艺级 BOL
    process = models.CharField(max_length=20, blank=True)
    line_nr = models.CharField(max_length=15, blank=True, db_column='lineNr')
    ct = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, db_column='CT')
    hc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, db_column='HC')
    bol = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, db_column='BOL')
    oee = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, db_column='oee')
    bottle_neck_station = models.CharField(max_length=15, blank=True, db_column='bottleNeckStation')
    line_balance = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, db_column='lineBalance')
    # 分类与差异
    category = models.CharField(max_length=30, blank=True)
    new_project = models.CharField(max_length=2, blank=True, db_column='newProject')
    gap_bol = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, db_column='gap_BOL')
    rejected = models.CharField(max_length=2, blank=True, default='N')
    recall = models.CharField(max_length=5, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'CN_IE_BOLOverView'
        app_label = 'dynamic_bol'
        verbose_name = 'BOL更新记录'
        verbose_name_plural = verbose_name
        ordering = ['-submit_date']

    def __str__(self):
        return f"{self.bol_nr} ({self.program_code}/{self.process})"


class BolOverViewByProcess(models.Model):
    """按工艺拆分的BOL详情（HRDB 只读，对应 CN_IE_BOLOverView_byProcess）
    注意：HRDB 表无 id 列，使用 BOL_Nr 作为主键（每条记录 BOL_Nr 唯一）。
    """
    bol_nr = models.CharField(max_length=50, primary_key=True, db_column='BOL_Nr')
    program_code = models.CharField(max_length=15, db_column='programCode')
    line_nr = models.CharField(max_length=15, db_column='lineNr')
    process = models.CharField(max_length=20)
    ct = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, db_column='CT')
    hc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, db_column='HC')
    bol = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, db_column='BOL')
    oee = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, db_column='oee')
    bottle_neck_station = models.CharField(max_length=15, blank=True, db_column='bottleNeckStation')
    version = models.CharField(max_length=5)
    location = models.CharField(max_length=20, blank=True)
    user_name = models.CharField(max_length=20, blank=True, db_column='userName')
    update_time = models.DateTimeField(null=True, blank=True, db_column='updateTime')
    lb_rate = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, db_column='LB_rate')

    class Meta:
        managed = False
        db_table = 'CN_IE_BOLOverView_byProcess'
        app_label = 'dynamic_bol'
        verbose_name = '工艺BOL详情'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.bol_nr} - {self.process}"


class BolApprovalHistory(models.Model):
    """BOL审批历史（HRDB 只读，对应 CN_IE_BOL_approval_historyList）"""
    id = models.BigAutoField(primary_key=True)
    bol_nr = models.CharField(max_length=50, db_column='BOL_Nr')
    approval_type = models.CharField(max_length=30, blank=True, db_column='approvalType')
    operat_user = models.CharField(max_length=30, blank=True, db_column='operatUser')
    approval_status = models.CharField(max_length=5, blank=True, db_column='approvalStatus')
    update_time = models.DateTimeField(null=True, blank=True, db_column='updateTime')

    class Meta:
        managed = False
        db_table = 'CN_IE_BOL_approval_historyList'
        app_label = 'dynamic_bol'
        verbose_name = '审批历史'
        verbose_name_plural = verbose_name


class BolUpdateHistory(models.Model):
    """BOL更新历史（HRDB 只读，对应 CN_IE_BOL_UpdateHistoryList）"""
    id = models.BigAutoField(primary_key=True)
    program_code = models.CharField(max_length=15, db_column='programCode')
    process = models.CharField(max_length=20)
    version = models.CharField(max_length=5)
    line_nr = models.CharField(max_length=15, db_column='lineNr')
    location = models.CharField(max_length=20, blank=True)
    if_wct_upload = models.BooleanField(default=False, db_column='if_wct_upload')
    if_bol_upload = models.BooleanField(default=False, db_column='if_bol_upload')
    user_name = models.CharField(max_length=20, blank=True, db_column='userName')
    update_date = models.DateTimeField(null=True, blank=True, db_column='updateDate')
    if_approved = models.BooleanField(default=False, db_column='if_approved')
    category = models.CharField(max_length=30, blank=True)
    bol_nr = models.CharField(max_length=50, db_column='BOL_Nr')

    class Meta:
        managed = False
        db_table = 'CN_IE_BOL_UpdateHistoryList'
        app_label = 'dynamic_bol'
        verbose_name = '更新历史'
        verbose_name_plural = verbose_name


class FineUser(models.Model):
    """HRDB 用户表（只读，对应 fine_user）

    用于将 BolOverView.submit_user_name（用户名）映射为 realName（真实姓名）展示
    """
    id = models.CharField(max_length=255, primary_key=True)
    user_name = models.CharField(max_length=255, blank=True, db_column='userName')
    real_name = models.CharField(max_length=255, blank=True, db_column='realName')
    email = models.CharField(max_length=255, blank=True)
    mobile = models.CharField(max_length=255, blank=True)

    class Meta:
        managed = False
        db_table = 'fine_user'
        app_label = 'dynamic_bol'
        verbose_name = 'HRDB用户'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.user_name} ({self.real_name})"

# -*- coding: utf-8 -*-
"""CMC cbco_records 只读模型

用于通过 program_number（项目编号）检索项目基本信息：
客户、项目描述、IRS 地点、顶棚类型、Topline 状态（WON/MUST）、
SOP/EOP 日期、产品组（如 BLTS）等。

在 Budget BOL 导入时自动同步这些字段，避免每次联表查询。
"""
from django.db import models


class CbcoRecord(models.Model):
    """CMC cbco_records 表（只读，每行=某项目某年一条产量记录）

    同一 program_number 在不同 year 下可能有多条记录，
    同步项目基本信息时取与财年匹配的记录，若不存在则取最近一条。
    """
    id = models.BigAutoField(primary_key=True)
    program_number = models.CharField(max_length=100, verbose_name='项目编号')
    customer = models.CharField(max_length=200, blank=True, verbose_name='客户')
    program_description = models.CharField(max_length=500, blank=True,
                                           verbose_name='项目描述')
    irs_location = models.CharField(max_length=200, blank=True, verbose_name='IRS地点')
    typ_of_roof = models.CharField(max_length=100, blank=True, verbose_name='顶棚类型')
    topline_status = models.CharField(max_length=100, blank=True,
                                      verbose_name='Topline状态(WON/MUST)')
    sop_date = models.DateTimeField(null=True, blank=True, verbose_name='SOP日期')
    eop_date = models.DateTimeField(null=True, blank=True, verbose_name='EOP日期')
    region = models.CharField(max_length=50, blank=True, verbose_name='区域')
    weekly_max_capacity = models.FloatField(null=True, blank=True,
                                            verbose_name='周最大产能')
    year = models.IntegerField(verbose_name='年份')
    volume = models.IntegerField(verbose_name='产量')
    product_group = models.CharField(max_length=100, blank=True, verbose_name='产品组')
    program_phase = models.CharField(max_length=50, blank=True, verbose_name='项目阶段')
    version_id = models.IntegerField(null=True, blank=True, verbose_name='版本ID')
    upload_log_id = models.IntegerField(null=True, blank=True, verbose_name='上传日志ID')
    uploaded_by = models.IntegerField(null=True, blank=True, verbose_name='上传人ID')
    created_at = models.DateTimeField(null=True, blank=True, verbose_name='创建时间')
    is_manual = models.BooleanField(null=True, blank=True, verbose_name='是否手工录入')

    class Meta:
        managed = False
        db_table = 'cbco_records'
        app_label = 'budget_bol'
        verbose_name = 'CBCO 项目记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.program_number} ({self.year})"

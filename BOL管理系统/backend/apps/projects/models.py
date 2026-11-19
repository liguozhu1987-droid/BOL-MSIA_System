# -*- coding: utf-8 -*-
"""项目主数据模型 - 映射 HRDB.CN_IE_BOL_programCodeInfor 表（只读）"""
from django.db import models


class ProgramInfo(models.Model):
    """项目主数据（HRDB 只读，对应 CN_IE_BOL_programCodeInfor）"""
    program_code = models.CharField(max_length=15, primary_key=True, db_column='programCode')
    product_type = models.CharField(max_length=50, blank=True, db_column='productType')
    process_type = models.CharField(max_length=50, blank=True, db_column='processType')
    program_name = models.CharField(max_length=200, blank=True, db_column='programName')
    customer_name = models.CharField(max_length=100, blank=True, db_column='customerName')
    related_program_code = models.CharField(max_length=15, blank=True, db_column='relatedProgramCode')
    program_status = models.CharField(max_length=30, blank=True, db_column='programStatus')
    location = models.CharField(max_length=20, blank=True)
    flow_finished = models.BooleanField(default=False, db_column='flow_finished')
    user_name = models.CharField(max_length=20, blank=True, db_column='userName')
    update_date = models.DateTimeField(null=True, blank=True, db_column='updateDate')

    class Meta:
        managed = False
        db_table = 'CN_IE_BOL_programCodeInfor'
        app_label = 'projects'
        verbose_name = '项目主数据'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.program_code} - {self.program_name}"


class BolUser(models.Model):
    """BOL 系统用户库（HRDB 只读，对应 CN_IE_BOL_Userdatabase）"""
    real_name = models.CharField(max_length=100, blank=True, db_column='realName')
    user_name = models.CharField(max_length=20, primary_key=True, db_column='userName')
    location = models.CharField(max_length=20, blank=True)
    station = models.CharField(max_length=50, blank=True)

    class Meta:
        managed = False
        db_table = 'CN_IE_BOL_Userdatabase'
        app_label = 'projects'
        verbose_name = '系统用户'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.real_name} ({self.user_name})"


class StationInfo(models.Model):
    """工位信息（HRDB 只读，对应 CN_IE_BOL_StationInfor）"""
    id = models.BigAutoField(primary_key=True)
    program_code = models.CharField(max_length=15, db_column='programCode')
    process = models.CharField(max_length=20)
    version = models.CharField(max_length=5)
    line_nr = models.CharField(max_length=15, db_column='lineNr')
    station_code = models.CharField(max_length=20, db_column='stationCode')
    station_name = models.CharField(max_length=50, db_column='stationName')
    station_type = models.CharField(max_length=20, db_column='stationType')
    wct_qty = models.IntegerField(default=0, db_column='wct_qty')
    bol_nr = models.CharField(max_length=50, db_column='BOL_Nr')
    user_name = models.CharField(max_length=20, blank=True, db_column='userName')
    update_date = models.DateTimeField(null=True, blank=True, db_column='updateDate')

    class Meta:
        managed = False
        db_table = 'CN_IE_BOL_StationInfor'
        app_label = 'projects'
        verbose_name = '工位信息'
        verbose_name_plural = verbose_name

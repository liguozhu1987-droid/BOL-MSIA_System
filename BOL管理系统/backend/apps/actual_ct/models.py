# -*- coding: utf-8 -*-
'''实测CT数据模型 - 映射 HRDB.CN_IE_CT_ 开头的表（只读）

注意：这些表只采集了 cycle time（CT），并非BOL。
BOL = CT × HC × (1+1/15) / OEE / 60，需要HC才能计算BOL。
因此本模块仅提供CT查询，BOL计算需结合BOL更新记录中的HC。
'''
from django.db import models


class RealCtExtract(models.Model):
    id = models.BigAutoField(primary_key=True)
    company = models.CharField(max_length=5, blank=True)
    project_name = models.CharField(db_column='projectName', max_length=50, blank=True)
    project_code = models.CharField(db_column='projectCode', max_length=30)
    line_nr = models.CharField(db_column='lineNr', max_length=30)
    station_nr = models.CharField(db_column='stationNr', max_length=30)
    cycle_time = models.DecimalField(db_column='cycleTime', max_digits=10, decimal_places=2, null=True, blank=True)
    count = models.IntegerField(default=0)
    update_time = models.DateTimeField(db_column='updateTime', null=True, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = '实测CT(工位级)'
        db_table = 'CN_IE_CT_realCT_extract'
        ordering = ['-update_time']
        managed = False

    def __str__(self):
        return f"{self.project_code}/{self.line_nr}/{self.station_nr} CT={self.cycle_time}s"


class RealCtExtractPerDay(models.Model):
    id = models.BigAutoField(primary_key=True)
    company = models.CharField(max_length=5, blank=True)
    project_name = models.CharField(db_column='projectName', max_length=50, blank=True)
    project_code = models.CharField(db_column='projectCode', max_length=30)
    line_nr = models.CharField(db_column='lineNr', max_length=30)
    station_nr = models.CharField(db_column='stationNr', max_length=30)
    cycle_time = models.DecimalField(db_column='cycleTime', max_digits=10, decimal_places=2, null=True, blank=True)
    start_time = models.DateField(db_column='startTime')
    update_time = models.DateTimeField(db_column='updateTime', null=True, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = '实测CT(按天)'
        db_table = 'CN_IE_CT_realCT_extract_perDay'
        ordering = ['-start_time', '-update_time']
        managed = False

    def __str__(self):
        return f"{self.project_code}/{self.line_nr}/{self.station_nr} {self.start_time} CT={self.cycle_time}s"


class BottleNeckCt(models.Model):
    id = models.BigAutoField(primary_key=True)
    company = models.CharField(max_length=5, blank=True)
    project_name = models.CharField(db_column='projectName', max_length=50, blank=True)
    project_code = models.CharField(db_column='projectCode', max_length=30)
    line_nr = models.CharField(db_column='lineNr', max_length=30)
    cycle_time_bottleneck = models.DecimalField(db_column='cycleTime_bottleNeck', max_digits=10, decimal_places=2, null=True, blank=True)
    update_time = models.DateTimeField(db_column='updateTime', null=True, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = '瓶颈工位CT'
        db_table = 'CN_IE_CT_bottleNeck_list'
        ordering = ['-update_time']
        managed = False

    def __str__(self):
        return f"{self.project_code}/{self.line_nr} 瓶颈CT={self.cycle_time_bottleneck}s"


class CtRealtimeStatus(models.Model):
    id = models.BigAutoField(primary_key=True)
    company = models.CharField(max_length=10)
    line_nr = models.CharField(db_column='lineNr', max_length=10)
    project_code = models.CharField(db_column='projectCode', max_length=20)
    state = models.CharField(max_length=5, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = '产线实时状态'
        db_table = 'CN_IE_CT_Realtime_status'
        managed = False

    def __str__(self):
        return f"{self.company}/{self.line_nr} {self.state}"


class ProjectAcquisition(models.Model):
    id = models.BigAutoField(primary_key=True)
    company = models.CharField(max_length=10)
    project_code = models.CharField(db_column='projectCode', max_length=30)
    project_name = models.CharField(db_column='projectName', max_length=50)
    line_nr = models.CharField(db_column='lineNr', max_length=30)
    status = models.BooleanField(null=True, blank=True)
    update_date = models.DateTimeField(db_column='updateDate', null=True, blank=True)
    user_name = models.CharField(db_column='userName', max_length=50, blank=True)
    revised_id = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = '项目采集配置'
        db_table = 'CN_IE_realTime_projects_acquisition'
        managed = False

    def __str__(self):
        return f"{self.company}/{self.project_code}/{self.line_nr}"


class KpiMonthlyHistory(models.Model):
    id = models.BigAutoField(db_column='nr', primary_key=True)
    year = models.IntegerField()
    month = models.IntegerField()
    location = models.CharField(max_length=10, blank=True)
    kpi_name = models.CharField(max_length=50)
    kpi_value = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    update_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = 'IE KPI月度历史'
        db_table = 'CN_AME_KPI_monthlyHistory'
        ordering = ['-year', '-month']
        managed = False


class BolImproveTarget(models.Model):
    id = models.BigAutoField(db_column='nr', primary_key=True)
    year = models.IntegerField()
    plant = models.CharField(max_length=20)
    process = models.CharField(max_length=20)
    program_code = models.CharField(db_column='programCode', max_length=20)
    program_name = models.CharField(db_column='programName', max_length=100)
    bol_budget = models.DecimalField(max_digits=12, decimal_places=4)
    target_bol = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    process_01_ct = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    process_01_hc = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    process_02_ct = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    process_02_hc = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    process_03_ct = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    process_03_hc = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    process_04_ct = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    process_04_hc = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    update_date = models.DateTimeField(db_column='updateDate', null=True, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = 'IE BOL改善目标'
        db_table = 'CN_AME_IE_BOL_improveTarget'
        ordering = ['-year', 'plant', 'program_code']
        managed = False

    def __str__(self):
        return f"{self.year} {self.plant}/{self.program_code}/{self.process} 目标{self.target_bol}"


class BolImproveTargetVolume(models.Model):
    id = models.BigAutoField(db_column='nr', primary_key=True)
    year = models.IntegerField()
    volume = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = 'actual_ct'
        verbose_name = 'IE BOL改善目标产量'
        db_table = 'CN_AME_IE_BOL_improveTarget_volume'
        ordering = ['year', 'id']
        managed = False

    def __str__(self):
        return f"{self.year} nr={self.id} volume={self.volume}"

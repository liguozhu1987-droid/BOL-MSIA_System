# -*- coding: utf-8 -*-
"""BOL 计算工具与常量定义"""


def calc_bol(ct: float, hc: float, oee: float) -> float:
    """
    BOL 标准计算公式：
        BOL = CT × HC × (1 + 1/15) / OEE
    其中：
        CT  标准循环周期（秒）
        HC  直接员工数量
        OEE 综合设备利用率（小数，如 0.85）
    返回：BOL 值（单位：分钟，因为 CT 秒 / 60 后×HC×系数/OEE 即为每件人工工时分钟数）
    说明：原始公式 CT 单位为秒，结果为分钟，故除以 60。
    """
    if not ct or not hc or not oee:
        return 0.0
    if oee == 0:
        return 0.0
    INDIRECT = 1.0 / 15.0
    return round(ct * hc * (1 + INDIRECT) / oee / 60.0, 4)


def calc_bol_gap(bol_a: float, bol_b: float) -> float:
    """计算两个 BOL 的差值（A - B）"""
    return round((bol_a or 0) - (bol_b or 0), 4)


def calc_labor_cost_gap(bol_gap: float, annual_volume: float, labor_rate: float) -> float:
    """
    年化人力成本差异测算：
        成本差异 = BOL差异(分钟/件) × 年产量(件/年)
                 × 工时单价(元/小时) / 60(分钟/小时)
    正值表示年化成本损失，负值表示年化成本节省。
    """
    if bol_gap is None or annual_volume is None or labor_rate is None:
        return 0.0
    return round(bol_gap * annual_volume * labor_rate / 60.0, 2)


# BOL 类型常量
BOL_TYPE_BUDGET = 'BUDGET'        # 年度预算 BOL
BOL_TYPE_DYNAMIC = 'DYNAMIC'      # 动态改善后 BOL（来自现有系统）
BOL_TYPE_SENSOR = 'SENSOR'        # 传感器实测 BOL
BOL_TYPE_QWS = 'QWS'              # 报价 BOL
BOL_TYPE_TRACKING = 'TRACKING'    # 跟踪目标 BOL

BOL_TYPE_CHOICES = [
    (BOL_TYPE_BUDGET, '年度预算'),
    (BOL_TYPE_DYNAMIC, '动态改善'),
    (BOL_TYPE_SENSOR, '传感器实测'),
    (BOL_TYPE_QWS, '报价QWS'),
    (BOL_TYPE_TRACKING, '跟踪目标'),
]

# 项目状态
PROGRAM_STATUS_CHOICES = [
    ('Quotation', '报价中'),
    ('Trial', '试产'),
    ('SOP', '量产'),
    ('EOP', '停产'),
]

# 地点
LOCATION_CHOICES = [
    ('SH Inalfa', '上海'),
    ('BJ Inalfa', '北京'),
    ('CJ Inalfa', '长春'),
]

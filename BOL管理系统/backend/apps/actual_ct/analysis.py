# -*- coding: utf-8 -*-
"""实测CT分析辅助模块。"""
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

import pyodbc
from django.db import connections


def normalize_ct_value(value):
    """将CT字段转换为正数浮点值。"""
    if value in (None, '', 'None', 'nan', 'NaN'):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    if number <= 0:
        return None
    return round(number, 2)


def normalize_date(value):
    """统一转换日期字段。"""
    if value in (None, '', 'None'):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        text = str(value).strip()
        if 'T' in text:
            return datetime.fromisoformat(text.replace('Z', '+00:00')).date()
        return datetime.strptime(text, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _calculate_iqr(values):
    """使用 IQR 与均值绝对偏差的组合规则计算异常阈值。"""
    if len(values) < 4:
        return None, None, None
    sorted_values = sorted(values)
    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 0:
        lower_half = sorted_values[:mid]
        upper_half = sorted_values[mid:]
    else:
        lower_half = sorted_values[:mid]
        upper_half = sorted_values[mid + 1:]
    q1 = median(lower_half) if lower_half else sorted_values[0]
    q3 = median(upper_half) if upper_half else sorted_values[-1]
    iqr = q3 - q1
    mean_value = sum(values) / len(values)
    mad = median([abs(v - mean_value) for v in values]) if values else 0
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    robust_upper_bound = max(upper_bound, mean_value + max(10.0, 2.5 * mad, 1.5 * iqr))
    robust_lower_bound = min(lower_bound, mean_value - max(10.0, 2.5 * mad, 1.5 * iqr))
    return q1, q3, (robust_lower_bound, robust_upper_bound)


def _build_diagnosis(values, daily_series, anomaly_points, months=3):
    """生成工位工时诊断结论、原因建议与改善机会。"""
    if not values:
        return {
            'summary': '当前工位暂无可用工时数据，建议先补齐最近 3 个月的采集记录。',
            'likely_causes': ['缺少有效采集数据，无法判断异常来源。'],
            'improvement_opportunities': ['补齐工时采集并确认工位编码与数据通道正常。'],
        }

    mean_value = sum(values) / len(values)
    median_value = median(values) if values else 0
    max_value = max(values)
    min_value = min(values)
    range_value = max_value - min_value

    likely_causes = []
    improvement_opportunities = []
    summary_parts = []

    if anomaly_points:
        summary_parts.append('检测到明显离群工时点，说明该工位存在波动或异常采集情况。')
        likely_causes.append('工位工时存在显著离群点，可能是节拍波动、设备/夹具异常或采集点跳变。')
        improvement_opportunities.append('优先排查异常时段对应的设备状态、夹具/治具及采集点稳定性，确认是否需要复测或校准。')
    else:
        summary_parts.append('当前工位工时整体较稳定，未出现明显离群点。')
        likely_causes.append('当前工时分布较集中，说明节拍稳定性较好。')
        improvement_opportunities.append('继续跟踪日均值和极差变化，重点关注后续是否出现节拍恶化。')

    if range_value > max(10.0, mean_value * 0.25):
        summary_parts.append('日间极差较大，说明工位节拍波动明显。')
        likely_causes.append('日均值与极差同时较大，可能与换线、换型、作业员差异或物料波动有关。')
        improvement_opportunities.append('梳理换线/换型、作业标准和物料准备节拍，寻找标准化与节拍平稳化机会。')

    if len(daily_series) >= 3 and any(item['range_ct'] > max(8.0, mean_value * 0.15) for item in daily_series):
        likely_causes.append('部分日期的极差显著上升，可能存在短时瓶颈或工艺切换造成的节拍抖动。')
        improvement_opportunities.append('对极差高发日期的工艺步骤、设备负荷和人员配置做回溯分析，找出改善点。')

    if max_value > median_value * 1.25:
        likely_causes.append('工位峰值明显高于中位数，说明存在短时高负荷或节拍拉长。')
        improvement_opportunities.append('针对峰值时段拆解工序步骤，识别是否存在等待、返工或辅助动作过长。')

    if not likely_causes:
        likely_causes.append('当前数据未显示典型异常模式。')
    if not improvement_opportunities:
        improvement_opportunities.append('继续采集并监控工位节拍变化，观察是否出现新的异常趋势。')

    summary = ' '.join(summary_parts)
    return {
        'summary': summary,
        'likely_causes': likely_causes,
        'improvement_opportunities': improvement_opportunities,
    }


def build_station_ct_analysis(records, months=3, bin_size=None):
    """构建工位级工时分析：直方图 + 均值/极差 + 异常点 + 诊断建议。

    Args:
        records: 原始记录列表
        months: 时间窗口（月数）
        bin_size: 直方图分组宽度（秒），如 5/10；为 None 时按 bin_count=10 均分
    """
    normalized_records = []
    for row in records:
        cycle_time = normalize_ct_value(row.get('cycle_time') or row.get('cycleTime'))
        update_time = row.get('update_time') or row.get('updateTime') or row.get('start_time') or row.get('startTime')
        if cycle_time is None:
            continue
        record_date = normalize_date(update_time)
        normalized_records.append({
            'cycle_time': cycle_time,
            'update_time': update_time,
            'date': record_date or date.today(),
        })

    values = [item['cycle_time'] for item in normalized_records]

    # 直方图渲染前剔除 IQR 异常值，避免离群点拉宽值域导致正常数据被挤压
    hist_values, filtered_out, iqr_lower, iqr_upper = filter_outliers_iqr(values)
    histogram = build_histogram(hist_values, bin_count=10, bin_size=bin_size)
    histogram['filtered_out'] = filtered_out
    histogram['iqr_lower'] = round(iqr_lower, 2) if iqr_lower is not None else None
    histogram['iqr_upper'] = round(iqr_upper, 2) if iqr_upper is not None else None
    histogram['total'] = len(values)

    daily_map = defaultdict(list)
    for item in normalized_records:
        day_key = item['date']
        daily_map[day_key].append(item['cycle_time'])

    daily_series = []
    for day_key in sorted(daily_map):
        day_values = daily_map[day_key]
        # 日级数据同时计算 mean 和 median（IE 最佳实践：median 抗离群）
        daily_series.append({
            'date': day_key.isoformat() if isinstance(day_key, date) else str(day_key),
            'mean_ct': round(sum(day_values) / len(day_values), 2),
            'median_ct': round(median(day_values), 2),
            'range_ct': round(max(day_values) - min(day_values), 2),
            'min_ct': round(min(day_values), 2),
            'max_ct': round(max(day_values), 2),
            'sample_count': len(day_values),
        })

    # IE 最佳实践：工位代表CT = P1-P99 + IQR 双重剔除后的中位数
    represent_ct_info = compute_represent_ct(values)

    # IE 最佳实践：休哈特 Xbar-R 控制图，判断过程是否受控
    xbar_r_chart = build_xbar_r_chart(daily_series)

    q1, q3, bounds = _calculate_iqr(values)
    lower_bound, upper_bound = bounds if bounds else (None, None)
    median_value = median(values) if values else 0
    anomaly_points = []
    if lower_bound is not None and upper_bound is not None:
        for item in normalized_records:
            if item['cycle_time'] < lower_bound or item['cycle_time'] > upper_bound:
                anomaly_points.append({
                    'date': item['date'].isoformat() if isinstance(item['date'], date) else str(item['date']),
                    'cycle_time': item['cycle_time'],
                })
    if not anomaly_points and values:
        for item in normalized_records:
            if item['cycle_time'] > median_value * 1.25 or item['cycle_time'] < median_value * 0.8:
                anomaly_points.append({
                    'date': item['date'].isoformat() if isinstance(item['date'], date) else str(item['date']),
                    'cycle_time': item['cycle_time'],
                })

    diagnosis = _build_diagnosis(values, daily_series, anomaly_points, months=months)

    # 诊断建议补充控制图结论
    if diagnosis.get('summary'):
        diagnosis['summary'] = diagnosis['summary'] + ' ' + xbar_r_chart['message']

    return {
        'period': {
            'months': max(months, 1),
        },
        'sample_count': len(normalized_records),
        'represent_ct': represent_ct_info['represent_ct'],
        'represent_ct_info': represent_ct_info,
        'histogram': histogram,
        'daily_series': daily_series,
        'xbar_r_chart': xbar_r_chart,
        'anomaly_count': len(anomaly_points),
        'anomaly_points': anomaly_points,
        'anomaly_thresholds': {
            'q1': round(q1, 2) if q1 is not None else None,
            'q3': round(q3, 2) if q3 is not None else None,
            'lower_bound': round(lower_bound, 2) if lower_bound is not None else None,
            'upper_bound': round(upper_bound, 2) if upper_bound is not None else None,
        },
        'diagnosis': diagnosis,
    }


def build_histogram(values, bin_count=10, bin_size=None):
    """构建直方图分箱。

    支持两种分组模式：
    - bin_size 模式（优先）：按固定宽度（如 5s/10s）分组，便于横向对比
    - bin_count 模式（默认）：按固定组数均分值域（旧行为，保留兼容）
    """
    values = [float(v) for v in values if v is not None]
    if not values:
        return {
            'categories': [],
            'counts': [],
            'bin_count': bin_count,
            'bin_size': bin_size,
            'min_value': 0,
            'max_value': 0,
            'total': 0,
            'filtered_out': 0,
        }

    min_value = min(values)
    max_value = max(values)

    # 单一值退化
    if min_value == max_value:
        return {
            'categories': [f'{min_value:.1f}'],
            'counts': [len(values)],
            'bin_count': 1,
            'bin_size': bin_size,
            'min_value': round(min_value, 2),
            'max_value': round(max_value, 2),
            'total': len(values),
            'filtered_out': 0,
        }

    # bin_size 模式：按固定宽度分组（起点对齐到 bin_size 的整数倍）
    if bin_size and bin_size > 0:
        # 起点对齐到 bin_size 整数倍，便于阅读（如 0/5/10/15...）
        start = math.floor(min_value / bin_size) * bin_size
        end = math.ceil(max_value / bin_size) * bin_size
        if end <= start:
            end = start + bin_size
        num_bins = max(int(round((end - start) / bin_size)), 1)
        categories = []
        counts = [0] * num_bins
        for idx in range(num_bins):
            lo = start + idx * bin_size
            hi = lo + bin_size
            if idx == num_bins - 1:
                categories.append(f'{lo:.0f}-{end:.0f}')
            else:
                categories.append(f'{lo:.0f}-{hi:.0f}')
        for value in values:
            idx = int((value - start) / bin_size)
            if idx < 0:
                idx = 0
            elif idx >= num_bins:
                idx = num_bins - 1
            counts[idx] += 1
        return {
            'categories': categories,
            'counts': counts,
            'bin_count': num_bins,
            'bin_size': bin_size,
            'min_value': round(min_value, 2),
            'max_value': round(max_value, 2),
            'total': len(values),
            'filtered_out': 0,
        }

    # bin_count 模式（默认，按组数均分值域）
    step = (max_value - min_value) / max(bin_count, 1)
    categories = []
    counts = [0] * max(bin_count, 1)
    for idx in range(max(bin_count, 1)):
        lo = min_value + idx * step
        hi = min_value + (idx + 1) * step
        if idx == max(bin_count, 1) - 1:
            categories.append(f'{lo:.1f}-{max_value:.1f}')
        else:
            categories.append(f'{lo:.1f}-{hi:.1f}')

    for value in values:
        idx = int((value - min_value) / step)
        if idx >= max(bin_count, 1):
            idx = max(bin_count, 1) - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1

    return {
        'categories': categories,
        'counts': counts,
        'bin_count': max(bin_count, 1),
        'bin_size': bin_size,
        'min_value': round(min_value, 2),
        'max_value': round(max_value, 2),
        'total': len(values),
        'filtered_out': 0,
    }


def filter_outliers_iqr(values):
    """使用 IQR 规则剔除异常值，返回 (保留值列表, 剔除数量, 下界, 上界)。

    用于直方图渲染前的异常剔除，避免离群点拉宽值域导致正常数据被挤压。
    """
    if not values or len(values) < 4:
        return list(values or []), 0, None, None
    sorted_values = sorted(values)
    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 0:
        lower_half = sorted_values[:mid]
        upper_half = sorted_values[mid:]
    else:
        lower_half = sorted_values[:mid]
        upper_half = sorted_values[mid + 1:]
    q1 = median(lower_half) if lower_half else sorted_values[0]
    q3 = median(upper_half) if upper_half else sorted_values[-1]
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    kept = [v for v in values if lower_bound <= v <= upper_bound]
    filtered_out = len(values) - len(kept)
    return kept, filtered_out, lower_bound, upper_bound


def percentile(values, p):
    """计算百分位数（线性插值法，与 numpy.percentile 默认一致）。

    Args:
        values: 数值列表
        p: 百分位（0-100）
    """
    if not values:
        return None
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    # 线性插值：索引 = (n-1) * p/100
    idx = (n - 1) * (p / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(sorted_values[lo])
    frac = idx - lo
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def filter_outliers_percentile(values, lower_pct=1, upper_pct=99):
    """使用百分位剔除异常值，返回 (保留值列表, 剔除数量, 下界, 上界)。

    国际IE最佳实践：P1-P99 百分位剔除，去除两端极值后保留核心分布。
    比 Tukey IQR 更保守，适合工位CT代表值计算（避免误删有效数据）。

    Args:
        values: 数值列表
        lower_pct: 下百分位（默认 1，即 P1）
        upper_pct: 上百分位（默认 99，即 P99）
    """
    if not values or len(values) < 4:
        return list(values or []), 0, None, None
    lower_bound = percentile(values, lower_pct)
    upper_bound = percentile(values, upper_pct)
    if lower_bound is None or upper_bound is None:
        return list(values), 0, None, None
    kept = [v for v in values if lower_bound <= v <= upper_bound]
    if not kept:
        # 极端情况：所有值都落在边界外（理论上不会发生），回退到原数据
        return list(values), 0, lower_bound, upper_bound
    filtered_out = len(values) - len(kept)
    return kept, filtered_out, lower_bound, upper_bound


def compute_represent_ct(values):
    """计算工位代表CT：P1-P99 百分位剔除 + Tukey IQR 双重过滤后取中位数。

    国际IE最佳实践组合拳：
        1. P1-P99 百分位剔除：去除两端极值
        2. Tukey IQR (1.5×IQR)：进一步剔除箱线图外的离群点
        3. 取剩余数据的中位数作为工位代表CT（抗离群点能力强于均值）

    Returns:
        dict: {
            'represent_ct': 工位代表CT（中位数）,
            'median': 中位数,
            'mean': 均值（剔除后，供参考）,
            'min': 最小值（剔除后）,
            'max': 最大值（剔除后）,
            'sample_count': 原始样本数,
            'kept_count': 保留样本数,
            'filtered_out': 剔除总数,
            'p1': P1 百分位,
            'p99': P99 百分位,
            'iqr_lower': IQR 下界,
            'iqr_upper': IQR 上界,
        }
    """
    if not values:
        return {
            'represent_ct': None, 'median': None, 'mean': None,
            'min': None, 'max': None, 'sample_count': 0, 'kept_count': 0,
            'filtered_out': 0, 'p1': None, 'p99': None,
            'iqr_lower': None, 'iqr_upper': None,
        }

    original_count = len(values)
    values = [float(v) for v in values if v is not None and v > 0]

    # 第一步：P1-P99 百分位剔除
    kept, p_filtered, p1, p99 = filter_outliers_percentile(values, 1, 99)

    # 第二步：Tukey IQR 剔除
    kept, iqr_filtered, iqr_lower, iqr_upper = filter_outliers_iqr(kept)

    if not kept:
        kept = values  # 极端情况回退

    return {
        'represent_ct': round(median(kept), 2),
        'median': round(median(kept), 2),
        'mean': round(sum(kept) / len(kept), 2),
        'min': round(min(kept), 2),
        'max': round(max(kept), 2),
        'sample_count': original_count,
        'kept_count': len(kept),
        'filtered_out': original_count - len(kept),
        'p1': round(p1, 2) if p1 is not None else None,
        'p99': round(p99, 2) if p99 is not None else None,
        'iqr_lower': round(iqr_lower, 2) if iqr_lower is not None else None,
        'iqr_upper': round(iqr_upper, 2) if iqr_upper is not None else None,
    }


# 休哈特控制图系数表（基于子组样本量 n）
# 来源：ASTM/ISO/ANSI 标准控制图系数表
# A2: 均值图控制限系数；D3: 极差图下控制限系数；D4: 极差图上控制限系数
_SHEWHART_COEFFICIENTS = {
    2: {'A2': 1.880, 'D3': 0.000, 'D4': 3.267},
    3: {'A2': 1.023, 'D3': 0.000, 'D4': 2.574},
    4: {'A2': 0.729, 'D3': 0.000, 'D4': 2.282},
    5: {'A2': 0.577, 'D3': 0.000, 'D4': 2.114},
    6: {'A2': 0.483, 'D3': 0.000, 'D4': 2.004},
    7: {'A2': 0.419, 'D3': 0.076, 'D4': 1.924},
    8: {'A2': 0.373, 'D3': 0.136, 'D4': 1.864},
    9: {'A2': 0.337, 'D3': 0.184, 'D4': 1.816},
    10: {'A2': 0.308, 'D3': 0.223, 'D4': 1.777},
    11: {'A2': 0.285, 'D3': 0.256, 'D4': 1.744},
    12: {'A2': 0.266, 'D3': 0.283, 'D4': 1.717},
}


def _get_shewhart_coefficients(n):
    """获取休哈特控制图系数，n>12 时按 n=12 处理（保守估计）。"""
    if n < 2:
        return None
    return _SHEWHART_COEFFICIENTS.get(min(n, 12))


def build_xbar_r_chart(daily_series):
    """构建休哈特 Xbar-R 控制图（日级 CT 均值-极差控制图）。

    国际IE最佳实践：用控制图判断工位过程是否处于统计受控状态。
    - Xbar 图：监控日均值是否稳定（过程中心）
    - R 图：监控日极差是否稳定（过程波动）

    Args:
        daily_series: build_station_ct_analysis 产出的日级序列
            每项需含 mean_ct（日均值）、range_ct（日极差）、sample_count

    Returns:
        dict: {
            'xbar_chart': {'cl': 中心线, 'ucl': 上控制限, 'lcl': 下控制限, 'out_of_control_points': [...]},
            'r_chart': {'cl': 中心线, 'ucl': 上控制限, 'lcl': 下控制限, 'out_of_control_points': [...]},
            'is_in_control': 过程是否受控,
            'n_subgroups': 子组数,
            'xbar_bar': 总均值,
            'r_bar': 平均极差,
            'rules_violated': 违反的判异规则列表,
        }
    """
    if not daily_series or len(daily_series) < 2:
        return {
            'xbar_chart': {'cl': None, 'ucl': None, 'lcl': None, 'out_of_control_points': []},
            'r_chart': {'cl': None, 'ucl': None, 'lcl': None, 'out_of_control_points': []},
            'is_in_control': True,
            'n_subgroups': len(daily_series) if daily_series else 0,
            'xbar_bar': None,
            'r_bar': None,
            'rules_violated': [],
            'message': '子组数不足（需≥2个日级数据点）',
        }

    # 取有有效均值的子组
    valid_groups = [
        (s['date'], s['mean_ct'], s.get('range_ct', 0), s.get('sample_count', 1))
        for s in daily_series
        if s.get('mean_ct') is not None
    ]
    if len(valid_groups) < 2:
        return {
            'xbar_chart': {'cl': None, 'ucl': None, 'lcl': None, 'out_of_control_points': []},
            'r_chart': {'cl': None, 'ucl': None, 'lcl': None, 'out_of_control_points': []},
            'is_in_control': True,
            'n_subgroups': len(valid_groups),
            'xbar_bar': None,
            'r_bar': None,
            'rules_violated': [],
            'message': '有效子组不足',
        }

    # 平均子组样本量（用于选系数）
    avg_n = sum(g[3] for g in valid_groups) / len(valid_groups)
    n_for_coeff = max(2, min(int(round(avg_n)), 12))
    coeff = _get_shewhart_coefficients(n_for_coeff)
    if not coeff:
        return {
            'xbar_chart': {'cl': None, 'ucl': None, 'lcl': None, 'out_of_control_points': []},
            'r_chart': {'cl': None, 'ucl': None, 'lcl': None, 'out_of_control_points': []},
            'is_in_control': True,
            'n_subgroups': len(valid_groups),
            'xbar_bar': None,
            'r_bar': None,
            'rules_violated': [],
            'message': '无法获取控制图系数',
        }

    xbar_bar = sum(g[1] for g in valid_groups) / len(valid_groups)
    r_bar = sum(g[2] for g in valid_groups) / len(valid_groups)

    A2 = coeff['A2']
    D3 = coeff['D3']
    D4 = coeff['D4']

    # Xbar 图控制限：CL = xbar_bar, UCL/LCL = xbar_bar ± A2 * Rbar
    xbar_cl = round(xbar_bar, 2)
    xbar_ucl = round(xbar_bar + A2 * r_bar, 2)
    xbar_lcl = round(xbar_bar - A2 * r_bar, 2)

    # R 图控制限：CL = Rbar, UCL = D4*Rbar, LCL = D3*Rbar
    r_cl = round(r_bar, 2)
    r_ucl = round(D4 * r_bar, 2)
    r_lcl = round(D3 * r_bar, 2)

    # 判异规则检验
    xbar_ooc = []  # 越界点
    r_ooc = []
    rules_violated = []

    for date_str, xbar, r, _ in valid_groups:
        if xbar > xbar_ucl or xbar < xbar_lcl:
            xbar_ooc.append({'date': date_str, 'value': xbar, 'rule': '单点越界'})
        if r > r_ucl or (r_lcl > 0 and r < r_lcl):
            r_ooc.append({'date': date_str, 'value': r, 'rule': '单点越界'})

    if xbar_ooc:
        rules_violated.append('Xbar图单点越界')
    if r_ooc:
        rules_violated.append('R图单点越界')

    # 规则2：连续7点在中心线同侧
    xbar_values = [g[1] for g in valid_groups]
    consecutive_same_side = 1
    same_side_dir = 1 if xbar_values[0] > xbar_bar else -1
    for v in xbar_values[1:]:
        side = 1 if v > xbar_bar else -1
        if side == same_side_dir:
            consecutive_same_side += 1
            if consecutive_same_side >= 7:
                rules_violated.append('Xbar图连续7点同侧')
                break
        else:
            consecutive_same_side = 1
            same_side_dir = side

    # 规则3：连续7点递增或递减（趋势）
    if len(xbar_values) >= 7:
        trend_up = trend_down = 1
        for i in range(1, len(xbar_values)):
            if xbar_values[i] > xbar_values[i - 1]:
                trend_up += 1
                trend_down = 1
            elif xbar_values[i] < xbar_values[i - 1]:
                trend_down += 1
                trend_up = 1
            else:
                trend_up = trend_down = 1
            if trend_up >= 7 or trend_down >= 7:
                rules_violated.append('Xbar图连续7点趋势')
                break

    is_in_control = len(rules_violated) == 0

    return {
        'xbar_chart': {
            'cl': xbar_cl,
            'ucl': xbar_ucl,
            'lcl': xbar_lcl,
            'out_of_control_points': xbar_ooc,
        },
        'r_chart': {
            'cl': r_cl,
            'ucl': r_ucl,
            'lcl': r_lcl,
            'out_of_control_points': r_ooc,
        },
        'is_in_control': is_in_control,
        'n_subgroups': len(valid_groups),
        'xbar_bar': xbar_cl,
        'r_bar': r_cl,
        'rules_violated': rules_violated,
        'message': '过程受控' if is_in_control else f'过程失控：{", ".join(rules_violated)}',
    }


def summarize_dimension(records, field_name):
    """按维度聚合，返回名称/数量/中位数CT（IE 最佳实践：P1-P99 + IQR 剔除后中位数）。"""
    grouped = defaultdict(list)
    for record in records:
        key = record.get(field_name) or '未知'
        grouped[key].append(record)

    items = []
    for key, group in sorted(grouped.items(), key=lambda item: item[0]):
        values = [item['cycle_time'] for item in group if item.get('cycle_time') is not None]
        if not values:
            continue
        rep = compute_represent_ct(values)
        items.append({
            'name': str(key),
            'count': len(group),
            'avg_ct': rep['represent_ct'],  # 兼容字段：代表CT（中位数）
            'median_ct': rep['median'],
            'mean_ct': rep['mean'],
            'min_ct': rep['min'],
            'max_ct': rep['max'],
            'filtered_out': rep['filtered_out'],
        })
    return items


def summarize_station_level(records):
    """以工位为最小颗粒度聚合CT（IE 最佳实践：P1-P99 + IQR 剔除后中位数）。"""
    grouped = defaultdict(list)
    for record in records:
        key = (
            record.get('company') or '未知',
            record.get('line_nr') or '未知',
            record.get('project_code') or '未知',
            record.get('station_nr') or '未知',
        )
        grouped[key].append(record)

    items = []
    for (company, line_nr, project_code, station_nr), group in sorted(grouped.items(), key=lambda item: item[0]):
        values = [item['cycle_time'] for item in group if item.get('cycle_time') is not None]
        if not values:
            continue
        rep = compute_represent_ct(values)
        items.append({
            'company': str(company),
            'line_nr': str(line_nr),
            'project_code': str(project_code),
            'station_nr': str(station_nr),
            'name': f"{str(line_nr)}/{str(station_nr)}",
            'count': len(group),
            'avg_ct': rep['represent_ct'],  # 兼容字段：代表CT（中位数）
            'median_ct': rep['median'],
            'mean_ct': rep['mean'],
            'min_ct': rep['min'],
            'max_ct': rep['max'],
            'kept_count': rep['kept_count'],
            'filtered_out': rep['filtered_out'],
        })

    items.sort(key=lambda item: item['avg_ct'], reverse=True)
    return items


def build_line_balance(station_items):
    """根据工位代表CT（中位数）计算线平衡率。"""
    if not station_items:
        return {
            'rate': 0,
            'station_count': 0,
            'bottleneck_station': '-',
            'bottleneck_ct': 0,
            'total_ct': 0,
        }

    values = [item['avg_ct'] for item in station_items if item.get('avg_ct') is not None]
    if not values:
        return {
            'rate': 0,
            'station_count': 0,
            'bottleneck_station': '-',
            'bottleneck_ct': 0,
            'total_ct': 0,
        }

    bottleneck_station = max(station_items, key=lambda item: item['avg_ct'])
    bottleneck_ct = float(bottleneck_station['avg_ct'])
    total_ct = sum(values)
    rate = round((total_ct / (bottleneck_ct * len(values))) * 100, 2) if bottleneck_ct > 0 else 0
    return {
        'rate': rate,
        'station_count': len(values),
        'bottleneck_station': bottleneck_station['name'],
        'bottleneck_ct': round(bottleneck_ct, 2),
        'total_ct': round(total_ct, 2),
    }


def quote_sql_value(value):
    """将 Python 值转为 SQL 字面量。"""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


# OPE 视图数据清洗的 SQL WHERE 子句
OPE_CLEAN_WHERE = (
    "((projectCode LIKE 'T%' OR projectCode LIKE 'S%') "
    "OR (projectCode LIKE 't%' OR projectCode LIKE 's%')) "
    "AND projectCode IS NOT NULL AND LTRIM(RTRIM(projectCode)) <> '' "
    "AND projectName IS NOT NULL AND LTRIM(RTRIM(projectName)) <> '' "
    "AND lineNr IS NOT NULL AND LTRIM(RTRIM(lineNr)) <> '' "
    "AND stationNr IS NOT NULL AND LTRIM(RTRIM(stationNr)) <> '' "
    "AND cycleTime IS NOT NULL "
    "AND cycleTime >= 10 AND cycleTime <= 1000"
)


def get_ope_connection():
    """连接到 InalfaCNDM 数据仓库，访问 OPE.V_fact_cn_realTimeCT_overView 视图"""
    return pyodbc.connect(
        'Driver={SQL Server};'
        'Server=172.26.2.212,1433;'
        'Database=InalfaCNDM;'
        'UID=srv_DWS_OPE;'
        'PWD=j+1nrC4ZlZ;'
        'TrustServerCertificate=yes;',
        timeout=30,
    )


def execute_ope_query(sql, params=None):
    """执行 OPE 视图查询，返回 dict 列表"""
    conn = None
    cursor = None
    try:
        conn = get_ope_connection()
        # pyodbc 原生 Cursor 不支持 timeout 属性（仅 mssql-django 游标包装器支持），
        # 查询超时需设置在连接上：conn.timeout（秒）
        conn.timeout = 120
        cursor = conn.cursor()
        cursor.execute(sql, params or [])
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def build_ct_analysis_payload(rows, filters=None, months=3, bin_count=10, start_date=None, end_date=None):
    """基于原始行数据构造CT分析结果。"""
    filters = filters or {}
    normalized_filters = {
        'company': (filters.get('company') or '').strip(),
        'project_code': (filters.get('project_code') or '').strip(),
        'line_nr': (filters.get('line_nr') or '').strip(),
        'station_nr': (filters.get('station_nr') or '').strip(),
    }

    if start_date is None:
        start_date = (date.today() - timedelta(days=max(months, 1) * 30)).replace(day=1)
    if end_date is None:
        end_date = date.today()

    cleaned_records = []
    for row in rows:
        company = str(row.get('company') or row.get('companyCode') or '').strip()
        line_nr = str(row.get('line_nr') or row.get('lineNr') or '').strip()
        project_code = str(row.get('project_code') or row.get('projectCode') or '').strip()
        project_name = str(row.get('project_name') or row.get('projectName') or '').strip()
        station_nr = str(row.get('station_nr') or row.get('stationNr') or '').strip()
        cycle_time = normalize_ct_value(row.get('cycle_time') or row.get('cycleTime'))
        record_date = normalize_date(row.get('start_time') or row.get('startTime'))

        if not cycle_time:
            continue
        if record_date and start_date and record_date < start_date:
            continue
        if record_date and end_date and record_date > end_date:
            continue

        if normalized_filters['company'] and company != normalized_filters['company']:
            continue
        if normalized_filters['project_code'] and project_code != normalized_filters['project_code']:
            continue
        if normalized_filters['line_nr'] and line_nr != normalized_filters['line_nr']:
            continue
        if normalized_filters['station_nr'] and station_nr != normalized_filters['station_nr']:
            continue

        cleaned_records.append({
            'company': company,
            'line_nr': line_nr,
            'project_code': project_code,
            'project_name': project_name,
            'station_nr': station_nr,
            'cycle_time': cycle_time,
            'start_time': record_date,
        })

    values = [record['cycle_time'] for record in cleaned_records]
    histogram = build_histogram(values, bin_count=max(bin_count, 1))
    station_items = summarize_station_level(cleaned_records)
    line_balance = build_line_balance(station_items)

    return {
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'months': months,
        },
        'stats': {
            'source_count': len(rows),
            'cleaned_count': len(cleaned_records),
            'invalid_count': max(len(rows) - len(cleaned_records), 0),
            'station_count': len(station_items),
            'line_balance_rate': line_balance['rate'],
            'bottleneck_station': line_balance['bottleneck_station'],
            'bottleneck_ct': line_balance['bottleneck_ct'],
        },
        'histogram': histogram,
        'station_analysis': {
            'items': station_items,
            'line_balance': line_balance,
        },
        'drilldown': {
            'factory': summarize_dimension(cleaned_records, 'company'),
            'line': summarize_dimension(cleaned_records, 'line_nr'),
            'project': summarize_dimension(cleaned_records, 'project_code'),
            'station': summarize_dimension(cleaned_records, 'station_nr'),
        },
    }


def fetch_filter_options(filters=None, months=3):
    """从 SQL Server 视图提取级联筛选项。"""
    filters = filters or {}
    end_date = date.today()
    start_date = end_date - timedelta(days=max(months, 1) * 30)

    def fetch_distinct(column_name, label_column=None, extra_filters=None):
        extra_filters = extra_filters or {}
        query = f"SELECT DISTINCT {column_name} AS value"
        if label_column and label_column != column_name:
            query += f", {label_column} AS label"
        query += f" FROM OPE.V_fact_cn_realTimeCT_overView WHERE [Update Date] >= {quote_sql_value(start_date)} AND [Update Date] <= {quote_sql_value(end_date)}"

        clauses = []
        if extra_filters.get('company'):
            clauses.append(f"company = {quote_sql_value(extra_filters['company'])}")
        if extra_filters.get('line_nr'):
            clauses.append(f"lineNr = {quote_sql_value(extra_filters['line_nr'])}")
        if extra_filters.get('project_code'):
            clauses.append(f"projectCode = {quote_sql_value(extra_filters['project_code'])}")
        if extra_filters.get('station_nr'):
            clauses.append(f"stationNr = {quote_sql_value(extra_filters['station_nr'])}")
        if clauses:
            query += ' AND ' + ' AND '.join(clauses)
        query += ' ORDER BY value'

        conn = None
        cursor = None
        try:
            conn = pyodbc.connect(
                'Driver={SQL Server};'
                'Server=172.26.2.212,1433;'
                'Database=InalfaCNDM;'
                'UID=srv_DWS_OPE;'
                'PWD=j+1nrC4ZlZ;'
                'TrustServerCertificate=yes;',
                timeout=30,
            )
            # pyodbc 原生 Cursor 不支持 timeout 属性，查询超时设置在连接上
            conn.timeout = 120
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            results = []
            for row in rows:
                value = row[0]
                if value in (None, ''):
                    continue
                label = value if len(row) < 2 or row[1] in (None, '') else str(row[1])
                results.append({'value': str(value), 'label': str(label)})
            return results
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    company_filters = {k: v for k, v in filters.items() if v}
    line_filters = {**company_filters}
    project_filters = {**company_filters}
    station_filters = {**company_filters}

    if filters.get('company'):
        project_filters['company'] = filters['company']
        station_filters['company'] = filters['company']
    if filters.get('line_nr'):
        project_filters['line_nr'] = filters['line_nr']
        station_filters['line_nr'] = filters['line_nr']
    if filters.get('project_code'):
        station_filters['project_code'] = filters['project_code']

    return {
        'company': fetch_distinct('company', None, {}),
        'line_nr': fetch_distinct('lineNr', None, {'company': filters.get('company') or None}),
        'project_code': fetch_distinct('projectCode', 'projectName', {
            'company': filters.get('company') or None,
            'line_nr': filters.get('line_nr') or None,
        }),
        'station_nr': fetch_distinct('stationNr', None, {
            'company': filters.get('company') or None,
            'line_nr': filters.get('line_nr') or None,
            'project_code': filters.get('project_code') or None,
        }),
    }


def fetch_ct_analysis_from_db(filters=None, months=3, bin_count=10):
    """从 SQL Server 视图读取并分析近期CT数据。"""
    filters = filters or {}
    end_date = date.today()
    start_date = end_date - timedelta(days=max(months, 1) * 30)

    query = """
        SELECT
            companyCode AS company_code,
            company,
            lineNr AS line_nr,
            projectCode AS project_code,
            projectName AS project_name,
            stationNr AS station_nr,
            cycleTime AS cycle_time,
            startTime AS start_time,
            [Update Date] AS update_time
        FROM OPE.V_fact_cn_realTimeCT_overView
        WHERE [Update Date] >= {start} AND [Update Date] <= {end}
    """
    clauses = []
    if filters.get('company'):
        clauses.append("company = {}".format(quote_sql_value(filters['company'])))
    if filters.get('project_code'):
        clauses.append("projectCode = {}".format(quote_sql_value(filters['project_code'])))
    if filters.get('line_nr'):
        clauses.append("lineNr = {}".format(quote_sql_value(filters['line_nr'])))
    if filters.get('station_nr'):
        clauses.append("stationNr = {}".format(quote_sql_value(filters['station_nr'])))

    if clauses:
        query += ' AND ' + ' AND '.join(clauses)

    query += ' ORDER BY startTime'

    sql = query.format(start=quote_sql_value(start_date), end=quote_sql_value(end_date))

    conn = None
    cursor = None
    try:
        conn = pyodbc.connect(
            'Driver={SQL Server};'
            'Server=172.26.2.212,1433;'
            'Database=InalfaCNDM;'
            'UID=srv_DWS_OPE;'
            'PWD=j+1nrC4ZlZ;'
            'TrustServerCertificate=yes;',
            timeout=30,
        )
        # pyodbc 原生 Cursor 不支持 timeout 属性，查询超时设置在连接上
        conn.timeout = 120
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return build_ct_analysis_payload(rows, filters=filters, months=months, bin_count=bin_count, start_date=start_date, end_date=end_date)
    except Exception:
        try:
            cursor = connections['hrdb'].cursor()
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return build_ct_analysis_payload(rows, filters=filters, months=months, bin_count=bin_count, start_date=start_date, end_date=end_date)
        except Exception:
            raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

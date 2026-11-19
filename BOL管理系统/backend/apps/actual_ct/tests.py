from datetime import datetime
import sys
import unittest

sys.path.insert(0, 'backend')

from apps.actual_ct.analysis import (
    build_station_ct_analysis, compute_represent_ct,
    filter_outliers_percentile, filter_outliers_iqr,
    percentile, build_xbar_r_chart,
)
from apps.actual_ct.views import dedupe_project_options


class StationCtAnalysisTests(unittest.TestCase):
    def test_build_station_ct_analysis_returns_histogram_and_daily_range_series(self):
        records = [
            {'cycle_time': 20, 'update_time': datetime(2026, 6, 1, 12, 0, 0)},
            {'cycle_time': 24, 'update_time': datetime(2026, 6, 1, 14, 0, 0)},
            {'cycle_time': 50, 'update_time': datetime(2026, 6, 2, 10, 0, 0)},
            {'cycle_time': 22, 'update_time': datetime(2026, 6, 3, 8, 0, 0)},
            {'cycle_time': 26, 'update_time': datetime(2026, 6, 4, 9, 0, 0)},
        ]

        payload = build_station_ct_analysis(records, months=3)

        self.assertEqual(payload['sample_count'], 5)
        self.assertEqual(payload['histogram']['counts'][0], 2)
        self.assertEqual(payload['daily_series'][0]['date'], '2026-06-01')
        # 日级同时有 mean_ct 和 median_ct
        self.assertEqual(payload['daily_series'][0]['mean_ct'], 22.0)
        self.assertEqual(payload['daily_series'][0]['median_ct'], 22.0)
        self.assertEqual(payload['daily_series'][0]['range_ct'], 4.0)
        self.assertEqual(payload['daily_series'][1]['mean_ct'], 50.0)
        self.assertEqual(payload['daily_series'][1]['median_ct'], 50.0)
        # 工位代表CT（P1-P99 + IQR 剔除后的中位数）
        self.assertIsNotNone(payload['represent_ct'])
        self.assertIn('represent_ct_info', payload)
        # Xbar-R 控制图
        self.assertIn('xbar_r_chart', payload)
        self.assertIn('is_in_control', payload['xbar_r_chart'])
        self.assertGreater(payload['anomaly_count'], 0)
        self.assertIn('异常', payload['diagnosis']['summary'])
        self.assertTrue(payload['diagnosis']['likely_causes'])
        self.assertTrue(payload['diagnosis']['improvement_opportunities'])

    def test_build_station_ct_analysis_handles_empty_records(self):
        payload = build_station_ct_analysis([], months=3)

        self.assertEqual(payload['sample_count'], 0)
        self.assertEqual(payload['histogram']['counts'], [])
        self.assertEqual(payload['daily_series'], [])
        self.assertEqual(payload['anomaly_count'], 0)

    def test_dedupe_project_options_removes_duplicate_codes(self):
        payload = [
            {'code': 'T6763', 'name': '项目A'},
            {'code': 'T6763', 'name': '项目A-副本'},
            {'code': 'T6764', 'name': '项目B'},
            {'code': 'T6764', 'name': '项目B-副本'},
        ]

        result = dedupe_project_options(payload)

        self.assertEqual(result, [
            {'code': 'T6763', 'name': '项目A'},
            {'code': 'T6764', 'name': '项目B'},
        ])


class IeBestPracticeTests(unittest.TestCase):
    """IE 最佳实践：P1-P99 百分位剔除 + Tukey IQR + 中位数 + 休哈特控制图"""

    def test_percentile_linear_interpolation(self):
        """验证百分位线性插值"""
        self.assertEqual(percentile([10, 20, 30, 40, 50], 0), 10.0)
        self.assertEqual(percentile([10, 20, 30, 40, 50], 100), 50.0)
        self.assertEqual(percentile([10, 20, 30, 40, 50], 50), 30.0)
        # P1 应该接近最小值
        self.assertAlmostEqual(percentile([10, 20, 30, 40, 50], 1), 10.4, places=1)

    def test_filter_outliers_percentile_removes_extremes(self):
        """P1-P99 应剔除两端极值（小样本下较保守，主要靠 IQR 兜底）"""
        # 大样本下 P1-P99 能稳定剔除两端 1% 的点
        values = list(range(30, 41)) * 10 + [200, 250]  # 110 个正常 + 2 个离群
        kept, filtered_out, lo, hi = filter_outliers_percentile(values, 1, 99)
        self.assertGreater(filtered_out, 0)
        # 200 和 250 应被 P99 剔除
        self.assertNotIn(200, kept)
        self.assertNotIn(250, kept)
        # 正常值应保留
        self.assertIn(35, kept)

    def test_filter_outliers_iqr_removes_outliers(self):
        """Tukey IQR 应剔除 1.5×IQR 外的点"""
        # 数据集中在 30-40，加一个 200 离群点
        values = [30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 200]
        kept, filtered_out, lo, hi = filter_outliers_iqr(values)
        self.assertGreater(filtered_out, 0)
        self.assertNotIn(200, kept)

    def test_compute_represent_ct_uses_median_after_double_filter(self):
        """工位代表CT = P1-P99 + IQR 双重剔除后的中位数"""
        # 正常值在 30-40，加几个离群点
        values = [30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 100, 200]
        rep = compute_represent_ct(values)
        # 代表CT 应该在 30-40 之间（中位数），不受 100/200 影响
        self.assertGreaterEqual(rep['represent_ct'], 30)
        self.assertLessEqual(rep['represent_ct'], 40)
        # 应剔除 100 和 200
        self.assertGreater(rep['filtered_out'], 0)
        # P1/P99/IQR 应有值
        self.assertIsNotNone(rep['p1'])
        self.assertIsNotNone(rep['p99'])
        self.assertIsNotNone(rep['iqr_lower'])
        self.assertIsNotNone(rep['iqr_upper'])

    def test_compute_represent_ct_handles_small_samples(self):
        """小样本（<4）不做剔除，直接取中位数"""
        values = [30, 35]
        rep = compute_represent_ct(values)
        self.assertEqual(rep['represent_ct'], 32.5)
        self.assertEqual(rep['filtered_out'], 0)

    def test_compute_represent_ct_handles_empty(self):
        """空数据应返回 None"""
        rep = compute_represent_ct([])
        self.assertIsNone(rep['represent_ct'])
        self.assertEqual(rep['sample_count'], 0)

    def test_build_xbar_r_chart_in_control(self):
        """稳定过程的控制图应判为受控"""
        # 日级数据稳定，无明显波动
        daily_series = [
            {'date': '2026-06-01', 'mean_ct': 30.0, 'range_ct': 2.0, 'sample_count': 5},
            {'date': '2026-06-02', 'mean_ct': 30.5, 'range_ct': 2.5, 'sample_count': 5},
            {'date': '2026-06-03', 'mean_ct': 31.0, 'range_ct': 1.8, 'sample_count': 5},
            {'date': '2026-06-04', 'mean_ct': 30.2, 'range_ct': 2.2, 'sample_count': 5},
            {'date': '2026-06-05', 'mean_ct': 30.8, 'range_ct': 2.0, 'sample_count': 5},
        ]
        chart = build_xbar_r_chart(daily_series)
        self.assertTrue(chart['is_in_control'])
        self.assertEqual(chart['rules_violated'], [])
        self.assertIsNotNone(chart['xbar_chart']['ucl'])
        self.assertIsNotNone(chart['r_chart']['ucl'])

    def test_build_xbar_r_chart_detects_out_of_control(self):
        """过程有越界点应判为失控"""
        daily_series = [
            {'date': '2026-06-01', 'mean_ct': 30.0, 'range_ct': 2.0, 'sample_count': 5},
            {'date': '2026-06-02', 'mean_ct': 30.5, 'range_ct': 2.0, 'sample_count': 5},
            {'date': '2026-06-03', 'mean_ct': 31.0, 'range_ct': 2.0, 'sample_count': 5},
            {'date': '2026-06-04', 'mean_ct': 30.2, 'range_ct': 2.0, 'sample_count': 5},
            {'date': '2026-06-05', 'mean_ct': 100.0, 'range_ct': 50.0, 'sample_count': 5},  # 越界
        ]
        chart = build_xbar_r_chart(daily_series)
        self.assertFalse(chart['is_in_control'])
        self.assertGreater(len(chart['rules_violated']), 0)

    def test_build_xbar_r_chart_insufficient_subgroups(self):
        """子组不足时应返回受控（无法计算）"""
        daily_series = [{'date': '2026-06-01', 'mean_ct': 30.0, 'range_ct': 2.0, 'sample_count': 5}]
        chart = build_xbar_r_chart(daily_series)
        self.assertTrue(chart['is_in_control'])
        self.assertEqual(chart['n_subgroups'], 1)

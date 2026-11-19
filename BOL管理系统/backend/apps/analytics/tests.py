from unittest.mock import Mock, patch
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.analytics.bol_aggregation import aggregate_bol_rows
from apps.analytics.views import (
	BudgetBolComparisonView,
	DashboardView,
	MultiDimBolAnalysisView,
	MultiDimBolTrendView,
	_calc_achievable_yoy_multi,
	_calculate_improve_target_achievable_bol,
	_calculate_improve_target_hours,
	_calculate_improve_target_bol,
	_calc_improve_target_compare,
)


class BolAggregationTests(SimpleTestCase):
	def test_sums_all_lines_and_same_line_rows_at_project_grain(self):
		rows = [
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 27.92},
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'BJ', 'bol': 27.92},
		]

		result = aggregate_bol_rows(
			rows, 'bol', ('fiscal_year', 'project_code', 'process_type')
		)

		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]['bol'], 55.84)
		self.assertEqual(result[0]['source_row_count'], 2)
		self.assertEqual(result[0]['plants'], ('BJ',))

	def test_can_preserve_plant_grain_and_ignore_null_values(self):
		rows = [
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 27.92},
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': None},
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Shanghai', 'bol': 12.0},
		]

		result = aggregate_bol_rows(
			rows, 'bol', ('fiscal_year', 'project_code', 'process_type', 'plant')
		)

		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]['plant'], 'BJ')
		self.assertEqual(result[0]['bol'], 27.92)
		self.assertEqual(result[0]['source_row_count'], 1)

	def test_can_preserve_asset_grain_while_summing_duplicate_asset_rows(self):
		rows = [
			{'project_code': 'T6968', 'process_type': 'IHE', 'asset': 'BJPU7',
			 'plant': 'Beijing_IHE', 'budget_bol': 12.0},
			{'project_code': 'T6968', 'process_type': 'IHE', 'asset': 'BJPU7',
			 'plant': 'Beijing_IHE', 'budget_bol': 13.0},
			{'project_code': 'T6968', 'process_type': 'IHE', 'asset': 'BJPU8',
			 'plant': 'Beijing_IHE', 'budget_bol': 27.92},
		]

		result = aggregate_bol_rows(
			rows, 'budget_bol', ('project_code', 'process_type', 'asset')
		)

		self.assertEqual([row['bol'] for row in result], [25.0, 27.92])

	def test_zero_bol_is_omitted_as_missing_data(self):
		rows = [
			{'fiscal_year': 2025, 'project_code': 'T6343', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 0},
		]

		result = aggregate_bol_rows(
			rows, 'bol', ('fiscal_year', 'project_code', 'process_type')
		)

		self.assertEqual(result, [])


class ImproveTargetAchievableBolTests(SimpleTestCase):
	def test_zero_process_result_falls_back_to_budget(self):
		row = {
			'process_01_ct': 0,
			'process_01_hc': 12,
			'bol_budget': 18,
		}

		bol, source = _calculate_improve_target_achievable_bol(row)

		self.assertEqual((bol, source), (18, 'bol_budget'))

	def test_nonzero_process_result_uses_ct_hc_formula(self):
		row = {
			'process_01_ct': 30,
			'process_01_hc': 2,
			'process_02_ct': 15,
			'process_02_hc': 2,
			'bol_budget': 18,
		}

		bol, source = _calculate_improve_target_achievable_bol(row)

		self.assertAlmostEqual(bol, (30 * 2 + 15 * 2) * (1 + 1 / 15) / 0.85 / 60)
		self.assertEqual(source, 'process')

	def test_target_bol_applies_improvement_percentage(self):
		self.assertAlmostEqual(_calculate_improve_target_bol(20, 0.06), 18.8)

	def test_missing_target_percentage_keeps_budget_bol(self):
		self.assertEqual(_calculate_improve_target_bol(20, None), 20)
		self.assertIsNone(_calculate_improve_target_bol(None, 0.06))

	def test_zero_volume_is_a_calculated_zero_not_missing(self):
		self.assertEqual(_calculate_improve_target_hours(20, 0), 0)
		self.assertIsNone(_calculate_improve_target_hours(20, None))

	def test_non_positive_bol_is_missing_for_improvement_hours(self):
		self.assertIsNone(_calculate_improve_target_hours(0, 100))
		self.assertIsNone(_calculate_improve_target_hours(-2, 100))

	def test_same_project_process_rows_are_both_included(self):
		rows = [
			{
				'id': 1, 'plant': 'Shanghai', 'process': 'FA', 'program_code': 'T1',
				'program_name': 'Project 1', 'bol_budget': 0.624, 'target_bol': 0.1,
				'process_01_ct': None, 'process_01_hc': None,
				'process_02_ct': None, 'process_02_hc': None,
				'process_03_ct': None, 'process_03_hc': None,
				'process_04_ct': None, 'process_04_hc': None,
			},
			{
				'id': 2, 'plant': 'Shanghai', 'process': 'FA', 'program_code': 'T1',
				'program_name': 'Project 1', 'bol_budget': 0.624, 'target_bol': None,
				'process_01_ct': None, 'process_01_hc': None,
				'process_02_ct': None, 'process_02_hc': None,
				'process_03_ct': None, 'process_03_hc': None,
				'process_04_ct': None, 'process_04_hc': None,
			},
		]
		with (
			patch('apps.actual_ct.models.BolImproveTarget.objects.filter') as target_filter,
			patch('apps.actual_ct.models.BolImproveTargetVolume.objects.filter') as volume_filter,
		):
			target_filter.return_value.order_by.return_value.values.return_value = rows
			volume_filter.return_value.values.return_value = [
				{'id': 1, 'volume': 100},
				{'id': 2, 'volume': 100},
			]
			result = _calc_improve_target_compare(2026)

		sh = result['summary'][0]
		self.assertEqual(sh['budget_count'], 2)
		self.assertEqual(sh['target_count'], 2)
		self.assertEqual(sh['achievable_count'], 2)
		self.assertEqual(sh['budget_hours'], 2.1)
		self.assertEqual(sh['target_hours'], 2.0)
		self.assertEqual(sh['achievable_hours'], 2.1)


class DashboardKpiTests(SimpleTestCase):
	def test_lb_kpi_uses_latest_cmc_region_value(self):
		def mock_kpi_filter(**kwargs):
			queryset = Mock()
			if kwargs['kpi_name'] == 'LB':
				queryset.order_by.return_value.values_list.return_value.first.return_value = 10
				queryset.filter.return_value.values.return_value = [
					{'location': 'CMC', 'kpi_value': 0.8156},
					{'location': 'BJ', 'kpi_value': 0.8313},
				]
			else:
				queryset.order_by.return_value.values_list.return_value.first.return_value = None
			return queryset

		with patch('apps.actual_ct.models.KpiMonthlyHistory.objects.filter',
		           side_effect=mock_kpi_filter):
			result = DashboardView()._load_ame_kpis(2026)

		self.assertEqual(result['LB']['month'], 10)
		self.assertEqual(result['LB']['cmc_pct'], 81.6)
		self.assertEqual(result['LB']['by_plant'], {'BJ': 83.1})


class MultiDimBolTrendAggregationTests(SimpleTestCase):
	def test_yoy_omits_project_when_a_year_bol_is_zero(self):
		rows = [
			{'fiscal_year': 2024, 'project_code': 'T6343', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 34.96},
			{'fiscal_year': 2025, 'project_code': 'T6343', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 0},
			{'fiscal_year': 2024, 'project_code': 'T7000', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 20.0},
			{'fiscal_year': 2025, 'project_code': 'T7000', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 15.0},
		]
		year_options = Mock()
		year_options.values_list.return_value.distinct.return_value.order_by.return_value = [2024, 2025]
		plant_options = Mock()
		plant_options.values_list.return_value.distinct.return_value = ['Beijing_IHE']
		data_queryset = Mock()
		data_queryset.order_by.return_value.values.return_value = rows
		cbco_queryset = Mock()
		cbco_queryset.order_by.return_value.values.return_value = [
			{'program_number': 'T6343', 'year': 2025, 'volume': 100,
			 'program_description': 'V254'},
			{'program_number': 'T7000', 'year': 2025, 'volume': 100,
			 'program_description': 'Project 7000'},
		]

		with (
			patch('apps.budget_bol.models.AchievableTargetBol.objects.filter',
			      side_effect=[year_options, plant_options, data_queryset]),
			patch('apps.budget_bol.cbco_models.CbcoRecord.objects.filter',
			      return_value=cbco_queryset),
		):
			result = _calc_achievable_yoy_multi([2024, 2025], top_n=0)

		self.assertEqual([item['project_code'] for item in result['items']], ['T7000'])
		self.assertEqual(result['items'][0]['values'], {'2024': 20.0, '2025': 15.0})
	def test_multidimensional_statistics_use_project_level_samples(self):
		rows = [
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 27.92},
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 27.92},
			{'fiscal_year': 2025, 'project_code': 'T7000', 'process_type': 'IHE',
			 'plant': 'Shanghai_IHE', 'bol': 10.0},
		]
		bol_queryset = Mock()
		bol_queryset.values.return_value = rows
		roof_queryset = Mock()
		roof_queryset.order_by.return_value.values.return_value = [
			{'program_number': 'T6968', 'typ_of_roof': 'Fixed panel'},
			{'program_number': 'T7000', 'typ_of_roof': 'Fixed panel'},
		]

		with (
			patch('apps.budget_bol.models.AchievableTargetBol.objects.filter',
			      return_value=bol_queryset),
			patch('apps.budget_bol.cbco_models.CbcoRecord.objects.filter',
			      return_value=roof_queryset),
		):
			response = MultiDimBolAnalysisView().get(
				SimpleNamespace(query_params={'bol_type': 'ACHIEVABLE'})
			)

		self.assertEqual(response.data['by_process_roof'][0]['count'], 2)
		self.assertEqual(response.data['by_process_roof'][0]['mean'], 32.92)
		self.assertEqual(len(response.data['cross_plant']), 2)
		self.assertEqual(response.data['cross_plant'][0]['count'], 1)

	def test_dashboard_net_hours_uses_summed_budget_bol(self):
		from_rows = Mock()
		from_rows.values.return_value = [
			{'project_code': 'T6968', 'process_type': 'IHE', 'budget_bol': 36.705},
			{'project_code': 'T6968', 'process_type': 'IHE', 'budget_bol': 36.705},
		]
		to_rows = Mock()
		to_rows.values.return_value = [
			{'project_code': 'T6968', 'process_type': 'IHE', 'budget_bol': 27.92},
			{'project_code': 'T6968', 'process_type': 'IHE', 'budget_bol': 27.92},
		]
		volume_queryset = Mock()
		volume_queryset.values.return_value = [
			{'program_number': 'T6968', 'volume': 60},
		]

		with (
			patch('apps.analytics.views.BudgetBol.objects.filter',
			      side_effect=[from_rows, to_rows]),
			patch('apps.budget_bol.cbco_models.CbcoRecord.objects.filter',
			      return_value=volume_queryset),
		):
			hours = DashboardView()._calc_net_hours_saved(2026)

		self.assertEqual(hours, 17.6)

	def test_budget_fiscal_comparison_sums_lines_before_saved_hours(self):
		from_queryset = Mock()
		from_queryset.values.return_value = [
			{'project_code': 'T6968', 'process_type': 'IHE', 'plant': 'Beijing_IHE',
			 'budget_bol': 73.41},
		]
		to_queryset = Mock()
		to_queryset.values.return_value = [
			{'project_code': 'T6968', 'process_type': 'IHE', 'plant': 'BJ',
			 'budget_bol': 27.92},
			{'project_code': 'T6968', 'process_type': 'IHE', 'plant': 'BJ',
			 'budget_bol': 27.92},
		]
		volume_queryset = Mock()
		volume_queryset.values.return_value = [
			{'program_number': 'T6968', 'year': 2025, 'volume': 50,
			 'program_description': 'C71KB'},
			{'program_number': 'T6968', 'year': 2026, 'volume': 60,
			 'program_description': 'C71KB'},
		]

		with (
			patch('apps.analytics.views.BudgetBol.objects.filter',
			      side_effect=[from_queryset, to_queryset]),
			patch('apps.budget_bol.cbco_models.CbcoRecord.objects.filter',
			      return_value=volume_queryset),
		):
			response = BudgetBolComparisonView().get(
				SimpleNamespace(query_params={})
			)

		item = response.data['items'][0]
		self.assertEqual(item['from_bol'], 73.41)
		self.assertEqual(item['to_bol'], 55.84)
		self.assertEqual(item['hours_saved'], 17.57)

	def test_budget_and_achievable_sum_lines_before_project_mean(self):
		budget_rows = [
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T6968',
			 'plant': 'Beijing', 'budget_bol': 30.0},
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T6968',
			 'plant': 'Beijing', 'budget_bol': 30.0},
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T7000',
			 'plant': 'Beijing', 'budget_bol': 10.0},
		]
		achievable_rows = [
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T6968',
			 'plant': 'Beijing', 'bol': 27.92},
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T6968',
			 'plant': 'Beijing', 'bol': 27.92},
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T7000',
			 'plant': 'Beijing', 'bol': 10.0},
		]
		budget_queryset = SimpleNamespace(values=lambda *args: budget_rows)
		achievable_queryset = SimpleNamespace(values=lambda *args: achievable_rows)
		target_rows = [
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T6968',
			 'plant': 'Beijing', 'bol': 3.0},
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T6968',
			 'plant': 'Beijing', 'bol': 3.0},
			{'fiscal_year': 2026, 'process_type': 'IHE', 'project_code': 'T7000',
			 'plant': 'Beijing', 'bol': 2.0},
		]
		target_queryset = SimpleNamespace(values=lambda *args: target_rows)
		cbco_queryset = SimpleNamespace(
			order_by=lambda *args: SimpleNamespace(values=lambda *fields: [
				{'program_number': 'T6968', 'typ_of_roof': 'Fixed panel'},
				{'program_number': 'T7000', 'typ_of_roof': 'Fixed panel'},
			])
		)

		with (
			patch('apps.budget_bol.models.BudgetBol.objects.filter',
			      return_value=budget_queryset),
			patch('apps.budget_bol.models.AchievableTargetBol.objects.filter',
			      side_effect=[achievable_queryset, target_queryset]),
			patch('apps.budget_bol.cbco_models.CbcoRecord.objects.filter',
			      return_value=cbco_queryset),
		):
			response = MultiDimBolTrendView().get(
				SimpleNamespace(query_params={})
			)

		combo = response.data['by_year_combo']
		self.assertEqual(len(combo), 1)
		self.assertEqual(combo[0]['budget_mean'], 35.0)
		self.assertEqual(combo[0]['budget_count'], 2)
		self.assertEqual(combo[0]['achievable_mean'], 32.92)
		self.assertEqual(combo[0]['achievable_count'], 2)
		self.assertEqual(combo[0]['target_mean'], 4.0)
		self.assertEqual(combo[0]['target_count'], 2)

		plant_combo = response.data['by_year_plant_combo']
		self.assertEqual(len(plant_combo), 1)
		self.assertEqual(plant_combo[0]['mean'], 32.92)
		self.assertEqual(plant_combo[0]['count'], 2)

	def test_achievable_yoy_sums_lines_before_comparing_years(self):
		rows = [
			{'fiscal_year': 2024, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 73.41},
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 27.92},
			{'fiscal_year': 2025, 'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'BJ', 'bol': 27.92},
		]
		year_options = Mock()
		year_options.values_list.return_value.distinct.return_value.order_by.return_value = [2024, 2025]
		plant_options = Mock()
		plant_options.values_list.return_value.distinct.return_value = ['Beijing_IHE', 'BJ']
		data_queryset = Mock()
		data_queryset.order_by.return_value.values.return_value = rows
		cbco_queryset = Mock()
		cbco_queryset.order_by.return_value.values.return_value = [
			{'program_number': 'T6968', 'year': 2025, 'volume': 100,
			 'program_description': 'C71KB'},
		]

		with (
			patch('apps.budget_bol.models.AchievableTargetBol.objects.filter',
			      side_effect=[year_options, plant_options, data_queryset]),
			patch('apps.budget_bol.cbco_models.CbcoRecord.objects.filter',
			      return_value=cbco_queryset),
		):
			result = _calc_achievable_yoy_multi([2024, 2025], top_n=10)

		self.assertEqual(len(result['items']), 1)
		item = result['items'][0]
		self.assertEqual(item['values'], {'2024': 73.41, '2025': 55.84})
		self.assertEqual(item['from_bol'], 73.41)
		self.assertEqual(item['to_bol'], 55.84)
		self.assertEqual(item['diff'], -17.57)

	def test_achievable_yoy_detail_sums_lines_consistently(self):
		from_rows = [
			{'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 73.41},
		]
		to_rows = [
			{'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'Beijing_IHE', 'bol': 27.92},
			{'project_code': 'T6968', 'process_type': 'IHE',
			 'plant': 'BJ', 'bol': 27.92},
		]
		from_queryset = Mock()
		from_queryset.values.return_value = from_rows
		to_queryset = Mock()
		to_queryset.values.return_value = to_rows
		cbco_queryset = Mock()
		cbco_queryset.values.return_value = [
			{'program_number': 'T6968', 'volume': 100,
			 'program_description': 'C71KB'},
		]

		with (
			patch('apps.budget_bol.models.AchievableTargetBol.objects.filter',
			      side_effect=[from_queryset, to_queryset]),
			patch('apps.budget_bol.cbco_models.CbcoRecord.objects.filter',
			      return_value=cbco_queryset),
		):
			items = DashboardView()._calc_improvement_opportunities(2025)

		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]['from_bol'], 73.41)
		self.assertEqual(items[0]['to_bol'], 55.84)
		self.assertEqual(items[0]['bol_reduction'], 17.57)

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.tracking.models import HighBolTracking
from bol_platform.bol_calc import calc_labor_cost_gap


class LaborCostGapTests(SimpleTestCase):
	def test_cost_gap_converts_hourly_rate_to_per_minute(self):
		self.assertEqual(calc_labor_cost_gap(6, 12392, 54.18), 67139.86)

	def test_negative_gap_is_reported_as_annual_savings(self):
		self.assertEqual(calc_labor_cost_gap(-6, 12392, 54.18), -67139.86)

	@patch('django.db.models.Model.save')
	def test_partial_save_persists_recalculated_gap_and_cost(self, base_save):
		tracking = HighBolTracking(
			program_code='T7262',
			current_bol=22.6,
			target_bol=16.6,
			annual_volume=12392,
			labor_rate=54.18,
		)

		tracking.save(update_fields=['current_bol', 'updated_at'])

		self.assertEqual(tracking.bol_gap, 6.0)
		self.assertEqual(tracking.cost_gap, 67139.86)
		self.assertEqual(
			base_save.call_args.kwargs['update_fields'],
			{'current_bol', 'updated_at', 'bol_gap', 'cost_gap'},
		)

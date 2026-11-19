from datetime import datetime

from django.test import SimpleTestCase

from apps.dynamic_bol.views import _build_approval_overview_summary


class ApprovalOverviewStatsTests(SimpleTestCase):
	def test_counts_unique_project_processes_and_monthly_status_records(self):
		approved_rows = [
			{'location': 'Beijing_IHE', 'program_code': 'T1', 'process': 'FA'},
			{'location': 'BJ', 'program_code': 'T1', 'process': 'FA'},
			{'location': 'BJ', 'program_code': 'T1', 'process': 'IHE'},
		]
		monthly_rows = [
			{'month': datetime(2025, 11, 1), 'final_approve_status': 'Approved', 'count': 3},
			{'month': datetime(2025, 11, 1), 'final_approve_status': 'Ongoing', 'count': 2},
			{'month': datetime(2025, 12, 1), 'final_approve_status': 'Rejected', 'count': 1},
		]

		result = _build_approval_overview_summary(
			approved_rows, monthly_rows, ['2025-11', '2025-12']
		)

		self.assertEqual(result['approved_by_location'], [{'name': 'BJ', 'count': 2}])
		self.assertEqual(
			next(item for item in result['monthly_status'] if item['status'] == 'Pending')['data'],
			[2, 0],
		)
		self.assertEqual(
			next(item for item in result['monthly_status'] if item['status'] == 'Rejected')['data'],
			[0, 1],
		)

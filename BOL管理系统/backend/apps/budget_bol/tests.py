from unittest.mock import patch

from django.test import SimpleTestCase

from apps.budget_bol.views import _active_status_rows, _project_codes_by_name


class ActiveStatusRowsTests(SimpleTestCase):
    def test_only_must_and_won_rows_are_returned(self):
        rows = [
            {'project_code': 'MUST-1', 'status': 'MUST'},
            {'project_code': 'WON-1', 'status': ' won '},
            {'project_code': 'CANCELLED-1', 'status': 'CANCELLED'},
            {'project_code': 'UNKNOWN-1', 'status': ''},
        ]

        self.assertEqual(
            [row['project_code'] for row in _active_status_rows(rows)],
            ['MUST-1', 'WON-1'],
        )


class ProjectNameSearchTests(SimpleTestCase):
    @patch('apps.budget_bol.views.CbcoRecord.objects.filter')
    @patch('apps.projects.models.ProgramInfo.objects.filter')
    def test_search_matches_program_names_and_displayed_descriptions(
        self, program_info_filter, cbco_filter
    ):
        program_info_filter.return_value.values_list.return_value = [
            'HRDB-001', 'SHARED-001',
        ]
        cbco_filter.return_value.values_list.return_value = [
            'CMC-001', 'SHARED-001',
        ]

        codes = _project_codes_by_name('Foam')

        self.assertEqual(codes, {'HRDB-001', 'CMC-001', 'SHARED-001'})
        program_info_filter.assert_called_once_with(
            program_name__icontains='Foam',
        )
        cbco_filter.assert_called_once_with(
            program_description__icontains='Foam',
        )

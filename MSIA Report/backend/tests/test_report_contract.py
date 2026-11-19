import pytest
from fastapi import HTTPException

from app.api.reports import export_report_pdf, get_phase_report
from app.services.phase_report_service import REPORTABLE_REVIEW_STATUSES


def test_reports_only_use_formally_submitted_statuses():
    assert REPORTABLE_REVIEW_STATUSES == ("submitted", "confirmed")
    assert "draft" not in REPORTABLE_REVIEW_STATUSES


@pytest.mark.parametrize("endpoint", [get_phase_report, export_report_pdf])
def test_legacy_phase_report_endpoints_are_retired(endpoint):
    with pytest.raises(HTTPException) as exc_info:
        endpoint("PLAN-1", "MSIA1")
    assert exc_info.value.status_code == 410
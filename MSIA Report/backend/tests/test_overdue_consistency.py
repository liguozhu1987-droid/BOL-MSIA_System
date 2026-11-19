from datetime import datetime, timedelta

from app.models.issue import Issue
from app.services.issue_overdue import build_overdue_filter, is_issue_overdue


def test_pending_verification_is_not_overdue_even_after_deadline():
    now = datetime(2026, 1, 10, 12, 0, 0)
    issue = Issue(
        Status="pending_verification",
        Deadline=now - timedelta(days=2),
        PlannedCloseDate=now - timedelta(days=2),
        CreatedAt=now - timedelta(days=10),
    )
    assert is_issue_overdue(issue, now) is False


def test_issue_without_deadline_is_not_overdue():
    now = datetime(2026, 1, 10, 12, 0, 0)
    issue = Issue(
        Status="open",
        PlannedCloseDate=None,
        CreatedAt=now - timedelta(days=3),
    )
    assert is_issue_overdue(issue, now) is False


def test_deadline_day_is_not_overdue():
    now = datetime(2026, 1, 10, 12, 0, 0)
    issue = Issue(Status="in_progress", Deadline=datetime(2026, 1, 10, 0, 0, 0))
    assert is_issue_overdue(issue, now) is False


def test_day_after_deadline_is_overdue():
    now = datetime(2026, 1, 11, 0, 0, 0)
    issue = Issue(Status="in_progress", Deadline=datetime(2026, 1, 10, 0, 0, 0))
    assert is_issue_overdue(issue, now) is True


def test_build_overdue_filter_excludes_closed_status_and_past_due_only_when_applicable():
    now = datetime(2026, 1, 10, 12, 0, 0)
    conditions = build_overdue_filter(now)
    assert len(conditions) == 3
    assert conditions[0].left.name == "Status" or str(conditions[0]).find("Status") >= 0

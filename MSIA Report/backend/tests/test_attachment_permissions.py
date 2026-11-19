from types import SimpleNamespace

from app.api.attachments import _IMAGE_TYPES, _can_manage_issue_attachment


def make_issue():
    return SimpleNamespace(OwnerUserId=10, OwnerUserName="owner01")


def make_user(user_id, username, role):
    return SimpleNamespace(Id=user_id, Username=username, Role=role)


def test_issue_evidence_allows_reviewers_and_owner():
    issue = make_issue()
    assert _can_manage_issue_attachment(issue, "issue", make_user(20, "reviewer01", "reviewer"))
    assert _can_manage_issue_attachment(issue, "issue", make_user(10, "owner01", "reviewee"))


def test_closure_evidence_rejects_other_reviewee_but_allows_admin():
    issue = make_issue()
    assert not _can_manage_issue_attachment(issue, "issue_closure", make_user(30, "other", "reviewee"))
    assert _can_manage_issue_attachment(issue, "issue_closure", make_user(1, "admin", "admin"))


def test_supported_evidence_types_are_images_only():
    assert "image/png" in _IMAGE_TYPES
    assert "application/pdf" not in _IMAGE_TYPES

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import attachments, issues
from app.core.deps import get_current_user, get_db
from app.models.attachment import Attachment
from app.models.issue import Issue
from app.models.review import ReviewRecord
from app.schemas.issue import IssueCreate


class FakeQuery:
    def __init__(self, model, db):
        self.model = model
        self.db = db

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def first(self):
        if self.model is Issue:
            return self.db.issue
        if self.model is Attachment:
            return self.db.attachment
        if self.model is ReviewRecord:
            return self.db.review
        return None


class FakeDb:
    def __init__(self, issue=None, attachment=None, review=None):
        self.issue = issue
        self.attachment = attachment
        self.review = review

    def query(self, model):
        return FakeQuery(model, self)

    def add(self, value):
        self.added = value

    def commit(self):
        pass

    def refresh(self, value):
        pass


def make_app(db, user):
    def echo_issue(payload: IssueCreate):
        return payload

    app = FastAPI()
    app.patch("/issues/{issue_id}/status")(issues.update_issue_status)
    app.get("/attachments/{attachment_id}")(attachments.download_attachment)
    app.delete("/attachments/{attachment_id}")(attachments.delete_attachment)
    app.post("/attachments")(attachments.upload_attachment)
    app.post("/issues")(echo_issue)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return app


def user(user_id=2, role="reviewee"):
    return SimpleNamespace(Id=user_id, Username="user", Role=role, DisplayName="User")


def issue(status="open"):
    return SimpleNamespace(
        Id=10, Status=status, IsDeleted=False, OwnerUserId=99,
        OwnerUserName="owner", CreatedBy=99,
    )


def attachment(owner_type="issue"):
    return SimpleNamespace(
        Id=20, OwnerType=owner_type, OwnerId=10,
        StoredPath="missing-file", FileName="evidence.png", MimeType="image/png",
    )


def test_other_user_cannot_close_issue():
    client = TestClient(make_app(FakeDb(issue=issue()), user(role="reviewer")))
    response = client.patch("/issues/10/status", json={"Status": "closed"})
    assert response.status_code == 403


def test_reviewee_cannot_bypass_closure_workflow():
    client = TestClient(make_app(FakeDb(issue=issue()), user(user_id=99)))
    response = client.patch("/issues/10/status", json={"Status": "closed"})
    assert response.status_code == 403


def test_invalid_state_transitions_are_rejected():
    lead = user(role="lead_reviewer")
    open_client = TestClient(make_app(FakeDb(issue=issue("open")), lead))
    closed_client = TestClient(make_app(FakeDb(issue=issue("closed")), lead))
    assert open_client.patch("/issues/10/status", json={"Status": "closed"}).status_code == 400
    assert closed_client.patch("/issues/10/status", json={"Status": "open"}).status_code == 400


@pytest.mark.parametrize("payload", [
    {"Title": "bad", "Status": "invalid"},
    {"Title": "bad", "Severity": "X"},
    {"Title": "bad", "Priority": "urgent"},
])
def test_invalid_issue_fields_return_422(payload):
    app = FastAPI()
    def echo_issue(issue_payload: IssueCreate):
        return issue_payload

    app.post("/issues")(echo_issue)
    client = TestClient(app)
    assert client.post("/issues", json=payload).status_code == 422


def test_unauthorized_user_cannot_download_or_delete_issue_attachment():
    db = FakeDb(issue=issue(), attachment=attachment())
    client = TestClient(make_app(db, user(user_id=2, role="reviewee")))
    assert client.get("/attachments/20").status_code == 403
    assert client.delete("/attachments/20").status_code == 403


def test_attachment_rejects_invalid_mime_and_oversized_file(monkeypatch):
    db = FakeDb(issue=issue())
    client = TestClient(make_app(db, user(user_id=99, role="reviewee")))
    invalid = client.post(
        "/attachments?owner_type=issue&owner_id=10",
        files={"file": ("evidence.pdf", b"pdf", "application/pdf")},
    )
    assert invalid.status_code == 400

    monkeypatch.setattr(attachments, "_MAX_FILE_SIZE", 2)
    oversized = client.post(
        "/attachments?owner_type=issue&owner_id=10",
        files={"file": ("evidence.png", b"123", "image/png")},
    )
    assert oversized.status_code == 413


def test_attachment_rejects_missing_owner():
    client = TestClient(make_app(FakeDb(), user(user_id=99, role="reviewer")))
    response = client.post(
        "/attachments?owner_type=issue&owner_id=10",
        files={"file": ("evidence.png", b"png", "image/png")},
    )
    assert response.status_code == 404

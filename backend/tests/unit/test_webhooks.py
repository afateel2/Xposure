"""
Unit tests for app/webhooks.py (send/sign) and app/routes/webhooks.py (the
demo receiver). httpx itself is mocked at its single call site
(app.webhooks.httpx.post) — these tests are about our signing/dispatch
logic, not about actually reaching a network. The FastAPI receiver route
is tested for real against an in-memory SQLite session, same
dependency-override pattern as tests/unit/test_routes.py.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import webhooks
from app.config import settings
from app.db.base import Base
from app.db.models import AuditLog
from app.db.session import get_db
from app.main import app


# ── send_webhook / verify_signature (pure-ish, config + httpx only) ───────

def test_send_webhook_rejects_unknown_event():
    with pytest.raises(ValueError, match="Unknown webhook event"):
        webhooks.send_webhook("not.a.real.event", {})


def test_send_webhook_is_a_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "")
    with patch("app.webhooks.httpx.post") as mock_post:
        result = webhooks.send_webhook("change.detected", {"change_id": 1})
    mock_post.assert_not_called()
    assert result == {"sent": False, "event": "change.detected", "reason": "no WEBHOOK_URL configured"}


def test_send_webhook_signs_and_posts_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "http://example.test/hook")
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    mock_response = MagicMock(status_code=200)
    with patch("app.webhooks.httpx.post", return_value=mock_response) as mock_post:
        result = webhooks.send_webhook("action.approved", {"action_id": 7})

    assert result == {"sent": True, "event": "action.approved", "url": "http://example.test/hook", "status_code": 200}
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-Xposure-Signature"].startswith("sha256=")
    # The signature must actually verify against the exact body sent.
    assert webhooks.verify_signature("s3cret", kwargs["content"], kwargs["headers"]["X-Xposure-Signature"])
    assert not webhooks.verify_signature("wrong-secret", kwargs["content"], kwargs["headers"]["X-Xposure-Signature"])


def test_send_webhook_without_secret_sends_no_signature_header(monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "http://example.test/hook")
    monkeypatch.setattr(settings, "webhook_secret", "")
    mock_response = MagicMock(status_code=200)
    with patch("app.webhooks.httpx.post", return_value=mock_response) as mock_post:
        webhooks.send_webhook("impact.computed", {"change_id": 1})
    _, kwargs = mock_post.call_args
    assert "X-Xposure-Signature" not in kwargs["headers"]


def test_send_webhook_catches_delivery_failure(monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "http://example.test/hook")
    with patch("app.webhooks.httpx.post", side_effect=ConnectionError("refused")):
        result = webhooks.send_webhook("change.detected", {"change_id": 1})
    assert result["sent"] is False
    assert "refused" in result["reason"]


def test_verify_signature_rejects_missing_or_malformed_header():
    assert webhooks.verify_signature("s", b"body", None) is False
    assert webhooks.verify_signature("s", b"body", "not-prefixed") is False
    assert webhooks.verify_signature("s", b"body", "sha256=deadbeef") is False


# ── POST /webhooks/receiver, GET /webhooks/received ───────────────────────

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_receiver_accepts_unsigned_payload_when_no_secret_configured(client, db, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "")
    response = client.post("/webhooks/receiver", json={"event": "change.detected", "data": {"change_id": 1}})
    assert response.status_code == 200
    audit_log_id = response.json()["audit_log_id"]

    row = db.get(AuditLog, audit_log_id)
    assert row.actor == "webhook:receiver"
    assert row.event == "webhook_received:change.detected"
    assert row.payload_json["data"] == {"change_id": 1}


def test_receiver_requires_valid_signature_when_secret_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    body = b'{"event": "action.approved", "data": {}}'
    good_sig = "sha256=" + webhooks._sign("s3cret", body)

    unsigned = client.post("/webhooks/receiver", content=body, headers={"Content-Type": "application/json"})
    assert unsigned.status_code == 401

    wrong_sig = client.post(
        "/webhooks/receiver", content=body,
        headers={"Content-Type": "application/json", "X-Xposure-Signature": "sha256=wrong"},
    )
    assert wrong_sig.status_code == 401

    valid = client.post(
        "/webhooks/receiver", content=body,
        headers={"Content-Type": "application/json", "X-Xposure-Signature": good_sig},
    )
    assert valid.status_code == 200


def test_receiver_marks_trust_level_of_each_recorded_event(client, db, monkeypatch):
    """Security finding from the bulletproofing pass: with no
    WEBHOOK_SECRET configured (the shipped default), this endpoint accepts
    any caller's payload — by design, so the demo works with zero setup —
    but that must never look identical, in the audit log, to a delivery
    that was actually signature-checked. Every recorded event carries
    _verified so a later reader can tell the difference."""
    monkeypatch.setattr(settings, "webhook_secret", "")
    unverified = client.post("/webhooks/receiver", json={"event": "change.detected", "data": {}})
    assert unverified.json()["verified"] is False
    row = db.get(AuditLog, unverified.json()["audit_log_id"])
    assert row.payload_json["_verified"] is False

    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    body = b'{"event": "action.approved", "data": {}}'
    sig = "sha256=" + webhooks._sign("s3cret", body)
    verified = client.post(
        "/webhooks/receiver", content=body,
        headers={"Content-Type": "application/json", "X-Xposure-Signature": sig},
    )
    assert verified.json()["verified"] is True
    row2 = db.get(AuditLog, verified.json()["audit_log_id"])
    assert row2.payload_json["_verified"] is True


def test_list_received_webhooks_returns_newest_first(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "")
    client.post("/webhooks/receiver", json={"event": "change.detected", "data": {"n": 1}})
    client.post("/webhooks/receiver", json={"event": "impact.computed", "data": {"n": 2}})

    response = client.get("/webhooks/received")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["event"] == "webhook_received:impact.computed"
    assert body[1]["event"] == "webhook_received:change.detected"

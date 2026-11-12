"""
app/auth.py and routes/auth.py: real reviewer identity.

Deliberately does NOT use tests/unit/auth_fixtures.py's require_user
override — this file exercises the real login/logout/session cookie path
end to end, the same discipline test_routes.py's module docstring states
for get_db: a real SQLAlchemy session against SQLite, not a mock.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import SESSION_COOKIE, hash_password, verify_password
from app.db.base import Base
from app.db.models import AppUser, UserSession
from app.db.session import get_db
from app.main import app


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(db):
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def seeded_user(db):
    user = AppUser(
        email="reem@example.com", name_en="Reem", name_ar="ريم", job_title_en="Compliance Officer",
        job_title_ar="مسؤولة الامتثال", role="admin", password_hash=hash_password("correct horse"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_hash_password_is_salted_and_verifies_correctly():
    h1 = hash_password("same password")
    h2 = hash_password("same password")
    assert h1 != h2  # different random salt each time
    assert verify_password("same password", h1)
    assert verify_password("same password", h2)
    assert not verify_password("wrong password", h1)


def test_verify_password_rejects_malformed_stored_value():
    assert not verify_password("anything", "not-a-real-hash")
    assert not verify_password("anything", "")


def test_login_sets_a_cookie_and_me_reflects_it(client, seeded_user):
    resp = client.post("/auth/login", json={"email": "reem@example.com", "password": "correct horse"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["user"]["email"] == "reem@example.com"
    assert body["user"]["role"] == "admin"
    assert "password" not in body["user"] and "password_hash" not in body["user"]
    assert SESSION_COOKIE in resp.cookies

    me = client.get("/auth/me")
    assert me.json() == {"authenticated": True, "user": body["user"]}


def test_login_is_case_insensitive_on_email(client, seeded_user):
    resp = client.post("/auth/login", json={"email": "REEM@EXAMPLE.COM", "password": "correct horse"})
    assert resp.status_code == 200


def test_wrong_password_is_401_with_bilingual_detail(client, seeded_user):
    resp = client.post("/auth/login", json={"email": "reem@example.com", "password": "wrong"})
    assert resp.status_code == 401
    assert "|" in resp.json()["detail"]  # "English | Arabic", this project's honest-error convention


def test_unknown_email_is_401_not_404(client):
    """Never reveal whether an email exists — same status either way."""
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 401


def test_inactive_user_cannot_log_in(client, db, seeded_user):
    seeded_user.is_active = False
    db.commit()
    resp = client.post("/auth/login", json={"email": "reem@example.com", "password": "correct horse"})
    assert resp.status_code == 401


def test_me_without_a_cookie_is_not_authenticated(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False, "user": None}


def test_logout_destroys_the_session_row_not_just_the_cookie(client, db, seeded_user):
    client.post("/auth/login", json={"email": "reem@example.com", "password": "correct horse"})
    assert db.query(UserSession).count() == 1

    out = client.post("/auth/logout")
    assert out.status_code == 200
    assert out.json() == {"authenticated": False, "user": None}
    assert db.query(UserSession).count() == 0  # not just an expired/cleared cookie: the row is gone

    me = client.get("/auth/me")
    assert me.json()["authenticated"] is False


def test_expired_session_is_treated_as_signed_out_and_cleaned_up(client, db, seeded_user):
    client.post("/auth/login", json={"email": "reem@example.com", "password": "correct horse"})
    row = db.query(UserSession).one()
    row.expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit()

    me = client.get("/auth/me")
    assert me.json()["authenticated"] is False
    assert db.query(UserSession).count() == 0  # expired row is pruned on the read that finds it


def test_a_mutating_endpoint_requires_login(client):
    """/actions/{id}/approve depends on require_user (routes/actions.py).
    No cookie at all -> 401, not a crash and not a silent "user:web"."""
    resp = client.post("/actions/999/approve")
    assert resp.status_code == 401
    assert "sign in" in resp.json()["detail"].lower()


def test_logging_in_then_calling_a_mutating_endpoint_uses_the_real_identity(client, seeded_user):
    client.post("/auth/login", json={"email": "reem@example.com", "password": "correct horse"})
    # No action with this id exists in this empty DB, but the point here is
    # that auth passes (404, not 401) — the identity check runs before the
    # existence check, which is routes/actions.py's own dependency order.
    resp = client.post("/actions/999/approve")
    assert resp.status_code == 404


def test_only_an_admin_can_edit_the_automation_policy(client, db):
    reviewer = AppUser(
        email="khalid@example.com", name_en="Khalid", name_ar="خالد", role="reviewer",
        password_hash=hash_password("x"),
    )
    db.add(reviewer)
    db.commit()
    client.post("/auth/login", json={"email": "khalid@example.com", "password": "x"})
    resp = client.put("/settings/policy", json={"default_level": "notify_only", "action_levels": {}})
    assert resp.status_code == 403


def test_an_admin_can_edit_the_automation_policy_and_it_is_audited(client, db, seeded_user, monkeypatch, tmp_path):
    from app import policy as policy_mod

    policy_path = tmp_path / "automation_policy.yaml"
    policy_path.write_text("version: 1\ndefault_level: draft_then_approve\naction_levels: {}\n", encoding="utf-8")
    monkeypatch.setattr(policy_mod, "POLICY_PATH", policy_path)
    policy_mod.load_policy.cache_clear()
    try:
        client.post("/auth/login", json={"email": "reem@example.com", "password": "correct horse"})
        resp = client.put(
            "/settings/policy",
            json={"default_level": "draft_then_approve", "action_levels": {"notify_owner": "notify_only"}},
        )
        assert resp.status_code == 200
        assert resp.json()["action_levels"]["notify_owner"] == "notify_only"

        from app.db.models import AuditLog

        row = db.query(AuditLog).filter(AuditLog.event == "policy_updated").one()
        assert row.actor == "user:reem@example.com"
        assert row.payload_json["new"]["action_levels"]["notify_owner"] == "notify_only"

        # A gate still wins over the request: G3 only allows collect_evidence/
        # notify_owner to auto_execute, whatever the saved file says.
        resp2 = client.put(
            "/settings/policy",
            json={"default_level": "draft_then_approve", "action_levels": {"update_policy": "auto_execute"}},
        )
        assert resp2.status_code == 200
        decided = policy_mod.decide_automation("update_policy", "editorial", 0.95)
        assert decided != "auto_execute"  # G1/G3 still cap it, exactly as a hand-edited file would be capped
    finally:
        policy_mod.load_policy.cache_clear()


def test_update_policy_rejects_an_unknown_action_type(client, seeded_user):
    client.post("/auth/login", json={"email": "reem@example.com", "password": "correct horse"})
    resp = client.put(
        "/settings/policy", json={"default_level": "draft_then_approve", "action_levels": {"not_a_real_type": "auto_execute"}}
    )
    assert resp.status_code == 422

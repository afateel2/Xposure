"""
Route contracts for /demo/*: the shapes the frontend and the visibility
layer rely on (brief section 4), the demo-mode gate, and the 409 rules.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import require_user
from app.config import settings
from app.db.models import Action, AuditLog
from app.db.session import get_db
from app.demo import constants as C
from app.demo import runner
from app.demo.tracker import TRACKER
from app.main import app

from .auth_fixtures import TEST_USER
from .demo_fixtures import demo_env  # noqa: F401  (fixture)

RUN_KEYS = {"run_id", "status", "started_at", "finished_at", "stages", "note_en", "note_ar"}
STAGE_KEYS = {"key", "label_en", "label_ar", "status", "detail_en", "detail_ar", "counts", "started_at", "ended_at"}


@pytest.fixture()
def client(demo_env):
    def _db():
        with demo_env.session() as db:
            yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_user] = lambda: TEST_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_user, None)


def test_idle_run_has_the_contract_shape_with_all_stages_pending(client):
    body = client.get("/demo/run").json()
    assert RUN_KEYS <= set(body)
    assert body["status"] == "idle" and body["run_id"] is None
    assert [s["key"] for s in body["stages"]] == list(C.STAGE_KEYS)
    assert all(STAGE_KEYS <= set(s) and s["status"] == "pending" for s in body["stages"])
    assert "replays the regulator portal from a local mirror folder" in body["note_en"]
    assert body["note_ar"]


def test_status_reports_baseline_with_the_portal_and_versions(client, demo_env):
    demo_env.seed_baseline()
    body = client.get("/demo/status").json()
    assert body["phase"] == "baseline" and body["demo_mode"] is True
    assert [v["version_label"] for v in body["regulation_versions"]] == ["1-2018"]
    assert body["regulation_versions"][0]["clause_count"] == 2
    assert body["can_scan"] is True and body["needs_reset"] is False
    docs = {d["version_label"]: d["status"] for d in body["portal"]["documents"]}
    assert docs == {"1-2018": "known", "2-2024": "new"}
    assert body["portal"]["simulated"] is True and body["portal"]["new_available"] == 1
    assert body["llm_cache"]["enabled"] is True


def test_status_phases_follow_the_run(client, demo_env):
    demo_env.seed_baseline()
    assert client.get("/demo/status").json()["phase"] == "baseline"
    TRACKER.try_start("run-phase")
    assert client.get("/demo/status").json()["phase"] == "scanning"
    assert client.get("/demo/status").json()["can_reset"] is False


def test_status_review_ready_after_a_full_scan(client, demo_env):
    demo_env.seed_baseline()
    TRACKER.try_start("run-1")
    runner._execute("run-1")
    body = client.get("/demo/status").json()
    assert body["phase"] == "review_ready"
    assert body["pending_actions"] == 2 and body["total_actions"] == 4
    assert {v["version_label"] for v in body["regulation_versions"]} == {"1-2018", "2-2024"}
    run = client.get("/demo/run").json()
    assert run["status"] == "awaiting_review" and RUN_KEYS <= set(run)


def test_status_flags_needs_reset_after_a_failed_run(client, demo_env):
    demo_env.seed_baseline()
    TRACKER.try_start("run-1")
    TRACKER.fail("boom")
    body = client.get("/demo/status").json()
    assert body["needs_reset"] is True and body["phase"] == "baseline"


def test_scan_returns_202_with_a_run_id_and_double_click_is_idempotent(client, demo_env, monkeypatch):
    demo_env.seed_baseline()
    monkeypatch.setattr(runner, "_execute", lambda run_id: None)  # stay "running"
    first = client.post("/demo/scan")
    assert first.status_code == 202
    body = first.json()
    assert body["run_id"].startswith("run-") and body["status"] == "running" and body["already_running"] is False
    second = client.post("/demo/scan").json()
    assert second["already_running"] is True and second["run_id"] == body["run_id"]
    assert client.get("/demo/run").json()["run_id"] == body["run_id"]


def test_reset_returns_the_baseline_summary_and_appends_the_audit_event(client, demo_env):
    demo_env.seed_baseline()
    response = client.post("/demo/reset")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["phase"] == "baseline"
    assert {"cleared", "baseline", "org", "company_reset", "backup", "took_ms"} <= set(body)
    with demo_env.session() as db:
        events = [e.event for e in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert events[-1] == "demo_reset"


def test_reset_is_409_while_a_scan_runs(client, demo_env):
    demo_env.seed_baseline()
    TRACKER.try_start("run-busy")
    response = client.post("/demo/reset")
    assert response.status_code == 409 and "scan is running" in response.json()["detail"]


def test_destructive_endpoints_are_403_when_demo_mode_is_off(client, demo_env, monkeypatch):
    demo_env.seed_baseline()
    monkeypatch.setattr(settings, "demo_mode", False)
    assert client.post("/demo/reset").status_code == 403
    assert client.post("/demo/scan").status_code == 403
    body = client.get("/demo/status").json()  # reading stays allowed
    assert body["demo_mode"] is False and body["can_scan"] is False and body["stage_pacing_ms"] == 0
    with demo_env.session() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.event == "demo_reset")) is None
        assert db.scalar(select(Action)) is None

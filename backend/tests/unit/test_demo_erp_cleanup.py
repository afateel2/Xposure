"""
Demo reset removes the Odoo tasks Xposure created (best effort).

Uses the FakeOdoo pattern from test_erp.py (a stateful fake behind an
httpx.MockTransport, so the real client and service code runs, with no
network), extended with the two project.task calls the cleanup needs. The
reset itself runs on the in-memory SQLite fixture from demo_fixtures.py.
"""

import time

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Action, AuditLog
from app.demo import baseline, erp_cleanup
from app.erp import client as erp_client
from app.erp.client import ErpError, OdooClient
from app.erp.service import OdooService
from app.erp.settings import get_erp_settings

from .demo_fixtures import demo_env  # noqa: F401  (fixture)
from .test_erp import PASSWORD, FakeOdoo


class CleanupOdoo(FakeOdoo):
    """FakeOdoo plus project.task search_read and unlink."""

    def __init__(self):
        super().__init__()
        self.projects.append({"id": 2, "name": "Someone Elses Project"})
        self.unlinked: list[int] = []

    def add_task(self, task_id: int, project_id: int = 1, name: str = "Xposure task") -> None:
        self.tasks[task_id] = {
            "id": task_id, "name": name, "description": "", "project_id": project_id, "stage_id": 10,
            "user_ids": [], "date_deadline": False, "priority": "0", "state": "01_in_progress",
        }

    def m_project_task__search_read(self, a, kw):
        rows = list(self.tasks.values())
        for field, op, value in a[0]:
            assert op == "="
            rows = [t for t in rows if t[field] == value]
        assert kw.get("context") == {"active_test": False}, "archived tasks must be included"
        return [{"id": t["id"]} for t in rows][: kw.get("limit") or None]

    def m_project_task__unlink(self, a, kw):
        for task_id in a[0]:
            del self.tasks[task_id]  # KeyError for a missing id, like Odoo's MissingError
            self.unlinked.append(task_id)
        return True


@pytest.fixture()
def odoo(monkeypatch):
    fake = CleanupOdoo()
    monkeypatch.setattr(erp_client, "TRANSPORT", httpx.MockTransport(fake.handler))
    monkeypatch.setenv("ODOO_URL", "http://odoo.test:8069")
    monkeypatch.setenv("ODOO_DB", "xposure_erp")
    monkeypatch.setenv("ODOO_USER", "admin")
    monkeypatch.setenv("ODOO_PASSWORD", PASSWORD)
    return fake


def _action(env, change_id=1, **payload):
    with env.session() as db:
        db.add(Action(change_id=change_id, type="notify_owner", level="draft_then_approve",
                      status="awaiting_confirmation", payload_json=payload))
        db.commit()


# ── which ids are collected ───────────────────────────────────────────────

def test_collects_current_and_detached_task_ids_only(demo_env):
    _action(demo_env, erp={"system": "odoo", "task_id": 101})
    _action(demo_env, erp_detached=[{"task_id": 102, "reason": "delegation undone"}, {"task_id": "103"}, {"no": "id"}])
    _action(demo_env, erp={"system": "odoo", "task_id": 101}, erp_detached=[{"task_id": 104}])
    _action(demo_env, impact_node_name="Access Control Policy")  # no ERP data
    _action(demo_env, erp="not a dict", erp_detached="not a list")
    with demo_env.session() as db:
        assert erp_cleanup.collect_task_ids(db) == [101, 102, 103, 104]


# ── the service call ──────────────────────────────────────────────────────

def test_delete_task_deletes_only_inside_the_xposure_project(odoo):
    odoo.add_task(100)
    odoo.add_task(200, project_id=2, name="belongs to someone else")
    with OdooClient(get_erp_settings()) as client:
        service = OdooService(client, get_erp_settings())
        assert service.delete_task(100) is True
        assert service.delete_task(100) is False  # already gone
        assert service.delete_task(200) is False  # other project: never touched
        assert service.delete_task(999) is False  # never existed
    assert odoo.unlinked == [100]
    assert 200 in odoo.tasks


# ── clear_erp_tasks ───────────────────────────────────────────────────────

def test_clear_deletes_referenced_tasks_and_counts_the_gone_ones(odoo):
    odoo.add_task(100)
    odoo.add_task(101)
    odoo.add_task(150)  # not referenced by any action: must survive
    result = erp_cleanup.clear_erp_tasks([100, 101, 102])
    assert result == {"deleted": 2, "referenced": 3, "already_gone": 1}
    assert set(odoo.tasks) == {150}


def test_no_referenced_tasks_means_no_odoo_call_at_all(odoo):
    assert erp_cleanup.clear_erp_tasks([]) == {"deleted": 0, "referenced": 0, "already_gone": 0}
    assert odoo.calls == []


def test_odoo_down_is_reported_not_raised(odoo):
    odoo.mode = "down"
    result = erp_cleanup.clear_erp_tasks([100])
    assert result["deleted"] == 0 and result["referenced"] == 1
    assert result["skipped_reason"].startswith("unreachable")


@pytest.mark.parametrize("mode,prefix", [("timeout", "timeout"), ("server_error", "api"), ("garbage", "api"), ("odoo_error", "api")])
def test_every_odoo_failure_mode_is_swallowed_into_skipped_reason(odoo, mode, prefix):
    odoo.mode = mode
    result = erp_cleanup.clear_erp_tasks([100])
    assert result["deleted"] == 0 and result["skipped_reason"].startswith(prefix)
    assert PASSWORD not in str(result)


def test_not_configured_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "")
    monkeypatch.setenv("ODOO_PASSWORD", "")
    result = erp_cleanup.clear_erp_tasks([100])
    assert result["deleted"] == 0 and result["skipped_reason"].startswith("not_configured")


def test_partial_progress_is_kept_when_odoo_fails_midway(odoo):
    odoo.add_task(100)
    odoo.add_task(101)
    original = odoo.m_project_task__unlink

    def flaky_unlink(a, kw):
        if a[0] == [101]:
            odoo.mode = "down"
        return original(a, kw)

    odoo.m_project_task__unlink = flaky_unlink
    result = erp_cleanup.clear_erp_tasks([100, 101, 102])
    assert result["deleted"] == 2  # 100 and 101 were unlinked before the outage
    assert result["skipped_reason"].startswith("unreachable")  # 102 was not reached
    assert 100 not in odoo.tasks


def test_a_hung_odoo_cannot_slow_the_reset_past_the_deadline(odoo, monkeypatch):
    monkeypatch.setattr(erp_cleanup, "DEADLINE_SECONDS", 0.3)
    original = odoo.handler

    def slow(request):
        time.sleep(2)
        return original(request)

    monkeypatch.setattr(erp_client, "TRANSPORT", httpx.MockTransport(slow))
    started = time.monotonic()
    result = erp_cleanup.clear_erp_tasks([100])
    assert time.monotonic() - started < 1.5
    assert result["skipped_reason"].startswith("timeout") and result["deleted"] == 0


def test_client_timeouts_can_be_overridden_for_short_calls(odoo):
    with OdooClient(get_erp_settings(), connect_timeout=1.0, read_timeout=2.0) as client:
        assert client._http.timeout.connect == 1.0 and client._http.timeout.read == 2.0
    with OdooClient(get_erp_settings()) as client:
        assert client._http.timeout.connect == erp_client.CONNECT_TIMEOUT


# ── the reset ─────────────────────────────────────────────────────────────

def test_reset_deletes_the_odoo_tasks_and_reports_it_in_response_and_audit(demo_env, odoo):
    demo_env.seed_baseline()
    odoo.add_task(100)
    odoo.add_task(101)
    odoo.add_task(500, name="unrelated task in the same project, not referenced")
    _action(demo_env, erp={"system": "odoo", "task_id": 100, "stage": "New"})
    _action(demo_env, erp_detached=[{"system": "odoo", "task_id": 101, "reason": "delegation undone"}])

    result = baseline.reset_to_baseline()

    assert result["status"] == "ok"
    assert result["erp_cleared"] == {"deleted": 2, "referenced": 2, "already_gone": 0}
    assert set(odoo.tasks) == {500}
    with demo_env.session() as db:
        assert db.scalar(select(Action)) is None  # the actions are gone too
        last = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert last.event == "demo_reset"
    assert last.payload_json["erp_cleared"]["deleted"] == 2


def test_reset_succeeds_and_reports_skipped_when_odoo_is_down(demo_env, odoo):
    demo_env.seed_baseline()
    odoo.add_task(100)
    _action(demo_env, erp={"system": "odoo", "task_id": 100})
    odoo.mode = "down"

    started = time.monotonic()
    result = baseline.reset_to_baseline()

    assert time.monotonic() - started < erp_cleanup.DEADLINE_SECONDS
    assert result["status"] == "ok" and result["phase"] == "baseline"
    assert result["erp_cleared"]["deleted"] == 0
    assert result["erp_cleared"]["skipped_reason"].startswith("unreachable")
    with demo_env.session() as db:
        assert db.scalar(select(Action)) is None  # the reset itself was not affected
        last = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert last.payload_json["erp_cleared"]["skipped_reason"].startswith("unreachable")


def test_reset_with_no_erp_tasks_never_calls_odoo(demo_env, odoo):
    demo_env.seed_baseline()
    _action(demo_env, impact_node_name="Access Control Policy")
    result = baseline.reset_to_baseline()
    assert result["erp_cleared"] == {"deleted": 0, "referenced": 0, "already_gone": 0}
    assert odoo.calls == []


def test_reset_survives_an_unexpected_cleanup_bug(demo_env, monkeypatch):
    demo_env.seed_baseline()
    _action(demo_env, erp={"task_id": 100})

    def boom(ids):
        raise RuntimeError("bug in cleanup")

    monkeypatch.setattr(erp_cleanup, "clear_erp_tasks", boom)
    result = baseline.reset_to_baseline()
    assert result["status"] == "ok"
    assert result["erp_cleared"]["skipped_reason"] == "RuntimeError: bug in cleanup"

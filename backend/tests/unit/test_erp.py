"""
ERP (Odoo) integration tests.

No network and no real Odoo: a stateful FakeOdoo behind an httpx.MockTransport
answers the same JSON-RPC calls the client makes (common.version,
common.authenticate, object.execute_kw on project.project / project.task /
project.task.type / hr.employee / res.users). The real client, service,
delegate and sync code runs against it, and the routes run against an
in-memory SQLite database (same pattern as test_routes.py).

The live behaviour against a real Odoo 17 container is verified separately
(see the ODOO agent report); these tests pin the logic and the failure modes.
"""

import json
import logging
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import require_user
from app.db.base import Base
from app.db.models import Action, AuditLog, Change, Clause, Impact, OrgNode, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.erp import client as erp_client
from app.erp.client import ErpError, OdooClient
from app.erp.service import stage_key_for
from app.erp.settings import ErpSettings
from app.main import app

from .auth_fixtures import TEST_USER

PASSWORD = "s3cret-pass-for-tests"


# ── fake Odoo ───────────────────────────────────────────────────────────

class FakeOdoo:
    def __init__(self):
        self.mode = "up"  # up | down | timeout | garbage | server_error
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[str] = []
        self.stages = [
            {"id": 10, "name": "New", "sequence": 1, "project_ids": [1]},
            {"id": 11, "name": "In Progress", "sequence": 2, "project_ids": [1]},
            {"id": 12, "name": "Waiting for Confirmation", "sequence": 3, "project_ids": [1]},
            {"id": 13, "name": "Done", "sequence": 4, "project_ids": [1]},
        ]
        self.projects = [{"id": 1, "name": "Compliance Actions"}]
        self.users = {7: "Khalid Al-Harbi", 8: "Reem Al-Mutairi"}
        self.employees = [
            {"id": 1, "name": "Khalid Al-Harbi", "job_title": "IT Security Lead", "work_email": "khalid@example.test",
             "department_id": [1, "Information Technology"], "user_id": [7, "Khalid Al-Harbi"], "active": True},
            {"id": 2, "name": "Reem Al-Mutairi", "job_title": "Compliance Officer", "work_email": "reem@example.test",
             "department_id": [2, "Governance and Compliance"], "user_id": [8, "Reem Al-Mutairi"], "active": True},
            {"id": 3, "name": "Nasser Al-Dossari", "job_title": "Operations Manager", "work_email": None,
             "department_id": False, "user_id": False, "active": True},
            # the integration account's own employee (uid 2): must not be offered
            {"id": 4, "name": "Administrator", "job_title": None, "work_email": None,
             "department_id": False, "user_id": [2, "Administrator"], "active": True},
        ]
        self.tasks: dict[int, dict] = {}
        self._next_task = 100

    # test helpers
    def move_task(self, task_id: int, stage_name: str):
        stage = next(s for s in self.stages if s["name"] == stage_name)
        self.tasks[task_id]["stage_id"] = stage["id"]

    # transport
    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "down":
            raise httpx.ConnectError("connection refused", request=request)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if self.mode == "server_error":
            return httpx.Response(502, text="bad gateway")
        if self.mode == "garbage":
            return httpx.Response(200, text="<html>not json</html>")
        if self.mode == "odoo_error":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {
                "code": 200, "message": "Odoo Server Error",
                "data": {"message": "Access Denied by fake\nTraceback line that must not leak"}}})
        self.bodies.append(request.content.decode())
        body = json.loads(request.content)
        params = body["params"]
        service, method, args = params["service"], params["method"], params["args"]
        self.calls.append((service, method))
        try:
            result = self.dispatch(service, method, args)
        except KeyError as exc:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": {
                "code": 200, "message": "Odoo Server Error",
                "data": {"message": f"Record does not exist or has been deleted: {exc}"}}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    def dispatch(self, service, method, args):
        if service == "common" and method == "version":
            return {"server_version": "17.0-fake", "protocol_version": 1}
        if service == "common" and method == "authenticate":
            db, login, password, _ = args
            return 2 if (login == "admin" and password == PASSWORD and db == "xposure_erp") else False
        assert service == "object" and method == "execute_kw", (service, method)
        _db, uid, password, model, m, a, kw = args
        assert uid == 2 and password == PASSWORD, "object call without valid credentials"
        return getattr(self, "m_" + model.replace(".", "_") + "__" + m)(a, kw)

    # model methods: name is m_<model with dots as underscores>__<method>
    def m_project_project__search_read(self, a, kw):
        domain = a[0]
        rows = self.projects
        for field, op, value in domain:
            assert field == "name" and op == "="
            rows = [r for r in rows if r["name"] == value]
        return [dict(r) for r in rows][: kw.get("limit") or None]

    def m_project_task_type__search_read(self, a, kw):
        return sorted(({"id": s["id"], "name": s["name"], "sequence": s["sequence"]} for s in self.stages),
                      key=lambda s: (s["sequence"], s["id"]))

    def m_hr_employee__search_read(self, a, kw):
        rows = [e for e in self.employees if e["active"]]
        for field, op, value in a[0]:
            if field == "user_id" and op == "!=":
                rows = [e for e in rows if not (e["user_id"] and e["user_id"][0] == value)]
        return [dict(e) for e in rows]

    def m_hr_employee__read(self, a, kw):
        return [dict(e) for e in self.employees if e["id"] in a[0]]

    def m_res_users__read(self, a, kw):
        return [{"id": i, "name": self.users[i]} for i in a[0] if i in self.users]

    def m_project_task__create(self, a, kw):
        values = a[0]
        task_id = self._next_task
        self._next_task += 1
        user_ids = []
        for cmd in values.get("user_ids", []):
            assert cmd[0] == 6
            user_ids = list(cmd[2])
        self.tasks[task_id] = {
            "id": task_id, "name": values["name"], "description": values.get("description", ""),
            "project_id": values["project_id"], "stage_id": values.get("stage_id", 10),
            "user_ids": user_ids, "date_deadline": values.get("date_deadline") or False,
            "priority": values.get("priority", "0"), "state": "01_in_progress",
        }
        return task_id

    def m_project_task__read(self, a, kw):
        rows = []
        for task_id in a[0]:
            t = self.tasks.get(task_id)
            if t is None:
                continue
            stage = next(s for s in self.stages if s["id"] == t["stage_id"])
            rows.append({
                "id": t["id"], "name": t["name"], "stage_id": [stage["id"], stage["name"]],
                "user_ids": t["user_ids"], "project_id": [1, "Compliance Actions"],
                "date_deadline": t["date_deadline"], "state": t["state"], "write_date": "2026-09-19 10:00:00",
            })
        return rows


@pytest.fixture
def fake(monkeypatch):
    odoo = FakeOdoo()
    monkeypatch.setattr(erp_client, "TRANSPORT", httpx.MockTransport(odoo.handler))
    monkeypatch.setenv("ODOO_URL", "http://odoo.test:8069")
    monkeypatch.setenv("ODOO_PUBLIC_URL", "http://127.0.0.1:8069")
    monkeypatch.setenv("ODOO_DB", "xposure_erp")
    monkeypatch.setenv("ODOO_USER", "admin")
    monkeypatch.setenv("ODOO_PASSWORD", PASSWORD)
    monkeypatch.setenv("XPOSURE_PUBLIC_URL", "http://xposure.test:3010")
    return odoo


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "")
    monkeypatch.setenv("ODOO_PASSWORD", "")


# ── database fixtures (same shape as test_routes.py) ────────────────────

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_user] = lambda: TEST_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def seeded(db):
    regulator = Regulator(code="nca", name_ar="الهيئة", name_en="National Cybersecurity Authority", weight=1.0)
    db.add(regulator)
    db.flush()
    regulation = Regulation(
        regulator_id=regulator.id, code="ecc", title_ar="الضوابط", title_en="Essential Cybersecurity Controls"
    )
    db.add(regulation)
    db.flush()
    v1 = RegulationVersion(regulation_id=regulation.id, version_label="1-2018", file_sha256="aaa", source_url="")
    v2 = RegulationVersion(regulation_id=regulation.id, version_label="2-2024", file_sha256="bbb", source_url="")
    db.add_all([v1, v2])
    db.flush()
    db.add_all([
        Clause(version_id=v1.id, clause_id="2-5-3", text_en="Old.", order_index=0),
        Clause(version_id=v2.id, clause_id="2-5-3", text_en="New.", order_index=0),
    ])
    db.flush()
    change = Change(
        regulation_id=regulation.id, from_version_id=v1.id, to_version_id=v2.id,
        old_clause_id="2-5-3", new_clause_id="2-5-3", match_kind="exact_id", change_type="tightened",
        material=True, confidence=0.92,
        summary_en="Encryption keys must now be at least 256 bits " + chr(0x2014) + " see the annex. More text.",
        summary_ar="يجب ألا يقل طول مفاتيح التشفير عن 256 بتا.",
        effective_date=date.today() + timedelta(days=10), grace_days=5,
        diff_spans_json={"ops": []},
    )
    db.add(change)
    db.flush()
    node = OrgNode(type="policy", name="Cryptography Policy", attrs_json={})
    db.add(node)
    db.flush()
    impact = Impact(
        change_id=change.id, node_id=node.id, path_json={"scope_match": "exact", "depth": 0, "summary": node.name},
        note_en="Update.", note_ar="حدث.", recommended_actions_json=["update_policy"],
    )
    db.add(impact)
    db.flush()
    due = date.today() + timedelta(days=15)
    action = Action(
        change_id=change.id, type="update_policy", level="draft_then_approve", status="pending",
        due_date=due,
        payload_json={
            "impact_id": impact.id, "impact_node_name": "Cryptography Policy", "clause_id": "2-5-3",
            "priority_band": "critical", "priority_score": 91.5,
        },
    )
    second = Action(
        change_id=change.id, type="collect_evidence", level="draft_then_approve", status="pending",
        payload_json={"impact_id": impact.id, "priority_band": "medium"},
    )
    db.add_all([action, second])
    db.commit()
    return {"change_id": change.id, "action_id": action.id, "second_action_id": second.id, "due": due.isoformat()}


def audit_events(db, action_id):
    return [
        (r.event, r.payload_json or {})
        for r in db.scalars(
            select(AuditLog).where(AuditLog.ref_type == "action", AuditLog.ref_id == action_id).order_by(AuditLog.id)
        )
    ]


def delegate(client, action_id, employee_id=1, **extra):
    return client.post(f"/actions/{action_id}/delegate", json={"channel": "odoo", "employee_id": employee_id, **extra})


# ── client ──────────────────────────────────────────────────────────────

def test_client_authenticates_once_and_never_leaks_the_password(fake, caplog):
    settings = ErpSettings(_env_file=None, odoo_url="http://odoo.test:8069", odoo_password=PASSWORD)
    with caplog.at_level(logging.DEBUG):
        with OdooClient(settings) as c:
            assert c.authenticate() == 2
            assert c.authenticate() == 2
            c.search_read("project.project", [["name", "=", "Compliance Actions"]], ["name"])
    assert fake.calls.count(("common", "authenticate")) == 1
    assert PASSWORD not in caplog.text
    assert PASSWORD not in repr(settings)


def test_client_wrong_password_is_an_auth_error_without_the_secret(fake):
    settings = ErpSettings(_env_file=None, odoo_url="http://odoo.test:8069", odoo_password="wrong-password-xyz")
    with OdooClient(settings) as c, pytest.raises(ErpError) as info:
        c.authenticate()
    assert info.value.kind == "auth"
    assert "wrong-password-xyz" not in info.value.combined


@pytest.mark.parametrize(
    "mode,kind", [("down", "unreachable"), ("timeout", "timeout"), ("server_error", "api"), ("garbage", "api")]
)
def test_client_failure_modes_map_to_honest_error_kinds(fake, mode, kind):
    fake.mode = mode
    settings = ErpSettings(_env_file=None, odoo_url="http://odoo.test:8069", odoo_password=PASSWORD)
    with OdooClient(settings) as c, pytest.raises(ErpError) as info:
        c.version()
    assert info.value.kind == kind
    assert info.value.message_en and info.value.message_ar


def test_client_surfaces_odoo_error_body_even_on_http_200(fake):
    fake.mode = "odoo_error"
    settings = ErpSettings(_env_file=None, odoo_url="http://odoo.test:8069", odoo_password=PASSWORD)
    with OdooClient(settings) as c, pytest.raises(ErpError) as info:
        c.version()
    assert info.value.kind == "api"
    assert "Access Denied by fake" in info.value.message_en


def test_client_requires_configuration(unconfigured):
    with pytest.raises(ErpError) as info:
        OdooClient(ErpSettings(_env_file=None))
    assert info.value.kind == "not_configured"


def test_stage_key_mapping():
    assert stage_key_for("New") == "new"
    assert stage_key_for("In Progress") == "in_progress"
    assert stage_key_for("Waiting for Confirmation") == "waiting"
    assert stage_key_for("Done") == "done"
    assert stage_key_for("  done  ") == "done"
    assert stage_key_for("Something else") == "other"
    # the green check on a Kanban card closes the task without moving it
    assert stage_key_for("In Progress", "1_done") == "done"


# ── GET /erp/status, /erp/employees ─────────────────────────────────────

def test_status_not_configured_is_honest(client, unconfigured):
    body = client.get("/erp/status").json()
    assert body["configured"] is False
    assert body["reachable"] is False
    assert body["system"] == "odoo"
    assert "not configured" in body["message_en"].lower()
    assert body["message_ar"]


def test_status_connected(client, fake):
    body = client.get("/erp/status").json()
    assert body["configured"] is True and body["reachable"] is True
    assert body["system"] == "odoo"
    assert body["version"] == "17.0-fake"
    assert body["database"] == "xposure_erp"
    assert body["url"] == "http://127.0.0.1:8069"
    assert body["project_found"] is True
    assert "17.0-fake" in body["message_en"]
    assert PASSWORD not in json.dumps(body)


def test_status_unreachable(client, fake):
    fake.mode = "down"
    body = client.get("/erp/status").json()
    assert body["configured"] is True and body["reachable"] is False
    assert body["message_en"] and body["message_ar"]


def test_status_reachable_but_login_rejected(client, fake, monkeypatch):
    monkeypatch.setenv("ODOO_PASSWORD", "not-the-password")
    body = client.get("/erp/status").json()
    assert body["reachable"] is True and body["authenticated"] is False
    assert "rejected the login" in body["message_en"]


def test_employees_shape(client, fake):
    rows = client.get("/erp/employees").json()
    assert [r["id"] for r in rows] == [1, 2, 3]
    assert set(rows[0]) == {"id", "name", "job_title", "work_email", "department"}
    assert rows[0]["department"] == "Information Technology"
    assert rows[2]["department"] is None and rows[2]["work_email"] is None


def test_employees_fails_loudly_when_odoo_is_down(client, fake):
    fake.mode = "down"
    response = client.get("/erp/employees")
    assert response.status_code == 503
    assert " | " in response.json()["detail"]


# ── delegate through Odoo ───────────────────────────────────────────────

def test_delegate_odoo_creates_task_and_records_everything(client, fake, seeded, db):
    response = delegate(client, seeded["action_id"], 1, note="Please review before Thursday.")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["assignee_name"] == "Khalid Al-Harbi"
    assert body["assignee_contact"] == "khalid@example.test"
    erp = body["erp"]
    assert erp["system"] == "odoo" and erp["stage"] == "New" and erp["stage_key"] == "new"
    assert erp["assignee"] == "Khalid Al-Harbi"
    assert erp["url"] == f"http://127.0.0.1:8069/web#id={erp['task_id']}&model=project.task&view_type=form"

    task = fake.tasks[erp["task_id"]]
    assert task["project_id"] == 1 and task["user_ids"] == [7]
    assert task["date_deadline"] == seeded["due"]
    assert task["priority"] == "1"  # critical band is starred
    assert "2-5-3" in task["name"] and "ECC" in task["name"]
    assert "2-5-3" in task["description"]
    assert "Update policy" in task["name"]
    assert "Encryption keys must now be at least 256 bits" in task["name"]
    description = task["description"]
    for needle in (
        "Update policy", "Cryptography Policy", "critical", "91.5", seeded["due"],
        f"http://xposure.test:3010/changes/{seeded['change_id']}", "Please review before Thursday.",
        "Essential Cybersecurity Controls", "يجب ألا يقل",
    ):
        assert needle in description, needle
    assert chr(0x2014) not in task["name"] + description

    db.expire_all()
    action = db.get(Action, seeded["action_id"])
    assert action.status == "awaiting_confirmation"
    assert action.assignee_name == "Khalid Al-Harbi" and action.assignee_contact == "khalid@example.test"
    assert action.delegated_at is not None
    assert action.payload_json["erp"]["task_id"] == erp["task_id"]
    assert action.payload_json["impact_node_name"] == "Cryptography Policy"  # existing payload kept

    events = dict(audit_events(db, action.id))
    created = events["erp_task_created"]
    assert created["task_id"] == erp["task_id"] and created["url"] == erp["url"]
    assert created["employee"]["name"] == "Khalid Al-Harbi" and created["employee"]["id"] == 1
    delegated = events["action_delegated"]
    assert delegated["previous_status"] == "pending" and delegated["via"] == "erp"
    assert delegated["notification"]["channel"] == "odoo"


def test_delegate_to_employee_without_a_user_names_them_in_the_description(client, fake, seeded):
    response = delegate(client, seeded["action_id"], 3)
    assert response.status_code == 200
    erp = response.json()["erp"]
    task = fake.tasks[erp["task_id"]]
    assert task["user_ids"] == []
    assert "Nasser Al-Dossari" in task["description"]
    assert erp["assignee"] == "Nasser Al-Dossari"  # falls back to the employee name
    assert response.json()["assignee_contact"] is None


def test_post_erp_tasks_uses_the_same_path(client, fake, seeded):
    response = client.post(
        "/erp/tasks", json={"action_id": seeded["action_id"], "employee_id": 2, "note": "n"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_confirmation"
    assert response.json()["erp"]["assignee"] == "Reem Al-Mutairi"


def test_post_erp_tasks_refuses_a_non_pending_action(client, fake, seeded):
    assert delegate(client, seeded["action_id"]).status_code == 200
    again = client.post("/erp/tasks", json={"action_id": seeded["action_id"], "employee_id": 1})
    assert again.status_code == 409
    assert len(fake.tasks) == 1


def test_delegate_odoo_down_fails_loudly_and_leaves_the_action_untouched(client, fake, seeded, db):
    fake.mode = "down"
    response = delegate(client, seeded["action_id"])
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert " | " in detail
    english, arabic = detail.split(" | ", 1)
    assert "not reachable" in english and any("؀" <= ch <= "ۿ" for ch in arabic)
    assert chr(0x2014) not in detail

    db.expire_all()
    action = db.get(Action, seeded["action_id"])
    assert action.status == "pending"
    assert action.assignee_name is None and action.assignee_contact is None and action.delegated_at is None
    assert "erp" not in action.payload_json
    assert audit_events(db, action.id) == []
    assert fake.tasks == {}


def test_delegate_odoo_timeout_is_a_504_and_untouched(client, fake, seeded, db):
    fake.mode = "timeout"
    response = delegate(client, seeded["action_id"])
    assert response.status_code == 504
    db.expire_all()
    assert db.get(Action, seeded["action_id"]).status == "pending"


def test_delegate_odoo_not_configured_is_a_503_and_untouched(client, unconfigured, seeded, db):
    response = delegate(client, seeded["action_id"])
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
    db.expire_all()
    assert db.get(Action, seeded["action_id"]).status == "pending"


def test_delegate_odoo_unknown_employee_is_a_404_and_untouched(client, fake, seeded, db):
    response = delegate(client, seeded["action_id"], 99)
    assert response.status_code == 404
    db.expire_all()
    assert db.get(Action, seeded["action_id"]).status == "pending"
    assert fake.tasks == {}


def test_delegate_odoo_missing_project_is_reported_not_faked(client, fake, seeded, db):
    fake.projects.clear()
    response = delegate(client, seeded["action_id"])
    assert response.status_code == 502
    assert "Compliance Actions" in response.json()["detail"]
    db.expire_all()
    assert db.get(Action, seeded["action_id"]).status == "pending"


def test_delegate_validation(client, fake, seeded):
    assert client.post(f"/actions/{seeded['action_id']}/delegate", json={}).status_code == 422
    assert client.post(f"/actions/{seeded['action_id']}/delegate", json={"channel": "odoo"}).status_code == 422
    # the original name-only delegation still works and never touches Odoo
    legacy = client.post(f"/actions/{seeded['second_action_id']}/delegate", json={"assignee_name": "Fatima"})
    assert legacy.status_code == 200
    assert fake.calls == []


def test_undo_of_an_odoo_delegation_says_the_task_still_exists(client, fake, seeded, db):
    delegate(client, seeded["action_id"])
    undone = client.post(f"/actions/{seeded['action_id']}/undo")
    assert undone.status_code == 200
    assert undone.json()["status"] == "pending"
    assert any("odoo" in effect for effect in undone.json()["side_effects_not_reversed"])
    db.expire_all()
    action = db.get(Action, seeded["action_id"])
    assert action.assignee_name is None
    # the action stops pointing at the Odoo task, but keeps a record of it
    assert "erp" not in action.payload_json
    assert action.payload_json["erp_detached"][0]["task_id"] == 100
    assert client.get("/erp/tasks?refresh=false").json()["items"] == []
    events = [e for e, _ in audit_events(db, action.id)]
    assert "erp_task_created" in events and "action_status_reverted" in events  # audit rows remain


def test_change_detail_exposes_the_erp_block(client, fake, seeded):
    delegate(client, seeded["action_id"])
    detail = client.get(f"/changes/{seeded['change_id']}").json()
    actions = [a for impact in detail["impacts"] for a in impact["actions"]]
    with_erp = [a for a in actions if a["id"] == seeded["action_id"]][0]
    assert with_erp["erp"]["system"] == "odoo" and with_erp["erp"]["stage_key"] == "new"
    other = [a for a in actions if a["id"] == seeded["second_action_id"]][0]
    assert other["erp"] is None


# ── live status and two-way sync ────────────────────────────────────────

def test_get_task_live_state(client, fake, seeded):
    task_id = delegate(client, seeded["action_id"]).json()["erp"]["task_id"]
    fake.move_task(task_id, "In Progress")
    body = client.get(f"/erp/tasks/{task_id}").json()
    assert set(body) == {"task_id", "url", "stage", "stage_key", "assignee", "synced_at"}
    assert body["stage"] == "In Progress" and body["stage_key"] == "in_progress"
    assert body["assignee"] == "Khalid Al-Harbi"


def test_get_task_missing_in_odoo_is_a_404(client, fake):
    assert client.get("/erp/tasks/424242").status_code == 404


def test_sync_records_stage_changes_and_closes_the_action_on_done(client, fake, seeded, db):
    task_id = delegate(client, seeded["action_id"]).json()["erp"]["task_id"]

    # nothing changed yet: no synced event
    first = client.post("/erp/sync").json()
    assert first["checked"] == 1 and first["changed"] == [] and first["completed"] == []

    fake.move_task(task_id, "In Progress")
    second = client.post("/erp/sync").json()
    assert second["changed"] == [seeded["action_id"]] and second["completed"] == []
    db.expire_all()
    action = db.get(Action, seeded["action_id"])
    assert action.status == "awaiting_confirmation"
    assert action.payload_json["erp"]["stage"] == "In Progress"
    synced = [p for e, p in audit_events(db, action.id) if e == "erp_task_synced"]
    assert synced[-1]["previous_stage"] == "New" and synced[-1]["stage"] == "In Progress"

    fake.move_task(task_id, "Done")
    third = client.post("/erp/sync").json()
    assert third["completed"] == [seeded["action_id"]]
    db.expire_all()
    action = db.get(Action, seeded["action_id"])
    assert action.status == "done" and action.confirmed_at is not None
    events = audit_events(db, action.id)
    closed = [p for e, p in events if e == "action_confirmed_done"][0]
    assert closed["via"] == "erp_sync" and closed["previous_status"] == "awaiting_confirmation"
    assert closed["task_id"] == task_id and closed["erp_stage"] == "Done"
    assert action.payload_json["erp"]["stage_key"] == "done"

    # idempotent: a further sync adds nothing
    before = len(audit_events(db, action.id))
    again = client.post("/erp/sync").json()
    assert again["changed"] == [] and again["completed"] == []
    db.expire_all()
    assert len(audit_events(db, action.id)) == before


def test_undoing_an_erp_close_is_sticky(client, fake, seeded, db):
    task_id = delegate(client, seeded["action_id"]).json()["erp"]["task_id"]
    fake.move_task(task_id, "Done")
    client.post("/erp/sync")
    undone = client.post(f"/actions/{seeded['action_id']}/undo").json()
    assert undone["status"] == "awaiting_confirmation"
    client.post("/erp/sync")  # Odoo is still Done, but the human's undo must stand
    db.expire_all()
    assert db.get(Action, seeded["action_id"]).status == "awaiting_confirmation"


def test_kanban_done_check_also_closes_the_action(client, fake, seeded, db):
    task_id = delegate(client, seeded["action_id"]).json()["erp"]["task_id"]
    fake.tasks[task_id]["state"] = "1_done"
    assert client.post("/erp/sync").json()["completed"] == [seeded["action_id"]]


def test_sync_does_not_close_an_action_that_is_not_awaiting(client, fake, seeded, db):
    task_id = delegate(client, seeded["action_id"]).json()["erp"]["task_id"]
    client.post(f"/actions/{seeded['action_id']}/undo")  # back to pending, Odoo task remains
    fake.move_task(task_id, "Done")
    result = client.post("/erp/sync").json()
    assert result["completed"] == []
    db.expire_all()
    assert db.get(Action, seeded["action_id"]).status == "pending"


def test_sync_when_odoo_is_down_fails_loudly_and_changes_nothing(client, fake, seeded, db):
    delegate(client, seeded["action_id"])
    fake.mode = "down"
    response = client.post("/erp/sync")
    assert response.status_code == 503 and " | " in response.json()["detail"]
    db.expire_all()
    assert db.get(Action, seeded["action_id"]).status == "awaiting_confirmation"


def test_sync_reports_a_task_deleted_in_odoo_and_continues(client, fake, seeded, db):
    first = delegate(client, seeded["action_id"]).json()["erp"]["task_id"]
    second = delegate(client, seeded["second_action_id"], 2).json()["erp"]["task_id"]
    del fake.tasks[first]
    fake.move_task(second, "Waiting for Confirmation")
    result = client.post("/erp/sync").json()
    assert result["checked"] == 2
    assert [e["action_id"] for e in result["errors"]] == [seeded["action_id"]]
    assert result["errors"][0]["message_en"] and result["errors"][0]["message_ar"]
    assert result["changed"] == [seeded["second_action_id"]]


def test_erp_tasks_list_refreshes_by_default_and_can_skip(client, fake, seeded, db):
    task_id = delegate(client, seeded["action_id"]).json()["erp"]["task_id"]
    fake.move_task(task_id, "Done")
    listing = client.get("/erp/tasks").json()
    assert listing["refreshed"] is True
    assert listing["items"][0]["action_status"] == "done" and listing["items"][0]["stage_key"] == "done"

    fake.mode = "down"
    cached = client.get("/erp/tasks?refresh=false")
    assert cached.status_code == 200 and cached.json()["items"][0]["task_id"] == task_id
    assert client.get("/erp/tasks").status_code == 503


def test_no_secret_in_any_request_response_or_audit_row(client, fake, seeded, db):
    response = delegate(client, seeded["action_id"])
    audit_dump = json.dumps([p for _, p in audit_events(db, seeded["action_id"])], default=str)
    assert PASSWORD not in response.text
    assert PASSWORD not in audit_dump
    assert PASSWORD not in client.get("/erp/status").text

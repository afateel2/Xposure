"""
M7 API route tests.

Same discipline as test_agent.py/test_impact.py: a real SQLAlchemy session
against an in-memory SQLite database (via FastAPI's dependency_overrides
on get_db), not a mocked Session — these routes' interesting behavior is
their SQL (joins, grouped counts, priority recomputation), and a mock
would just agree with whatever the code did. The same routes were also
exercised by hand against the live Postgres with the real 208-change/
279-impact/452-action pipeline output (see docs/PLAN.md's M7 entry);
these tests pin that behavior on a small, fully-controlled fixture instead
of depending on that data staying exactly as it is.

policy.py's YAML load is NOT mocked: /settings/policy reads the real
backend/data/org/automation_policy.yaml, exactly as app/policy.py does at
runtime, so a test failure here means the file (or the module) actually
changed, not that a mock drifted from it.
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import require_user
from app.db.base import Base
from app.db.models import Action, AuditLog, Change, Clause, Impact, OrgNode, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.main import app

from .auth_fixtures import TEST_USER


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
    app.dependency_overrides[require_user] = lambda: TEST_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def seeded(db):
    """One regulator/regulation/two versions/one aligned clause pair, plus
    an org node + impact + two actions on it — enough to exercise every
    join and grouped count the routes do, at a size small enough to read
    the whole thing back in an assertion."""
    regulator = Regulator(code="nca", name_ar="الهيئة", name_en="National Cybersecurity Authority", weight=1.0)
    db.add(regulator)
    db.flush()
    regulation = Regulation(regulator_id=regulator.id, code="ecc", title_ar="الضوابط", title_en="Essential Cybersecurity Controls")
    db.add(regulation)
    db.flush()
    v1 = RegulationVersion(regulation_id=regulation.id, version_label="1-2018", file_sha256="aaa", source_url="")
    v2 = RegulationVersion(regulation_id=regulation.id, version_label="2-2024", file_sha256="bbb", source_url="")
    db.add_all([v1, v2])
    db.flush()

    old_clause = Clause(version_id=v1.id, clause_id="2-5-3", text_en="Old requirement text.", order_index=0)
    new_clause = Clause(version_id=v2.id, clause_id="2-5-3", text_en="New, stricter requirement text.", order_index=0)
    db.add_all([old_clause, new_clause])
    db.flush()

    change = Change(
        regulation_id=regulation.id,
        from_version_id=v1.id,
        to_version_id=v2.id,
        old_clause_id="2-5-3",
        new_clause_id="2-5-3",
        match_kind="exact_id",
        change_type="tightened",
        material=True,
        confidence=0.92,
        summary_en="The requirement became stricter.",
        summary_ar="أصبح المتطلب أكثر صرامة.",
        effective_date=date.today() + timedelta(days=10),
        grace_days=5,
        diff_spans_json={"ops": [{"op": "replace", "old": ["Old requirement text."], "new": ["New, stricter requirement text."]}]},
    )
    db.add(change)
    db.flush()

    node = OrgNode(type="policy", name="Information Security Policy", attrs_json={})
    db.add(node)
    db.flush()

    impact = Impact(
        change_id=change.id,
        node_id=node.id,
        path_json={"scope_match": "exact", "depth": 0, "summary": node.name},
        note_en="Update the policy to reflect the stricter requirement.",
        note_ar="حدّث السياسة.",
        recommended_actions_json=["update_policy", "collect_evidence"],
    )
    db.add(impact)
    db.flush()

    pending_action = Action(
        change_id=change.id, type="update_policy", level="draft_then_approve", status="pending",
        payload_json={"impact_id": impact.id},
    )
    done_action = Action(
        change_id=change.id, type="collect_evidence", level="auto_execute", status="done",
        owner_node_id=node.id, payload_json={"impact_id": impact.id},
    )
    db.add_all([pending_action, done_action])
    db.commit()

    return {
        "change_id": change.id,
        "pending_action_id": pending_action.id,
        "done_action_id": done_action.id,
        "impact_id": impact.id,
        "node_id": node.id,
    }


# ── GET /changes ────────────────────────────────────────────────────────

def test_list_changes_returns_computed_priority_and_counts(client, seeded):
    response = client.get("/changes")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["id"] == seeded["change_id"]
    assert row["change_type"] == "tightened"
    assert row["impacted_node_count"] == 1
    assert row["action_status_counts"] == {"pending": 1, "done": 1}
    # tightened, 1 impacted node, due inside 30 days -> comfortably "high" or above,
    # never "low" (mirrors priority.py's own guaranteed properties)
    assert row["priority_band"] in ("critical", "high", "medium")
    assert 0 <= row["priority_score"] <= 100


def test_list_changes_material_only_filter_excludes_non_material(client, db, seeded):
    editorial = Change(
        regulation_id=1, from_version_id=1, to_version_id=1,
        old_clause_id="9-9-9", new_clause_id="9-9-9", match_kind="exact_id",
        change_type="editorial", material=False, confidence=1.0,
        summary_en="Typo fix.", summary_ar="تصحيح إملائي.",
    )
    db.add(editorial)
    db.commit()

    materials_only = client.get("/changes?material_only=true").json()
    assert all(c["material"] is True for c in materials_only)

    everything = client.get("/changes?material_only=false").json()
    assert len(everything) == 2


def test_list_changes_band_filter(client, seeded):
    all_rows = client.get("/changes").json()
    band = all_rows[0]["priority_band"]
    filtered = client.get(f"/changes?band={band}").json()
    assert len(filtered) == 1
    other_band = "low" if band != "low" else "critical"
    assert client.get(f"/changes?band={other_band}").json() == []


# ── GET /changes/{id} ───────────────────────────────────────────────────

def test_get_change_detail_includes_diff_receipt_and_impacts(client, seeded):
    response = client.get(f"/changes/{seeded['change_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["old_text_en"] == "Old requirement text."
    assert body["new_text_en"] == "New, stricter requirement text."
    assert body["old_version_label"] == "1-2018"
    assert body["new_version_label"] == "2-2024"
    assert body["from_file_sha256"] == "aaa"
    assert body["to_file_sha256"] == "bbb"
    assert body["diff_ops"][0]["op"] == "replace"
    assert body["due_date"] is not None  # effective_date + grace_days, both set on the fixture

    assert len(body["impacts"]) == 1
    impact = body["impacts"][0]
    assert impact["node_name"] == "Information Security Policy"
    assert impact["recommended_actions"] == ["update_policy", "collect_evidence"]
    assert {a["type"] for a in impact["actions"]} == {"update_policy", "collect_evidence"}
    done = next(a for a in impact["actions"] if a["type"] == "collect_evidence")
    assert done["owner_node_name"] == "Information Security Policy"


def test_get_change_detail_404_for_unknown_id(client, seeded):
    response = client.get("/changes/999999")
    assert response.status_code == 404


def test_get_change_detail_reports_undo_availability_per_action(client, seeded):
    """Regression test for a real gap found via live verification: the
    frontend only showed an Undo control while an action was non-pending,
    so once an undo reverted an action back to 'pending' (the common
    case), there was no way to reach undo_action()'s own redo-via-undo-
    again mechanism — it existed on the backend but was unreachable from
    the UI. can_undo/is_redo let the frontend show the right control in
    every state, including a plain pending action that has real undo
    history."""

    def action_out(change_id: int) -> dict:
        body = client.get(f"/changes/{change_id}").json()
        return next(a for i in body["impacts"] for a in i["actions"] if a["id"] == seeded["pending_action_id"])

    # Virgin pending action: nothing to undo yet.
    before = action_out(seeded["change_id"])
    assert before["can_undo"] is False
    assert before["is_redo"] is False

    client.post(f"/actions/{seeded['pending_action_id']}/approve")
    after_approve = action_out(seeded["change_id"])
    assert after_approve["can_undo"] is True
    assert after_approve["is_redo"] is False  # last transition was a real approve, not an undo

    client.post(f"/actions/{seeded['pending_action_id']}/undo")
    after_undo = action_out(seeded["change_id"])
    assert after_undo["status"] == "pending"
    assert after_undo["can_undo"] is True  # reachable even though status is back to "pending"
    assert after_undo["is_redo"] is True  # clicking Undo again would redo the approve


# ── POST /actions/{id}/approve|dismiss ───────────────────────────────────

def test_approve_pending_action_succeeds_and_writes_audit_row(client, db, seeded):
    response = client.post(f"/actions/{seeded['pending_action_id']}/approve")
    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["status"]) == (seeded["pending_action_id"], "approved")
    # The seeded org node has no mapped company file, so no agent effect, and
    # the response says so instead of implying an edit happened.
    assert body["effect"] is None
    assert "no file effect" in body["effect_note"].lower()

    db.expire_all()
    action = db.get(Action, seeded["pending_action_id"])
    assert action.status == "approved"

    # Two audit rows land here: the decision itself, and the best-effort
    # webhooks.send_webhook() result (app/webhooks.py) — WEBHOOK_URL is
    # unset in this test environment, so that second row records a clean
    # no-op ("no WEBHOOK_URL configured"), not a delivery.
    from app.db.models import AuditLog
    rows = db.query(AuditLog).filter(AuditLog.ref_id == seeded["pending_action_id"]).order_by(AuditLog.id).all()
    assert len(rows) == 2
    assert rows[0].event == "action_approved"
    assert rows[0].actor == TEST_USER.actor()  # app/auth.py: the signed-in reviewer, not a fixed literal
    assert rows[0].payload_json["previous_status"] == "pending"
    assert rows[0].payload_json["via"] == "api"
    assert rows[1].event == "webhook_action_approved"
    assert rows[1].payload_json["sent"] is False


def test_dismiss_pending_action_succeeds(client, seeded):
    response = client.post(
        f"/actions/{seeded['pending_action_id']}/dismiss",
        json={"reason": "Already covered by the existing network procedure."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"
    assert response.json()["reason"] == "Already covered by the existing network procedure."


@pytest.mark.parametrize("body", [None, {}, {"reason": None}, {"reason": ""}, {"reason": "   "}, {"reason": "ab"}])
def test_dismiss_without_a_written_reason_is_refused_and_changes_nothing(client, db, seeded, body):
    action_id = seeded["pending_action_id"]
    kwargs = {} if body is None else {"json": body}
    response = client.post(f"/actions/{action_id}/dismiss", **kwargs)
    assert response.status_code == 422
    assert "reason" in response.json()["detail"].lower()

    db.expire_all()
    assert db.get(Action, action_id).status == "pending"
    # No dismissal row was written: refusing must leave the audit log untouched.
    assert db.query(AuditLog).filter(AuditLog.ref_id == action_id, AuditLog.event == "action_dismissed").count() == 0


def test_dismiss_reason_is_audited_shown_on_the_change_and_cleared_by_undo(client, db, seeded):
    action_id = seeded["pending_action_id"]
    reason = "Out of scope for the Dammam plant."
    assert client.post(f"/actions/{action_id}/dismiss", json={"reason": f"  {reason}  "}).status_code == 200

    db.expire_all()
    row = db.query(AuditLog).filter(AuditLog.ref_id == action_id, AuditLog.event == "action_dismissed").one()
    assert row.payload_json["reason"] == reason  # trimmed
    assert row.actor == TEST_USER.actor()

    def action_from_detail():
        detail = client.get(f"/changes/{seeded['change_id']}").json()
        return next(a for i in detail["impacts"] for a in i["actions"] if a["id"] == action_id)

    assert action_from_detail()["status"] == "dismissed"
    assert action_from_detail()["dismiss_reason"] == reason

    timeline = client.get(f"/changes/{seeded['change_id']}/timeline").json()["items"]
    dismissed = next(i for i in timeline if i["event"] == "action_dismissed")
    assert dismissed["detail_en"] == f"Reason: {reason}"

    # Undoing the dismissal makes the action pending again, so the old reason must not linger on screen.
    assert client.post(f"/actions/{action_id}/undo").status_code == 200
    assert action_from_detail()["status"] == "pending"
    assert action_from_detail()["dismiss_reason"] is None


def test_bulk_dismiss_requires_a_reason_but_bulk_approve_does_not(client, db, seeded):
    action_id = seeded["pending_action_id"]
    refused = client.post("/actions/bulk", json={"action_ids": [action_id], "decision": "dismiss"})
    assert refused.status_code == 422
    db.expire_all()
    assert db.get(Action, action_id).status == "pending"

    ok = client.post("/actions/bulk", json={"action_ids": [action_id], "decision": "dismiss", "reason": "Duplicate of another item."})
    assert ok.status_code == 200 and ok.json()["updated"] == [action_id]
    db.expire_all()
    assert db.get(Action, action_id).payload_json["dismiss_reason"] == "Duplicate of another item."
    summary = db.query(AuditLog).filter(AuditLog.event == "bulk_action_applied").one()
    assert summary.payload_json["reason"] == "Duplicate of another item."


# ── citation check on GET /changes/{id} ──────────────────────────────────

def _pdf_with_text(path, pages):
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 550, 800), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_change_detail_reports_citation_verified_against_the_source_file(client, db, seeded, tmp_path, monkeypatch):
    from app import citation

    pdf = tmp_path / "source.pdf"
    sha = _pdf_with_text(pdf, ["Old requirement text. Filler.", "New, stricter requirement text. More filler."])
    # Point both versions at this file; old text is on page 1, new text on page 2.
    for version in db.query(RegulationVersion).all():
        version.file_sha256 = sha
    db.query(Clause).filter(Clause.text_en == "Old requirement text.").one().page_en = 1
    db.query(Clause).filter(Clause.text_en == "New, stricter requirement text.").one().page_en = 2
    db.commit()
    monkeypatch.setattr(citation, "source_pdf_path", lambda *args: pdf)

    detail = client.get(f"/changes/{seeded['change_id']}").json()
    assert detail["citation"]["old"] == {"status": "verified", "page": 1, "cited_page": 1, "file_hash_ok": True, "reason": None}
    assert detail["citation"]["new"]["status"] == "verified" and detail["citation"]["new"]["page"] == 2


def test_change_detail_flags_text_that_is_not_in_the_source_file(client, db, seeded, tmp_path, monkeypatch):
    from app import citation

    pdf = tmp_path / "source.pdf"
    sha = _pdf_with_text(pdf, ["Completely different content about something else."])
    for version in db.query(RegulationVersion).all():
        version.file_sha256 = sha
    db.commit()
    monkeypatch.setattr(citation, "source_pdf_path", lambda *args: pdf)

    detail = client.get(f"/changes/{seeded['change_id']}").json()
    assert detail["citation"]["old"]["status"] == "not_found"
    assert detail["citation"]["new"]["status"] == "not_found"


def test_change_detail_citation_is_unavailable_not_an_error_when_the_file_is_missing(client, seeded, monkeypatch):
    from app import citation

    monkeypatch.setattr(citation, "source_pdf_path", lambda *args: None)
    response = client.get(f"/changes/{seeded['change_id']}")
    assert response.status_code == 200
    assert response.json()["citation"]["old"]["status"] == "unavailable"
    assert response.json()["citation"]["old"]["reason"] == "source file not found"


def test_approve_already_resolved_action_is_rejected(client, seeded):
    response = client.post(f"/actions/{seeded['done_action_id']}/approve")
    assert response.status_code == 409


def test_approve_unknown_action_404s(client, seeded):
    response = client.post("/actions/999999/approve")
    assert response.status_code == 404


def test_approve_then_approve_again_conflicts(client, seeded):
    first = client.post(f"/actions/{seeded['pending_action_id']}/approve")
    assert first.status_code == 200
    second = client.post(f"/actions/{seeded['pending_action_id']}/approve")
    assert second.status_code == 409


# ── POST /actions/{id}/delegate|confirm|undo, POST /actions/bulk ────────

def test_delegate_pending_action_sets_awaiting_confirmation(client, db, seeded):
    response = client.post(
        f"/actions/{seeded['pending_action_id']}/delegate",
        json={"assignee_name": "Fatima Al-Otaibi", "assignee_contact": "fatima@example.com", "message": "Please handle this."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["assignee_name"] == "Fatima Al-Otaibi"

    db.expire_all()
    action = db.get(Action, seeded["pending_action_id"])
    assert action.status == "awaiting_confirmation"
    assert action.assignee_contact == "fatima@example.com"
    assert action.delegated_at is not None

    delegated_row = db.scalar(
        select(AuditLog).where(AuditLog.event == "action_delegated", AuditLog.ref_id == action.id)
    )
    assert delegated_row.payload_json["previous_status"] == "pending"
    assert delegated_row.payload_json["assignee_name"] == "Fatima Al-Otaibi"
    # No notification channel is configured in this test environment —
    # the delegation must still succeed, honestly reporting a non-send.
    assert delegated_row.payload_json["notification"]["sent"] is False


def test_delegate_already_resolved_action_is_rejected(client, seeded):
    response = client.post(f"/actions/{seeded['done_action_id']}/delegate", json={"assignee_name": "Someone"})
    assert response.status_code == 409


def test_list_sent_notifications_reflects_a_real_delegation(client, seeded):
    empty = client.get("/notifications/sent").json()
    assert empty == []

    client.post(
        f"/actions/{seeded['pending_action_id']}/delegate",
        json={"assignee_name": "Fatima Al-Otaibi", "assignee_contact": "fatima@example.com"},
    )
    rows = client.get("/notifications/sent").json()
    assert len(rows) == 1
    assert rows[0]["action_id"] == seeded["pending_action_id"]
    assert rows[0]["assignee_name"] == "Fatima Al-Otaibi"
    # No notification channel is configured in this test environment —
    # the row must still appear, honestly reporting the non-send.
    assert rows[0]["notification"]["sent"] is False


def test_confirm_awaiting_confirmation_action_marks_done(client, db, seeded):
    client.post(f"/actions/{seeded['pending_action_id']}/delegate", json={"assignee_name": "Fatima"})
    response = client.post(f"/actions/{seeded['pending_action_id']}/confirm")
    assert response.status_code == 200
    assert response.json()["status"] == "done"

    db.expire_all()
    action = db.get(Action, seeded["pending_action_id"])
    assert action.confirmed_at is not None
    confirmed_row = db.scalar(select(AuditLog).where(AuditLog.event == "action_confirmed_done", AuditLog.ref_id == action.id))
    assert confirmed_row.payload_json["via"] == "manual_confirmation"
    assert confirmed_row.payload_json["previous_status"] == "awaiting_confirmation"


def test_confirm_a_still_pending_action_is_rejected(client, seeded):
    response = client.post(f"/actions/{seeded['pending_action_id']}/confirm")
    assert response.status_code == 409


def test_undo_after_approve_reverts_to_pending_with_no_side_effects_reported(client, db, seeded):
    client.post(f"/actions/{seeded['pending_action_id']}/approve")
    response = client.post(f"/actions/{seeded['pending_action_id']}/undo")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    # WEBHOOK_URL is unset in this test environment, so the webhook never
    # actually sent — undo must not claim it reversed a delivery that
    # never left the process.
    assert body["side_effects_not_reversed"] == []

    db.expire_all()
    assert db.get(Action, seeded["pending_action_id"]).status == "pending"


def test_undo_after_delegate_clears_the_stale_assignee(client, db, seeded):
    """Regression test for a real bug found via live Playwright
    verification: delegating then undoing left the action back at
    'pending' but still showing assignee_name/assignee_contact/
    delegated_at from the delegation that was just undone."""
    client.post(f"/actions/{seeded['pending_action_id']}/delegate", json={"assignee_name": "Fatima"})
    response = client.post(f"/actions/{seeded['pending_action_id']}/undo")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"

    db.expire_all()
    action = db.get(Action, seeded["pending_action_id"])
    assert action.status == "pending"
    assert action.assignee_name is None
    assert action.assignee_contact is None
    assert action.delegated_at is None


def test_undo_after_confirm_keeps_the_assignee_since_it_is_still_delegated(client, db, seeded):
    client.post(f"/actions/{seeded['pending_action_id']}/delegate", json={"assignee_name": "Fatima"})
    client.post(f"/actions/{seeded['pending_action_id']}/confirm")
    response = client.post(f"/actions/{seeded['pending_action_id']}/undo")
    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_confirmation"

    db.expire_all()
    action = db.get(Action, seeded["pending_action_id"])
    assert action.status == "awaiting_confirmation"
    assert action.assignee_name == "Fatima"  # still genuinely delegated, just not confirmed done yet


def test_undo_with_no_transition_history_is_rejected(client, seeded):
    response = client.post(f"/actions/{seeded['pending_action_id']}/undo")
    assert response.status_code == 409


def test_bulk_approve_partial_success_reports_stale_skip(client, db, seeded):
    second = Action(
        change_id=seeded["change_id"], type="collect_evidence", level="draft_then_approve",
        status="pending", payload_json={},
    )
    db.add(second)
    db.commit()

    response = client.post(
        "/actions/bulk",
        json={"action_ids": [seeded["pending_action_id"], second.id, seeded["done_action_id"]], "decision": "approve"},
    )
    assert response.status_code == 200
    body = response.json()
    assert sorted(body["updated"]) == sorted([seeded["pending_action_id"], second.id])
    assert body["skipped"] == [{"id": seeded["done_action_id"], "reason": "not pending (status=done)"}]

    db.expire_all()
    assert db.get(Action, seeded["pending_action_id"]).status == "approved"
    assert db.get(Action, second.id).status == "approved"


# ── GET /sources ────────────────────────────────────────────────────────

def test_list_sources_includes_both_versions_with_clause_counts(client, seeded):
    response = client.get("/sources")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    by_label = {v["version_label"]: v for v in body}
    assert by_label["1-2018"]["clause_count"] == 1
    assert by_label["2-2024"]["clause_count"] == 1
    assert by_label["1-2018"]["regulator"]["code"] == "nca"


# ── GET /settings/policy ────────────────────────────────────────────────

def test_get_policy_reflects_real_yaml_and_hard_gates(client):
    response = client.get("/settings/policy")
    assert response.status_code == 200
    body = response.json()
    assert body["default_level"] == "draft_then_approve"
    assert body["action_levels"]["collect_evidence"] == "auto_execute"
    assert body["action_levels"]["technical_change"] == "notify_only"
    assert set(body["auto_executable_change_types"]) == {"clarification", "editorial"}
    assert body["min_auto_execute_confidence"] == 0.7
    assert len(body["gates"]) == 4


# ── GET /agent/status ───────────────────────────────────────────────────

def test_agent_status_with_no_audit_history_is_all_none(client, db):
    response = client.get("/agent/status")
    assert response.status_code == 200
    assert response.json() == {
        "last_checked_at": None,
        "last_run_at": None,
        "last_run_status": None,
        "last_run_summary": None,
        "last_baseline_ingested_at": None,
        "last_baseline_ingested_label": None,
    }


def test_agent_status_reflects_the_latest_check_and_the_latest_run_of_either_kind(client, db):
    # Two "sources_checked" events -> the later one wins for last_checked_at.
    db.add(AuditLog(event="sources_checked", actor="agent", ref_type="run", ref_id=1, payload_json={"new_files": 0}))
    db.add(AuditLog(event="run_delivered", actor="agent", ref_type="run", ref_id=1, payload_json={"changes": 3}))
    db.commit()
    db.add(AuditLog(event="sources_checked", actor="agent", ref_type="run", ref_id=2, payload_json={"new_files": 1}))
    db.commit()

    first = client.get("/agent/status").json()
    assert first["last_run_status"] == "delivered"
    assert first["last_run_summary"] == {"changes": 3}
    latest_checked_at = first["last_checked_at"]

    # A later run_failed (higher id than run_delivered) should now be "the last run".
    db.add(AuditLog(event="run_failed", actor="agent", ref_type="run", ref_id=2, payload_json={"error": "llm timeout"}))
    db.commit()

    second = client.get("/agent/status").json()
    assert second["last_checked_at"] == latest_checked_at  # unchanged, no new sources_checked row
    assert second["last_run_status"] == "failed"
    assert second["last_run_summary"] == {"error": "llm timeout"}


def test_agent_status_surfaces_the_most_recent_baseline_ingest(client, db):
    db.add(AuditLog(
        event="baseline_ingested", actor="agent:ingest_new_node", ref_type="regulation_version", ref_id=1,
        payload_json={"regulator": "nca", "regulation": "ecc", "version_label": "1-2018", "note": "no prior version to diff against yet"},
    ))
    db.commit()
    db.add(AuditLog(
        event="baseline_ingested", actor="agent:ingest_new_node", ref_type="regulation_version", ref_id=2,
        payload_json={"regulator": "sama", "regulation": "crf", "version_label": "1-2025", "note": "no prior version to diff against yet"},
    ))
    db.commit()

    body = client.get("/agent/status").json()
    assert body["last_baseline_ingested_at"] is not None
    assert body["last_baseline_ingested_label"] == "SAMA / CRF 1-2025"


# ── GET /agent/eval-summary ──────────────────────────────────────────────

def test_eval_summary_is_null_when_no_eval_has_ever_run(client):
    with patch("app.routes.agent.eval_summary_mod.load_latest_eval_summary", return_value=None):
        response = client.get("/agent/eval-summary")
    assert response.status_code == 200
    assert response.json() is None


def test_eval_summary_reflects_a_real_eval_result(client):
    fake_summary = {
        "model": "google/gemma-4-31b-it", "base_url": "https://openrouter.ai/api/v1",
        "sample_size": 20, "structured_output_validity_rate": 1.0, "avg_latency_s": 3.18,
        "labeled_sample_size": 14, "accuracy_on_labeled": 1.0,
    }
    with patch("app.routes.agent.eval_summary_mod.load_latest_eval_summary", return_value=fake_summary):
        response = client.get("/agent/eval-summary")
    assert response.status_code == 200
    assert response.json() == fake_summary


# ── GET /agent/digest-status ─────────────────────────────────────────────

def test_digest_status_is_all_none_when_no_digest_has_ever_run(client):
    response = client.get("/agent/digest-status")
    assert response.status_code == 200
    assert response.json() == {"last_digest_at": None, "last_digest_status": None, "last_digest_summary": None}


def test_digest_status_reflects_the_most_recent_sent_or_skipped_run(client, db):
    db.add(AuditLog(event="digest_skipped", actor="agent:digest", payload_json={"reason": "nothing new since last digest"}))
    db.commit()
    first = client.get("/agent/digest-status").json()
    assert first["last_digest_status"] == "skipped"

    db.add(AuditLog(event="digest_sent", actor="agent:digest", payload_json={"new_critical_or_high_changes": [], "newly_overdue_actions": [{"id": 1}]}))
    db.commit()
    second = client.get("/agent/digest-status").json()
    assert second["last_digest_status"] == "sent"
    assert second["last_digest_summary"]["newly_overdue_actions"] == [{"id": 1}]

"""
Visibility layer tests: /overview, /activity, /audit, /audit/events, /tasks,
/agent/state, /changes/{id}/timeline, /changes/new-count.

Same discipline as test_routes.py: a real SQLAlchemy session on in-memory
SQLite via dependency_overrides, no mocked Session. Audit sequences are
seeded by hand with explicit timestamps so ordering, collapsing and the
demo_reset window are deterministic. Every endpoint here is read-only, and
one test proves it (audit_log and action rows are unchanged after GETs).
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Action, AuditLog, Change, Clause, Impact, OrgNode, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.main import app
from app.visibility import events as ev_mod
from app.visibility import labels as L

EM_DASH = chr(0x2014)
T0 = datetime(2026, 9, 15, 10, 0, 0)


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
def seeded(db):
    regulator = Regulator(code="nca", name_ar="الهيئة الوطنية للأمن السيبراني", name_en="National Cybersecurity Authority", weight=1.0)
    db.add(regulator)
    db.flush()
    regulation = Regulation(regulator_id=regulator.id, code="ecc", title_ar="الضوابط الأساسية", title_en="Essential Cybersecurity Controls")
    db.add(regulation)
    db.flush()
    v1 = RegulationVersion(regulation_id=regulation.id, version_label="1-2018", file_sha256="aaa", ingested_at=T0 - timedelta(days=30))
    v2 = RegulationVersion(regulation_id=regulation.id, version_label="2-2024", file_sha256="bbb", ingested_at=T0)
    db.add_all([v1, v2])
    db.flush()
    db.add_all([
        Clause(version_id=v1.id, clause_id="2-5-3", text_en="Old.", order_index=0),
        Clause(version_id=v2.id, clause_id="2-5-3", text_en="New.", order_index=0),
    ])
    change = Change(
        regulation_id=regulation.id, from_version_id=v1.id, to_version_id=v2.id, old_clause_id="2-5-3", new_clause_id="2-5-3",
        match_kind="exact_id", change_type="tightened", material=True, confidence=0.92,
        summary_en="The requirement became stricter.", summary_ar="أصبح المتطلب أكثر صرامة.",
        effective_date=date.today() + timedelta(days=10), grace_days=5, created_at=T0 + timedelta(minutes=1),
    )
    db.add(change)
    db.flush()
    node = OrgNode(type="policy", name="Information Security Policy", attrs_json={})
    db.add(node)
    db.flush()
    impact = Impact(change_id=change.id, node_id=node.id, path_json={}, recommended_actions_json=["update_policy", "collect_evidence"])
    db.add(impact)
    db.flush()
    a_pending = Action(
        change_id=change.id, type="update_policy", level="draft_then_approve", status="pending",
        payload_json={"impact_id": impact.id, "impact_node_name": node.name, "clause_id": "2-5-3"}, created_at=T0 + timedelta(minutes=2),
    )
    a_done = Action(
        change_id=change.id, type="collect_evidence", level="auto_execute", status="done", owner_node_id=node.id,
        payload_json={"impact_id": impact.id, "impact_node_name": node.name, "clause_id": "2-5-3"}, created_at=T0 + timedelta(minutes=2),
    )
    db.add_all([a_pending, a_done])
    db.commit()
    return {
        "regulation_id": regulation.id, "v1": v1.id, "v2": v2.id, "change_id": change.id, "node_id": node.id,
        "pending_id": a_pending.id, "done_id": a_done.id,
    }


def add_audit(db, event, *, ts=None, actor="agent:test", ref_type="", ref_id=None, payload=None):
    row = AuditLog(ts=ts or T0, actor=actor, event=event, ref_type=ref_type, ref_id=ref_id, payload_json=payload or {})
    db.add(row)
    db.commit()
    return row


def seed_pipeline_run(db, s, base=T0 + timedelta(minutes=5), run_id="run-A"):
    """The audit sequence one real agent run writes (agent/graph.py)."""
    t = lambda sec: base + timedelta(seconds=sec)  # noqa: E731
    add_audit(db, "sources_checked", ts=t(0), actor="agent:check_sources_node", payload={
        "run_id": run_id, "counts": {"already_ingested": 1, "new": 1},
        "files": [{"path": "nca/a.pdf", "status": "already_ingested", "version_id": s["v1"]}, {"path": "nca/b.pdf", "status": "new", "regulator": "nca", "regulation": "ecc"}],
    })
    add_audit(db, "source_ingested", ts=t(1), actor="agent:ingest_new_node", ref_type="regulation_version", ref_id=s["v2"],
              payload={"run_id": run_id, "regulator": "nca", "regulation": "ecc", "version_label": "2-2024", "version_id": s["v2"]})
    add_audit(db, "ingest_new_completed", ts=t(2), actor="agent:ingest_new_node", payload={"run_id": run_id, "ingested_count": 1})
    add_audit(db, "versions_diffed", ts=t(3), actor="agent:diff_node", ref_type="regulation_version", ref_id=s["v2"], payload={
        "run_id": run_id, "regulator": "nca", "regulation": "ecc", "from_label": "1-2018", "to_label": "2-2024",
        "from_version_id": s["v1"], "to_version_id": s["v2"], "change_count": 1, "material_count": 1})
    add_audit(db, "webhook_change_detected", ts=t(3), actor="agent:diff_node", ref_type="change", ref_id=s["change_id"],
              payload={"run_id": run_id, "sent": False, "reason": "no WEBHOOK_URL configured"})
    add_audit(db, "diff_pair_completed", ts=t(4), actor="agent:diff_node", payload={"run_id": run_id})
    add_audit(db, "diff_completed", ts=t(4), actor="agent:diff_node", payload={"run_id": run_id, "pairs_diffed": 1})
    add_audit(db, "impact_computed", ts=t(5), actor="agent:impact_node", ref_type="change", ref_id=s["change_id"],
              payload={"run_id": run_id, "change_id": s["change_id"], "clause_id": "2-5-3", "impact_count": 3, "recomputed": True})
    add_audit(db, "impact_node_completed", ts=t(6), actor="agent:impact_node", payload={"run_id": run_id, "changes_considered": 1, "impact_rows": 3})
    add_audit(db, "change_prioritized", ts=t(7), actor="agent:prioritize_node", ref_type="change", ref_id=s["change_id"],
              payload={"run_id": run_id, "score": 56, "band": "high"})
    add_audit(db, "prioritize_completed", ts=t(8), actor="agent:prioritize_node", payload={"run_id": run_id, "changes_prioritized": 1, "bands": {"high": 1}})
    for i, action_id in enumerate((s["pending_id"], s["done_id"])):
        add_audit(db, "action_created", ts=t(9 + i), actor="agent:apply_policy_node", ref_type="action", ref_id=action_id, payload={
            "run_id": run_id, "action_id": action_id, "change_id": s["change_id"],
            "type": "update_policy" if i == 0 else "collect_evidence", "level": "draft_then_approve" if i == 0 else "auto_execute"})
    add_audit(db, "apply_policy_completed", ts=t(12), actor="agent:apply_policy_node", payload={"run_id": run_id, "actions_created": 2, "by_level": {"draft_then_approve": 1, "auto_execute": 1}})
    add_audit(db, "action_auto_executed", ts=t(13), actor="agent:auto_execute_node", ref_type="action", ref_id=s["done_id"],
              payload={"run_id": run_id, "change_id": s["change_id"], "type": "collect_evidence", "previous_status": "pending", "via": "auto_execute"})
    add_audit(db, "auto_execute_completed", ts=t(14), actor="agent:auto_execute_node", payload={"run_id": run_id, "executed_count": 1})
    add_audit(db, "run_paused_for_human_review", ts=t(15), actor="agent:human_review_node", payload={"run_id": run_id, "awaiting_action_ids": [s["pending_id"]]})


# ── /activity ─────────────────────────────────────────────────────────────

def test_activity_collapses_pipeline_run_and_hides_bookkeeping(client, db, seeded):
    seed_pipeline_run(db, seeded)
    body = client.get("/activity").json()
    events = [i["event"] for i in body["items"]]
    # newest first
    assert events[0] == "run_paused_for_human_review"
    assert [i["id"] for i in body["items"]] == sorted((i["id"] for i in body["items"]), reverse=True)
    # node-completion rows and the never-sent webhook are not in the feed
    for hidden in ("ingest_new_completed", "diff_pair_completed", "diff_completed", "impact_node_completed",
                   "prioritize_completed", "apply_policy_completed", "auto_execute_completed", "webhook_change_detected"):
        assert hidden not in events
    created = next(i for i in body["items"] if i["event"] == "action_created")
    assert created["count"] == 2
    assert created["text_en"] == "2 actions created (1 for review, 1 auto-executable)"
    assert "إجراءين" in created["text_ar"]
    assert created["ref_id"] is None and created["action_id"] is None
    diffed = next(i for i in body["items"] if i["event"] == "versions_diffed")
    assert diffed["text_en"] == "Compared NCA ECC 1-2018 with 2-2024: 1 change found, 1 material"
    assert diffed["detail_en"] == "Tightened: 1"
    assert diffed["kind"] == "diff"
    scan = next(i for i in body["items"] if i["event"] == "sources_checked")
    assert scan["kind"] == "scan" and scan["text_en"].startswith("Checked 2 source documents")
    paused = body["items"][0]
    assert paused["severity"] == "warning" and paused["text_en"] == "Run paused: 1 action waiting for a human decision"


def test_activity_item_shape_and_bilingual_fields(client, db, seeded):
    seed_pipeline_run(db, seeded)
    item = client.get("/activity").json()["items"][0]
    for key in ("id", "ts", "kind", "severity", "icon", "text_en", "text_ar", "ref_type", "ref_id", "change_id", "action_id", "actor"):
        assert key in item
    assert item["ts"].endswith("Z")  # timezone-aware UTC on the wire
    assert item["kind"] in ("scan", "ingest", "diff", "classify", "impact", "action", "delegate", "confirm", "undo", "export", "system", "effect")
    assert item["severity"] in ("info", "success", "warning", "danger")


def test_activity_delegate_confirm_undo_flow(client, db, seeded):
    s = seeded
    aid = s["pending_id"]
    base = T0 + timedelta(hours=1)
    action = db.get(Action, aid)
    add_audit(db, "action_delegated", ts=base, actor="user:web", ref_type="action", ref_id=aid, payload={
        "change_id": s["change_id"], "type": "update_policy", "previous_status": "pending", "via": "api",
        "assignee_name": "Sara Al-Qahtani", "notification": {"sent": False, "reason": "no notification channel configured"}})
    add_audit(db, "webhook_action_delegated", ts=base + timedelta(seconds=1), actor="api:webhooks", ref_type="action", ref_id=aid,
              payload={"sent": False, "event": "action.delegated", "reason": "no WEBHOOK_URL configured"})
    add_audit(db, "action_confirmed_done", ts=base + timedelta(minutes=5), actor="user:web", ref_type="action", ref_id=aid, payload={
        "change_id": s["change_id"], "type": "update_policy", "previous_status": "awaiting_confirmation", "via": "manual_confirmation"})
    add_audit(db, "action_status_reverted", ts=base + timedelta(minutes=6), actor="user:web", ref_type="action", ref_id=aid, payload={
        "change_id": s["change_id"], "type": "update_policy", "previous_status": "awaiting_confirmation", "via": "undo",
        "reverted_event": "action_confirmed_done", "side_effects_not_reversed": []})
    action.status = "awaiting_confirmation"
    db.commit()

    items = client.get("/activity").json()["items"]
    assert [i["event"] for i in items] == ["action_status_reverted", "action_confirmed_done", "action_delegated"]  # webhook not sent: hidden
    delegated = items[2]
    assert delegated["kind"] == "delegate"
    assert delegated["text_en"] == "Delegated: Update policy on Information Security Policy (clause 2-5-3) to Sara Al-Qahtani"
    assert "Sara Al-Qahtani" in delegated["text_ar"]
    assert delegated["detail_en"] == "No notification was sent: no notification channel configured"
    assert delegated["action_id"] == aid and delegated["change_id"] == s["change_id"]
    assert items[1]["kind"] == "confirm" and items[1]["severity"] == "success"
    undone = items[0]
    assert undone["kind"] == "undo"
    assert undone["text_en"].startswith("Undone: the completion confirmation of Update policy")
    assert undone["detail_en"] == "Status is now: Awaiting confirmation"


def test_activity_bulk_decision_hides_per_action_rows_and_collapses_undos(client, db, seeded):
    s = seeded
    base = T0 + timedelta(hours=2)
    for i in range(3):
        add_audit(db, "action_approved", ts=base + timedelta(seconds=i), actor="user:web", ref_type="action", ref_id=s["pending_id"],
                  payload={"change_id": s["change_id"], "type": "update_policy", "previous_status": "pending", "via": "bulk"})
    add_audit(db, "bulk_action_applied", ts=base + timedelta(seconds=4), actor="user:web",
              payload={"decision": "approve", "updated": [s["pending_id"]], "skipped": [{"id": 9, "reason": "not found"}]})
    # only the bulk row for id pending_id was "updated", so exactly one per-action row is suppressed
    items = client.get("/activity").json()["items"]
    bulk = next(i for i in items if i["event"] == "bulk_action_applied")
    assert bulk["text_en"] == "Bulk approved: 1 action, 1 skipped"
    assert sum(1 for i in items if i["event"] == "action_approved") == 2


def test_activity_stage_events_scan_lifecycle(client, db, seeded):
    base = T0 + timedelta(hours=3)
    add_audit(db, "scan_requested", ts=base, actor="user:web", payload={"run_id": "demo-1"})
    add_audit(db, "stage_started", ts=base + timedelta(seconds=1), actor="agent:demo", payload={"run_id": "demo-1", "stage": "diff"})
    add_audit(db, "stage_completed", ts=base + timedelta(seconds=5), actor="agent:demo", payload={"run_id": "demo-1", "stage": "diff", "detail_en": "208 clauses compared"})
    add_audit(db, "stage_started", ts=base + timedelta(seconds=6), actor="agent:demo", payload={"run_id": "demo-1", "stage": "impact"})
    items = client.get("/activity").json()["items"]
    texts = [i["text_en"] for i in items]
    assert texts == ["Started: Tracing impact on the company", "Scan requested"]  # completed stage rows hidden by default
    assert items[0]["kind"] == "system" and items[1]["kind"] == "scan"
    full = client.get("/activity?include_stages=true").json()["items"]
    assert "Completed: Comparing versions clause by clause" in [i["text_en"] for i in full]
    add_audit(db, "scan_completed", ts=base + timedelta(seconds=30), actor="agent:demo", payload={"run_id": "demo-1", "changes_processed": 43, "actions_created": 80})
    add_audit(db, "scan_failed", ts=base + timedelta(seconds=40), actor="agent:demo", payload={"run_id": "demo-2", "error": "LLM unreachable"})
    top = client.get("/activity").json()["items"][:2]
    assert top[0]["severity"] == "danger" and top[0]["text_en"] == "Scan failed: LLM unreachable"
    assert top[1]["text_en"] == "Scan completed" and top[1]["detail_en"] == "43 changes, 80 actions"


def test_activity_effect_and_erp_events(client, db, seeded):
    s = seeded
    aid = s["pending_id"]
    base = T0 + timedelta(hours=4)
    add_audit(db, "action_effect_applied", ts=base, actor="agent:company", ref_type="action", ref_id=aid, payload={
        "change_id": s["change_id"], "path": "policies/access_control.md", "added": 4, "removed": 1, "version_before": 1, "version_after": 2})
    add_audit(db, "action_effect_reverted", ts=base + timedelta(seconds=1), actor="user:web", ref_type="action", ref_id=aid, payload={"path": "policies/access_control.md"})
    add_audit(db, "erp_task_created", ts=base + timedelta(seconds=2), actor="agent:erp", ref_type="action", ref_id=aid, payload={
        "system": "odoo", "task_id": 41, "assignee": "Omar Hassan"})
    add_audit(db, "erp_task_synced", ts=base + timedelta(seconds=3), actor="agent:erp", ref_type="action", ref_id=aid, payload={"system": "odoo", "task_id": 41, "stage": "In Progress"})
    add_audit(db, "erp_task_synced", ts=base + timedelta(seconds=4), actor="agent:erp", ref_type="action", ref_id=aid, payload={"system": "odoo", "task_id": 41, "stage": "Done"})
    items = client.get("/activity").json()["items"]
    by_event = {}
    for i in items:
        by_event.setdefault(i["event"], []).append(i)
    applied = by_event["action_effect_applied"][0]
    assert applied["kind"] == "effect" and applied["text_en"] == "Agent edited policies/access_control.md: +4 / -1 lines"
    assert applied["detail_en"] == "Version 1 to 2"
    assert by_event["action_effect_reverted"][0]["text_en"] == "Agent edit reverted: policies/access_control.md restored"
    assert by_event["erp_task_created"][0]["text_en"] == "ERP task created in Odoo: #41 for Omar Hassan"
    syncs = by_event["erp_task_synced"]
    assert {s["text_en"] for s in syncs} == {"ERP task status synced from Odoo: In Progress", "ERP task completed in Odoo"}
    assert next(s for s in syncs if "completed" in s["text_en"])["kind"] == "confirm"


def test_activity_unknown_event_degrades_gracefully(client, db, seeded):
    add_audit(db, "quantum_flux_recalibrated", ts=T0 + timedelta(hours=5), ref_type="change", ref_id=seeded["change_id"], payload={"odd": [1, 2]})
    add_audit(db, "brand_new_failed_step", ts=T0 + timedelta(hours=5, seconds=1), payload=None)
    # a known event with a malformed payload must not take the feed down either
    add_audit(db, "run_paused_for_human_review", ts=T0 + timedelta(hours=5, seconds=2), payload={"awaiting_action_ids": "not-a-list"})
    add_audit(db, "versions_diffed", ts=T0 + timedelta(hours=5, seconds=3), payload={"change_count": "many", "from_version_id": "x"})
    resp = client.get("/activity")
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_event = {i["event"]: i for i in items}
    unk = by_event["quantum_flux_recalibrated"]
    assert unk["text_en"] == f"Event recorded: Quantum flux recalibrated (change #{seeded['change_id']})"
    assert unk["severity"] == "info" and unk["kind"] == "system" and unk["icon"]
    assert unk["text_ar"].startswith("حدث مسجّل")
    assert by_event["brand_new_failed_step"]["severity"] == "danger"
    assert by_event["run_paused_for_human_review"]["text_en"]  # degraded, still readable
    assert by_event["versions_diffed"]["text_en"]


def test_activity_demo_reset_windowing(client, db, seeded):
    seed_pipeline_run(db, seeded, base=T0)
    reset = add_audit(db, "demo_reset", ts=T0 + timedelta(hours=1), actor="user:web", payload={})
    add_audit(db, "scan_requested", ts=T0 + timedelta(hours=1, minutes=1), actor="user:web", payload={"run_id": "new"})

    windowed = client.get("/activity").json()
    assert windowed["window"]["since_reset"] is True
    assert windowed["window"]["reset_at"].startswith("2026-09-15T11:00:00")
    assert [i["event"] for i in windowed["items"]] == ["scan_requested", "demo_reset"]
    assert windowed["items"][1]["text_en"] == "Demo data was reset to the baseline state"

    everything = client.get("/activity?since_reset=false").json()
    assert everything["window"]["since_reset"] is False
    assert any(i["event"] == "versions_diffed" for i in everything["items"])
    assert reset.id in {i["id"] for i in everything["items"]}


def test_activity_pagination_cursor_and_kind_filter(client, db, seeded):
    for i in range(7):
        add_audit(db, "sources_checked", ts=T0 + timedelta(minutes=i), payload={"counts": {"already_ingested": 1}, "files": []})
    page1 = client.get("/activity?limit=3").json()
    assert len(page1["items"]) == 3 and page1["next_before_id"] is not None
    page2 = client.get(f"/activity?limit=3&before_id={page1['next_before_id']}").json()
    assert len(page2["items"]) == 3
    assert max(i["id"] for i in page2["items"]) < min(i["id"] for i in page1["items"])
    page3 = client.get(f"/activity?limit=3&before_id={page2['next_before_id']}").json()
    assert len(page3["items"]) == 1 and page3["next_before_id"] is None
    assert client.get("/activity?kind=action").json()["items"] == []
    assert len(client.get("/activity?kind=scan&limit=50").json()["items"]) == 7


# ── /audit ────────────────────────────────────────────────────────────────

def test_audit_pagination_total_and_filters(client, db, seeded):
    seed_pipeline_run(db, seeded)
    total = db.scalar(select(func.count()).select_from(AuditLog))
    body = client.get("/audit?limit=5&offset=0").json()
    assert body["total"] == total and len(body["items"]) == 5 and body["limit"] == 5 and body["offset"] == 0
    ids = [i["id"] for i in body["items"]]
    assert ids == sorted(ids, reverse=True)
    second = client.get("/audit?limit=5&offset=5").json()
    assert not set(ids) & {i["id"] for i in second["items"]}
    last = client.get(f"/audit?limit=5&offset={total - 2}").json()
    assert len(last["items"]) == 2

    only = client.get("/audit?event=action_created").json()
    assert only["total"] == 2 and all(i["event"] == "action_created" for i in only["items"])
    two = client.get("/audit?event=action_created,run_paused_for_human_review").json()
    assert two["total"] == 3
    assert client.get("/audit?actor=agent:diff_node").json()["total"] == 4
    assert client.get("/audit?ref_type=action&ref_id=%d" % seeded["pending_id"]).json()["total"] == 1
    since = (T0 + timedelta(minutes=5, seconds=10)).isoformat() + "Z"
    assert client.get("/audit", params={"since": since}).json()["total"] == 5
    no_payload = client.get("/audit?limit=1&include_payload=false").json()["items"][0]
    assert no_payload["payload"] is None
    row = client.get("/audit?event=versions_diffed").json()["items"][0]
    assert row["payload"]["change_count"] == 1
    assert row["summary_en"].startswith("Compared NCA ECC") and row["summary_ar"]
    assert row["ts"].endswith("Z")


def test_audit_rejects_bad_since_and_lists_events_and_actors(client, db, seeded):
    seed_pipeline_run(db, seeded)
    assert client.get("/audit?since=yesterday-ish").status_code == 422
    add_audit(db, "webhook_received:change.detected", actor="api:webhook_receiver", payload={"_verified": False})
    events = client.get("/audit/events").json()["events"]
    names = [e["event"] for e in events]
    assert names == sorted(names) and len(names) == len(set(names))
    created = next(e for e in events if e["event"] == "action_created")
    assert created["count"] == 2 and created["kind"] == "action" and created["label_en"] == "Action created" and created["label_ar"]
    assert "webhook_received:change.detected" in names
    actors = client.get("/audit/actors").json()["actors"]
    assert {"actor": "agent:diff_node", "count": 4} in actors


def test_audit_since_reset_flag(client, db, seeded):
    seed_pipeline_run(db, seeded, base=T0)
    add_audit(db, "demo_reset", ts=T0 + timedelta(hours=1))
    add_audit(db, "scan_requested", ts=T0 + timedelta(hours=2))
    assert client.get("/audit").json()["total"] == db.scalar(select(func.count()).select_from(AuditLog))  # full history by default
    assert client.get("/audit?since_reset=true").json()["total"] == 2


# ── /agent/state ──────────────────────────────────────────────────────────

def test_agent_state_idle_with_no_history(client):
    body = client.get("/agent/state").json()
    assert body["state"] == "idle" and body["awaiting_count"] == 0 and body["last_scan_at"] is None
    assert body["last_run_status"] is None and body["since"] is None
    assert body["message_en"] and body["message_ar"]


def test_agent_state_scanning_stage_then_awaiting_review(client, db, seeded):
    now = datetime.utcnow()
    add_audit(db, "scan_requested", ts=now - timedelta(seconds=20), payload={"run_id": "r1"})
    add_audit(db, "stage_started", ts=now - timedelta(seconds=10), payload={"run_id": "r1", "stage": "diff"})
    body = client.get("/agent/state").json()
    assert body["state"] == "scanning"
    assert body["stage"]["key"] == "diff" and body["stage"]["label_en"] == "Comparing versions clause by clause"
    assert body["message_en"] == "Scanning now: Comparing versions clause by clause."
    assert body["run_id"] == "r1" and body["stalled"] is False
    add_audit(db, "stage_completed", ts=now - timedelta(seconds=5), payload={"run_id": "r1", "stage": "diff"})
    assert client.get("/agent/state").json()["stage"] is None
    add_audit(db, "run_paused_for_human_review", ts=now - timedelta(seconds=2), payload={"run_id": "r1", "awaiting_action_ids": [seeded["pending_id"]]})
    done = client.get("/agent/state").json()
    assert done["state"] == "awaiting_review" and done["awaiting_count"] == 1 and done["awaiting_changes"] == 1
    assert done["last_run_status"] == "awaiting_review" and done["last_scan_at"] is None
    assert "1 action is waiting" in done["message_en"]


def test_agent_state_failed_and_stalled_and_reset(client, db, seeded):
    now = datetime.utcnow()
    add_audit(db, "scan_requested", ts=now - timedelta(hours=3), payload={"run_id": "old"})
    add_audit(db, "stage_started", ts=now - timedelta(hours=3), payload={"run_id": "old", "stage": "diff"})
    stalled = client.get("/agent/state").json()
    assert stalled["state"] == "failed" and stalled["stalled"] is True
    assert "stopped without finishing" in stalled["message_en"]
    add_audit(db, "run_failed", ts=now - timedelta(minutes=1), actor="agent:runner", payload={"run_id": "old", "error": "SystemExit: source directory not found"})
    failed = client.get("/agent/state").json()
    assert failed["state"] == "failed" and failed["stalled"] is False and failed["last_run_status"] == "failed"
    assert failed["last_run_summary"]["error"] == "SystemExit: source directory not found"
    assert "source directory not found" in failed["message_en"]
    # a reset returns the agent to a clean state, and older history no longer counts
    db.get(Action, seeded["pending_id"]).status = "dismissed"
    db.commit()
    add_audit(db, "demo_reset", ts=now, payload={})
    after = client.get("/agent/state").json()
    assert after["state"] == "idle" and after["last_run_status"] is None and after["last_scan_at"] is None


def test_agent_state_scan_failed_reads_reason_key(client, db, seeded):
    """The demo runner writes the failure text under `reason`, not `error`."""
    now = datetime.utcnow()
    add_audit(db, "scan_requested", ts=now - timedelta(minutes=2), payload={"run_id": "r9"})
    add_audit(db, "scan_failed", ts=now - timedelta(minutes=1), actor="agent:demo_runner", payload={
        "run_id": "r9", "stage": "classify", "reason": "Interrupted: the process ended", "error_type": "Interrupted"})
    body = client.get("/agent/state").json()
    assert body["state"] == "failed" and body["last_run_summary"]["error"] == "Interrupted: the process ended"
    assert body["last_run_summary"]["stage"] == "classify"
    assert body["message_en"] == "The last run failed: Interrupted: the process ended"
    top = client.get("/activity").json()["items"][0]
    assert top["text_en"] == "Scan failed: Interrupted: the process ended"


def test_agent_state_completed_run_is_idle_with_summary(client, db, seeded):
    db.get(Action, seeded["pending_id"]).status = "approved"
    db.commit()
    now = datetime.utcnow()
    add_audit(db, "sources_checked", ts=now - timedelta(minutes=5), payload={"run_id": "r2", "counts": {}, "files": []})
    add_audit(db, "run_delivered", ts=now - timedelta(minutes=4), payload={"run_id": "r2", "changes_processed": 43, "actions_created": 90})
    body = client.get("/agent/state").json()
    assert body["state"] == "idle" and body["last_run_status"] == "completed" and body["last_run_summary"]["actions_created"] == 90
    assert body["last_scan_at"] is not None


# ── /overview ─────────────────────────────────────────────────────────────

def test_overview_structure_counts_and_planned_sources(client, db, seeded):
    seed_pipeline_run(db, seeded, base=datetime(2026, 1, 1))  # long ago: the source reads as stale
    body = client.get("/overview").json()
    mon = body["monitoring"]
    assert mon["sources_total"] == 1 and mon["sources_ok"] == 0 and mon["sources_planned"] == 4  # stale: scan is from 2026-09-15
    assert mon["last_scan_at"] is not None and mon["last_release_detected_at"] is not None
    assert mon["mean_hours_publish_to_alert"] is None and mon["mean_hours_sample_size"] == 0  # no published_at recorded: never invented
    assert body["review_queue"]["total"] == 1 and body["review_queue"]["urgent"] == 1 and body["review_queue"]["critical"] == 0
    assert body["review_queue"]["pending_actions"] == 1 and body["review_queue"]["awaiting_confirmation"] == 0
    matrix = body["priority_matrix"]
    assert (matrix["critical"], matrix["quick"], matrix["strategic"], matrix["followup"]) == (0, 1, 0, 0)
    assert [m["band"] for m in matrix["mapping"]] == ["critical", "high", "medium", "low"]
    assert [m["matrix_key"] for m in matrix["mapping"]] == ["critical", "quick", "strategic", "followup"]
    assert body["remediation"] == {"total_actions": 2, "resolved_actions": 1, "percent": 50.0,
                                   "by_status": {"pending": 1, "awaiting_confirmation": 0, "approved": 0, "done": 1, "dismissed": 0}}
    assert body["tasks"]["open"] == 0

    nca = body["sources"][0]
    assert nca["code"] == "nca/ecc" and nca["latest_version"] == "2-2024" and nca["open_changes"] == 1 and nca["changes_total"] == 1
    assert nca["planned"] is False and nca["status"] == "stale" and nca["status_reason"] == "not_checked_recently"
    assert nca["status_label_en"] and nca["status_label_ar"]
    assert nca["last_change_at"].startswith("2026-09-15T10:01:00")
    planned = [s for s in body["sources"] if s["planned"]]
    assert {s["code"] for s in planned} == {"saso", "sfda", "ncec", "gami"}
    for s in planned:
        assert s["status"] == "planned" and s["last_checked_at"] is None and s["last_change_at"] is None and s["latest_version"] is None
        assert s["status_label_en"] == "Planned"


def test_overview_ok_source_and_task_counters(client, db, seeded):
    s = seeded
    now = datetime.utcnow()
    add_audit(db, "sources_checked", ts=now - timedelta(minutes=10), payload={"run_id": "r", "counts": {"already_ingested": 2}, "files": [
        {"path": "x.pdf", "status": "already_ingested", "version_id": s["v2"]}]})
    for delta in (-3, 2, 30):  # overdue, due soon, far
        db.add(Action(change_id=s["change_id"], type="notify_owner", level="draft_then_approve", status="awaiting_confirmation",
                      due_date=date.today() + timedelta(days=delta), assignee_name="Sara", payload_json={}))
    db.add(Action(change_id=s["change_id"], type="notify_owner", level="draft_then_approve", status="pending",
                  due_date=date.today() - timedelta(days=1), payload_json={}))
    db.commit()
    body = client.get("/overview").json()
    assert body["tasks"]["open"] == 3 and body["tasks"]["overdue"] == 1 and body["tasks"]["due_within_5_days"] == 1
    assert body["review_queue"]["awaiting_confirmation"] == 3
    src = body["sources"][0]
    assert src["last_checked_at"] is not None
    # pending overdue action on this regulation flags attention
    assert src["status"] == "attention" and src["status_reason"] == "overdue_actions"
    assert body["monitoring"]["sources_ok"] == 0


def test_overview_source_ok_when_recently_checked_and_nothing_overdue(client, db, seeded):
    add_audit(db, "sources_checked", ts=datetime.utcnow() - timedelta(minutes=10), payload={"counts": {"already_ingested": 2}, "files": []})
    body = client.get("/overview").json()
    assert body["sources"][0]["status"] == "ok" and body["monitoring"]["sources_ok"] == 1
    assert body["sources"][0]["status_label_en"] == "In sync"


def test_overview_conflict_file_marks_attention(client, db, seeded):
    add_audit(db, "sources_checked", ts=datetime.utcnow(), payload={"counts": {"conflict": 1}, "files": [
        {"path": "x.pdf", "status": "conflict", "regulator": "nca", "regulation": "ecc"}]})
    body = client.get("/overview").json()
    assert body["sources"][0]["status"] == "attention" and body["sources"][0]["status_reason"] == "conflict"
    assert body["monitoring"]["file_issues"]["conflict"] == 1


def test_overview_demo_reset_window(client, db, seeded):
    seed_pipeline_run(db, seeded, base=T0)
    full = client.get("/overview").json()
    assert full["monitoring"]["last_scan_at"] is not None and full["window"]["since_reset"] is False
    add_audit(db, "demo_reset", ts=T0 + timedelta(hours=1))
    windowed = client.get("/overview").json()
    assert windowed["window"]["since_reset"] is True and windowed["window"]["reset_at"] is not None
    assert windowed["monitoring"]["last_scan_at"] is None and windowed["monitoring"]["last_release_detected_at"] is None
    src = windowed["sources"][0]
    assert src["last_checked_at"] is None and src["last_change_at"] is None and src["status"] == "stale" and src["status_reason"] == "never_checked"
    assert src["changes_total"] == 1  # the window only moves timestamps, counts are live table state
    unwindowed = client.get("/overview?since_reset=false").json()
    assert unwindowed["monitoring"]["last_scan_at"] is not None and unwindowed["window"]["since_reset"] is False


def test_overview_mean_hours_only_when_publication_date_known(client, db, seeded):
    v2 = db.get(RegulationVersion, seeded["v2"])
    v2.published_at = T0 - timedelta(hours=10)
    db.commit()  # first action was created at T0+2min, so 10h + 2min
    body = client.get("/overview").json()
    assert body["monitoring"]["mean_hours_sample_size"] == 1
    assert body["monitoring"]["mean_hours_publish_to_alert"] == 10.0


def test_overview_empty_database(client):
    body = client.get("/overview").json()
    assert body["monitoring"]["sources_total"] == 0 and body["monitoring"]["sources_planned"] == 4
    assert body["remediation"]["percent"] is None and body["review_queue"]["total"] == 0


# ── /tasks ────────────────────────────────────────────────────────────────

def test_tasks_shape_sorting_filters_and_summary(client, db, seeded):
    s = seeded
    today = date.today()
    overdue = Action(change_id=s["change_id"], type="notify_owner", level="draft_then_approve", status="awaiting_confirmation",
                     due_date=today - timedelta(days=2), assignee_name="Sara", assignee_contact="sara@example.com", owner_node_id=s["node_id"],
                     delegated_at=T0, payload_json={"erp": {"system": "odoo", "task_id": 7, "url": "http://odoo/7", "stage": "In Progress", "assignee": "Sara", "synced_at": "2026-09-19T10:00:00Z", "internal": "x"}})
    soon = Action(change_id=s["change_id"], type="reassess_control", level="draft_then_approve", status="pending", due_date=today + timedelta(days=3), payload_json={})
    edited = Action(change_id=s["change_id"], type="update_policy", level="draft_then_approve", status="approved", due_date=None,
                    payload_json={"effect": {"kind": "file_edit", "path": "policies/isp.md", "version_before": 1, "version_after": 2, "added": 3, "removed": 1, "diff_unified": "@@ -1 +1 @@"}})
    db.add_all([overdue, soon, edited])
    db.commit()

    body = client.get("/tasks").json()
    assert body["total"] == 5
    ids = [t["id"] for t in body["items"]]
    assert ids[0] == overdue.id  # overdue first
    assert ids.index(soon.id) < ids.index(edited.id) or edited.due_date is None
    first = body["items"][0]
    assert first["is_overdue"] is True and first["days_left"] == -2
    assert first["assignee_name"] == "Sara" and first["assignee_contact"] == "sara@example.com"
    assert first["owner_node_name"] == "Information Security Policy"
    assert first["erp"] == {"system": "odoo", "task_id": 7, "url": "http://odoo/7", "stage": "In Progress", "assignee": "Sara", "synced_at": "2026-09-19T10:00:00Z"}
    assert first["action_type_label_en"] == "Notify owner" and first["action_type_label_ar"] == "إشعار المالك"
    assert first["change_title_en"] == "The requirement became stricter." and first["change_title_ar"]
    assert first["clause_ref"] == "2-5-3" and first["priority_band"] == "high" and first["priority_key"] == "quick"
    assert first["due_date"] == (today - timedelta(days=2)).isoformat()
    assert first["delegated_at"].endswith("Z") and first["last_event_at"] is not None

    eff = next(t for t in body["items"] if t["id"] == edited.id)
    assert eff["effect"]["path"] == "policies/isp.md" and "diff_unified" not in eff["effect"] and eff["effect"]["has_diff"] is True
    with_diff = client.get("/tasks?include_effect_diff=true").json()
    assert next(t for t in with_diff["items"] if t["id"] == edited.id)["effect"]["diff_unified"] == "@@ -1 +1 @@"

    summ = body["summary"]
    assert summ["total"] == 5 and summ["open"] == 1 and summ["overdue"] == 1 and summ["assigned"] == 1
    assert summ["by_status"] == {"pending": 2, "awaiting_confirmation": 1, "approved": 1, "done": 1, "dismissed": 0}
    assert summ["pending_review"] == 2

    assert [t["id"] for t in client.get("/tasks?status=open").json()["items"]] == [overdue.id]
    assert client.get("/tasks?status=unresolved").json()["total"] == 3
    assert client.get("/tasks?status=done,approved").json()["total"] == 2
    assert client.get("/tasks?assigned=true").json()["total"] == 1
    assert client.get("/tasks?assigned=false").json()["total"] == 4
    assert client.get(f"/tasks?change_id={s['change_id']}&limit=2&offset=4").json()["items"].__len__() == 1
    assert client.get("/tasks?status=bogus").status_code == 422
    # summary ignores filters
    assert client.get("/tasks?status=done").json()["summary"]["total"] == 5


# ── /changes/{id}/timeline and /changes/new-count ─────────────────────────

def test_timeline_orders_a_full_history(client, db, seeded):
    s = seeded
    seed_pipeline_run(db, s)
    aid = s["pending_id"]
    base = T0 + timedelta(hours=1)
    add_audit(db, "action_delegated", ts=base, actor="user:web", ref_type="action", ref_id=aid, payload={
        "change_id": s["change_id"], "type": "update_policy", "previous_status": "pending", "via": "api", "assignee_name": "Sara"})
    add_audit(db, "erp_task_created", ts=base + timedelta(seconds=1), actor="agent:erp", ref_type="action", ref_id=aid, payload={"system": "odoo", "task_id": 9})
    add_audit(db, "action_status_reverted", ts=base + timedelta(minutes=1), actor="user:web", ref_type="action", ref_id=aid, payload={
        "change_id": s["change_id"], "type": "update_policy", "previous_status": "awaiting_confirmation", "via": "undo", "reverted_event": "action_delegated"})
    body = client.get(f"/changes/{s['change_id']}/timeline").json()
    assert body["change_id"] == s["change_id"] and body["clause_ref"] == "2-5-3" and body["change_title_en"]
    items = body["items"]
    stamps = [i["ts"] for i in items]
    assert stamps == sorted(stamps)
    events = [i["event"] for i in items]
    assert events[:2] == ["change_detected", "change_classified"]
    assert items[0]["text_en"] == "Clause 2-5-3 differs between NCA ECC 1-2018 and 2-2024"
    assert items[1]["text_en"] == "Classified as Tightened with 92% confidence"
    impact = next(i for i in items if i["event"] == "impact_computed")
    assert impact["text_en"] == "Impact traced for clause 2-5-3: 3 nodes affected"
    prio = next(i for i in items if i["event"] == "change_prioritized")
    assert prio["text_en"] == "Priority computed: 56/100 (High)" and prio["severity"] == "warning"
    created = [i for i in items if i["event"] == "action_created"]
    assert len(created) == 2 and {c["action_id"] for c in created} == {aid, s["done_id"]}
    assert all(c["status_after"] == "pending" for c in created)
    assert "erp_task_created" in events and "action_delegated" in events and "action_status_reverted" in events
    assert "run_paused_for_human_review" not in events  # run-level rows are not about this change
    assert "webhook_change_detected" not in events  # never left the process
    delegated = next(i for i in items if i["event"] == "action_delegated")
    assert delegated["status_after"] == "awaiting_confirmation" and delegated["actor"] == "user:web" and delegated["audit_id"] is not None
    reverted = next(i for i in items if i["event"] == "action_status_reverted")
    assert reverted["status_after"] == "pending"
    assert client.get("/changes/99999/timeline").status_code == 404


def test_timeline_includes_actions_without_audit_rows(client, db, seeded):
    body = client.get(f"/changes/{seeded['change_id']}/timeline").json()
    created = [i for i in body["items"] if i["event"] == "action_created"]
    assert len(created) == 2 and all(c["audit_id"] is None and c["status_after"] == "pending" for c in created)


def test_new_count_route_not_shadowed_and_counts_by_band(client, db, seeded):
    s = seeded
    db.add(Change(regulation_id=s["regulation_id"], from_version_id=s["v1"], to_version_id=s["v2"], old_clause_id="9-9", new_clause_id="9-9",
                  match_kind="exact_id", change_type="editorial", material=False, confidence=1.0, summary_en="Typo.", summary_ar="خطأ إملائي.",
                  created_at=T0 + timedelta(hours=2)))
    db.add(Change(regulation_id=s["regulation_id"], from_version_id=s["v1"], to_version_id=s["v2"], old_clause_id="8-8", new_clause_id="8-8",
                  match_kind="new", change_type="new_obligation", material=True, confidence=0.9, summary_en="New duty.", summary_ar="التزام جديد.",
                  created_at=T0 + timedelta(hours=2)))
    db.commit()
    resp = client.get("/changes/new-count", params={"since": (T0 + timedelta(hours=1)).isoformat() + "Z"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1  # material only by default: the editorial one is excluded
    assert body["by_band"]["critical"] + body["by_band"]["high"] + body["by_band"]["medium"] + body["by_band"]["low"] == 1
    assert sum(body["by_matrix"].values()) == 1 and body["latest_created_at"].startswith("2026-09-15T12:00:00")
    all_kinds = client.get("/changes/new-count", params={"since": (T0 + timedelta(hours=1)).isoformat() + "Z", "material_only": "false"}).json()
    assert all_kinds["total"] == 2
    none = client.get("/changes/new-count", params={"since": "2027-01-01T00:00:00Z"}).json()
    assert none["total"] == 0 and none["latest_created_at"] is None and none["by_band"] == {"critical": 0, "high": 0, "medium": 0, "low": 0}
    assert client.get("/changes/new-count", params={"since": "2026-09-15T11:00:00+00:00"}).status_code == 200
    assert client.get("/changes/new-count?since=not-a-date").status_code == 422
    assert client.get("/changes/new-count").status_code == 422
    # and the existing route still works for real ids
    assert client.get(f"/changes/{s['change_id']}").status_code == 200


# ── cross-cutting guarantees ──────────────────────────────────────────────

def test_visibility_endpoints_are_read_only(client, db, seeded):
    seed_pipeline_run(db, seeded)
    audit_before = db.scalar(select(func.count()).select_from(AuditLog))
    actions_before = sorted((a.id, a.status) for a in db.scalars(select(Action)))
    for path in ("/overview", "/activity", "/audit", "/audit/events", "/audit/actors", "/tasks", "/agent/state",
                 f"/changes/{seeded['change_id']}/timeline", "/changes/new-count?since=2020-01-01T00:00:00Z"):
        assert client.get(path).status_code == 200, path
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(AuditLog)) == audit_before
    assert sorted((a.id, a.status) for a in db.scalars(select(Action))) == actions_before


SAMPLE_PAYLOADS = {
    "sources_checked": {"counts": {"conflict": 1, "unrecognized": 1, "new": 1}, "files": []},
    "source_ingested": {"regulator": "nca", "regulation": "ecc", "version_label": "2-2024"},
    "baseline_ingested": {"regulator": "nca", "regulation": "ecc", "version_label": "1-2018"},
    "action_created": {"type": "notify_owner", "level": "notify_only", "impact_node_name": f"ECC 1-3-1 {EM_DASH} Policies"},
    "action_delegated": {"assignee_name": "Sara", "erp": {"task_id": 3}, "notification": {"sent": True, "channel": "email"}},
    "action_status_reverted": {"reverted_event": "action_approved", "side_effects_not_reversed": ["webhook: action.approved"]},
    "digest_sent": {"new_critical_or_high_changes": [1], "newly_overdue_actions": [], "notify_result": {"sent": False, "reason": "no SMTP host configured"}},
    "webhook_action_approved": {"sent": True, "event": "action.approved"},
    "webhook_received:action.approved": {"_verified": True},
    "run_failed": {"error": "ValueError: boom"},
    "resume_failed": {"error": "SystemExit: nope"},
}


def test_every_catalogued_event_produces_clean_bilingual_text():
    """No handler may emit the long dash character, an empty string or an
    unfilled placeholder, whatever the payload looks like."""
    names = set(ev_mod.HANDLERS) | set(ev_mod.EVENT_LABELS) | set(SAMPLE_PAYLOADS) | {"totally_unknown", "webhook_received:x"}
    for name in sorted(names):
        for payload in (SAMPLE_PAYLOADS.get(name, {}), {}):
            ev = ev_mod.Ev(1, T0, "agent:x", name, "action", 5, payload)
            d = ev_mod.describe(ev, ev_mod.Ctx())
            for text in (d.en, d.ar, d.detail_en or "", d.detail_ar or ""):
                assert EM_DASH not in text and chr(0x2013) not in text, (name, text)
                assert "None" not in text and "{" not in text, (name, text)
            assert d.en.strip() and d.ar.strip(), name
            assert d.severity in ("info", "success", "warning", "danger") and d.icon and d.kind in ev_mod.KIND_ICON, name


def test_arabic_counting_forms():
    assert L.ar_count(1, L.ACTION) == "إجراء واحد"
    assert L.ar_count(2, L.ACTION) == "إجراءين"
    assert L.ar_count(5, L.ACTION) == "5 إجراءات"
    assert L.ar_count(43, L.ACTION) == "43 إجراءً"
    assert L.clean(f"a {EM_DASH} b") == "a - b"


def test_no_long_dash_in_visibility_source_files():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    files = list((root / "visibility").glob("*.py")) + [root / "routes" / n for n in ("overview.py", "activity.py", "tasks.py")]
    for f in files:
        assert EM_DASH not in f.read_text(encoding="utf-8"), f

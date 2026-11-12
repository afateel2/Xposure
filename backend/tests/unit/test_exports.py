"""
Unit tests for app/exports/{excel,oscal,pdf}.py (M8).

Same in-memory-SQLite-via-dependency_overrides discipline as
tests/unit/test_routes.py, with an equivalent `seeded` fixture (control
mapping impacted node, owner + evidence edges, two actions) so exports
that traverse the org graph (excel.py's owner/evidence_ref lookup) have
something real to find. The PDF test actually calls Playwright end to end
(not mocked) — it renders in ~1-2s locally and this is exactly the kind
of thing this project's own testing discipline says to run for real
rather than assume works (see docs/PLAN.md's repeated "verified against
real data, not just written").
"""

from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Action, Change, Clause, Impact, OrgEdge, OrgNode, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.exports.excel import build_assessment_workbook
from app.exports.oscal import build_oscal_export
from app.exports.pdf import build_change_report_html, render_change_pdf
from app.main import app


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


@pytest.fixture
def seeded(db):
    regulator = Regulator(code="nca", name_ar="الهيئة", name_en="National Cybersecurity Authority", weight=1.0)
    db.add(regulator)
    db.flush()
    regulation = Regulation(regulator_id=regulator.id, code="ecc", title_ar="الضوابط", title_en="Essential Cybersecurity Controls")
    db.add(regulation)
    db.flush()
    v1 = RegulationVersion(regulation_id=regulation.id, version_label="1-2018", file_sha256="aaa111", source_url="")
    v2 = RegulationVersion(regulation_id=regulation.id, version_label="2-2024", file_sha256="bbb222", source_url="")
    db.add_all([v1, v2])
    db.flush()

    old_clause = Clause(version_id=v1.id, clause_id="2-5-3", text_en="Old requirement text.", page_en=10, order_index=0)
    new_clause = Clause(version_id=v2.id, clause_id="2-5-3", text_en="New, stricter requirement text.", page_en=12, order_index=0)
    db.add_all([old_clause, new_clause])
    db.flush()

    change = Change(
        regulation_id=regulation.id, from_version_id=v1.id, to_version_id=v2.id,
        old_clause_id="2-5-3", new_clause_id="2-5-3", match_kind="exact_id",
        change_type="tightened", material=True, confidence=0.92,
        summary_en="The requirement became stricter.", summary_ar="أصبح المتطلب أكثر صرامة.",
        effective_date=date.today() + timedelta(days=10), grace_days=5,
        diff_spans_json={"ops": [{"op": "replace", "old": ["Old requirement text."], "new": ["New, stricter requirement text."]}]},
    )
    db.add(change)
    db.flush()

    control_node = OrgNode(type="control_mapping", name="ECC 2-5-3", attrs_json={"control_id": "2-5-3"})
    owner_node = OrgNode(type="owner", name="OT Engineering", attrs_json={})
    evidence_node = OrgNode(type="evidence", name="Network Segmentation Design", attrs_json={"ref": "EV-NET-004"})
    db.add_all([control_node, owner_node, evidence_node])
    db.flush()

    db.add_all([
        OrgEdge(from_id=control_node.id, to_id=owner_node.id, relation="owned_by"),
        OrgEdge(from_id=control_node.id, to_id=evidence_node.id, relation="evidenced_by"),
    ])
    db.flush()

    impact = Impact(
        change_id=change.id, node_id=control_node.id,
        path_json={"scope_match": "exact", "depth": 0, "summary": control_node.name},
        note_en="Reassess this control against the stricter requirement.",
        note_ar="أعد تقييم هذا الضابط.",
        recommended_actions_json=["reassess_control", "collect_evidence"],
    )
    db.add(impact)
    db.flush()

    db.add_all([
        Action(change_id=change.id, type="reassess_control", level="draft_then_approve", status="pending", payload_json={"impact_id": impact.id}),
        Action(change_id=change.id, type="collect_evidence", level="auto_execute", status="done", payload_json={"impact_id": impact.id}),
    ])
    db.commit()

    return {"change_id": change.id, "control_node_id": control_node.id}


# ── Excel ──────────────────────────────────────────────────────────────

def test_excel_export_includes_owner_and_evidence_from_the_org_graph(db, seeded):
    change = db.get(Change, seeded["change_id"])
    workbook_bytes = build_assessment_workbook(db, change)
    workbook = load_workbook(BytesIO(workbook_bytes))
    rows = list(workbook.active.iter_rows(values_only=True))
    assert rows[0] == ("control_id", "status", "owner", "evidence_ref", "note")
    assert len(rows) == 2
    control_id, status, owner, evidence_ref, note = rows[1]
    assert control_id == "2-5-3"
    assert owner == "OT Engineering"
    assert evidence_ref == "EV-NET-004"
    assert "reassess" in status.lower()


def test_excel_export_is_header_only_when_no_control_mapping_impacted(db):
    change = Change(
        regulation_id=1, from_version_id=1, to_version_id=1,
        old_clause_id="9-9", new_clause_id="9-9", match_kind="exact_id",
        change_type="editorial", material=False, confidence=1.0,
        summary_en="x", summary_ar="x",
    )
    db.add(change)
    db.commit()
    workbook_bytes = build_assessment_workbook(db, change)
    workbook = load_workbook(BytesIO(workbook_bytes))
    rows = list(workbook.active.iter_rows(values_only=True))
    assert rows == [("control_id", "status", "owner", "evidence_ref", "note")]


# ── OSCAL ──────────────────────────────────────────────────────────────

def test_oscal_export_shape_and_both_source_documents(db, seeded):
    change = db.get(Change, seeded["change_id"])
    export = build_oscal_export(db, change)
    control = export["catalog"]["groups"][0]["controls"][0]
    assert control["id"] == "2-5-3"
    prose_by_prop = {p["prop-name"]: p["prose"] for p in control["parts"]}
    assert prose_by_prop["previous-text"] == "Old requirement text."
    assert prose_by_prop["current-text"] == "New, stricter requirement text."

    docs = export["xposure-change-metadata"]["source_documents"]
    assert {d["version_label"] for d in docs} == {"1-2018", "2-2024"}
    assert {d["sha256"] for d in docs} == {"aaa111", "bbb222"}


# ── PDF ────────────────────────────────────────────────────────────────

def test_pdf_html_marks_changed_sentences_and_cites_both_documents(db, seeded):
    change = db.get(Change, seeded["change_id"])
    html_doc = build_change_report_html(db, change, priority_score=55, priority_band="high")
    assert "<mark>Old requirement text.</mark>" in html_doc
    assert "<mark>New, stricter requirement text.</mark>" in html_doc
    assert "aaa111" in html_doc and "bbb222" in html_doc
    assert "1-2018" in html_doc and "2-2024" in html_doc
    assert "OT Engineering" not in html_doc  # org-graph detail belongs to the Excel export, not this report


def test_render_change_pdf_produces_a_real_pdf(db, seeded):
    change = db.get(Change, seeded["change_id"])
    pdf_bytes = render_change_pdf(db, change, priority_score=55, priority_band="high")
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000


# ── Routes (404s, content types) ─────────────────────────────────────────

def test_export_routes_404_for_unknown_change(client):
    assert client.get("/changes/999999/export/pdf").status_code == 404
    assert client.get("/changes/999999/export/excel").status_code == 404
    assert client.get("/changes/999999/export/oscal").status_code == 404


def test_export_routes_return_expected_content_types(client, seeded):
    change_id = seeded["change_id"]
    pdf = client.get(f"/changes/{change_id}/export/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"

    excel = client.get(f"/changes/{change_id}/export/excel")
    assert excel.status_code == 200
    assert "spreadsheetml" in excel.headers["content-type"]

    oscal = client.get(f"/changes/{change_id}/export/oscal")
    assert oscal.status_code == 200
    assert oscal.headers["content-type"].startswith("application/json")

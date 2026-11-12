"""
Unit tests for app/exports/summary_pdf.py and the GET /exports/summary
route — the executive-summary counterpart to test_exports.py's per-change
PDF tests. Same in-memory-SQLite discipline and the same "actually call
Playwright, don't mock it" rule: this is exactly the kind of export bug
(a bad f-string, an unescaped field) that only a real render catches.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Change, Regulation, Regulator
from app.db.session import get_db
from app.exports.summary_pdf import build_summary_report_html, render_summary_pdf
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
    nca = Regulator(code="nca", name_ar="الهيئة", name_en="National Cybersecurity Authority", weight=1.0)
    sama = Regulator(code="sama", name_ar="ساما", name_en="Saudi Central Bank", weight=1.2)
    db.add_all([nca, sama])
    db.flush()

    reg_ecc = Regulation(regulator_id=nca.id, code="ecc", title_ar="الضوابط", title_en="Essential Cybersecurity Controls")
    reg_crf = Regulation(regulator_id=sama.id, code="crf", title_ar="الإطار", title_en="Cyber Security Framework")
    db.add_all([reg_ecc, reg_crf])
    db.flush()

    def _version(regulation):
        from app.db.models import RegulationVersion

        v = RegulationVersion(regulation_id=regulation.id, version_label="1-2024", file_sha256="sha", source_url="")
        db.add(v)
        db.flush()
        return v

    v_ecc = _version(reg_ecc)
    v_crf = _version(reg_crf)

    changes = [
        Change(
            regulation_id=reg_ecc.id, from_version_id=v_ecc.id, to_version_id=v_ecc.id,
            old_clause_id="2-5-1", new_clause_id="2-5-1", match_kind="exact_id",
            change_type="new_obligation", material=True, confidence=0.9,
            summary_en="A brand new obligation was introduced for network segmentation. It requires quarterly reviews.",
            summary_ar="x",
            effective_date=date.today() + timedelta(days=10),
            created_at=datetime.utcnow() - timedelta(days=1),
        ),
        Change(
            regulation_id=reg_ecc.id, from_version_id=v_ecc.id, to_version_id=v_ecc.id,
            old_clause_id="2-5-2", new_clause_id="2-5-2", match_kind="exact_id",
            change_type="tightened", material=True, confidence=0.9,
            summary_en="<script>alert(1)</script> the control now requires MFA.",
            summary_ar="x",
            effective_date=date.today() + timedelta(days=200),
            created_at=datetime.utcnow() - timedelta(days=40),
        ),
        Change(
            regulation_id=reg_crf.id, from_version_id=v_crf.id, to_version_id=v_crf.id,
            old_clause_id="3-1-1", new_clause_id="3-1-1", match_kind="exact_id",
            change_type="editorial", material=False, confidence=1.0,
            summary_en="Fixed a typo.",
            summary_ar="x",
            created_at=datetime.utcnow() - timedelta(days=2),
        ),
        Change(
            regulation_id=reg_crf.id, from_version_id=v_crf.id, to_version_id=v_crf.id,
            old_clause_id="3-1-2", new_clause_id=None, match_kind="withdrawn",
            change_type="withdrawn", material=True, confidence=0.8,
            summary_en="A requirement was withdrawn.",
            summary_ar="x",
            created_at=datetime.utcnow() - timedelta(days=3),
        ),
    ]
    db.add_all(changes)
    db.commit()

    return {"change_ids": [c.id for c in changes]}


def _material_changes(db):
    return list(db.query(Change).filter(Change.material.is_(True)).order_by(Change.id).all())


# ── HTML ───────────────────────────────────────────────────────────────

def test_summary_html_escapes_malicious_summary_and_counts_bands(db, seeded):
    changes = _material_changes(db)
    html_doc = build_summary_report_html(db, changes, filters={})

    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_doc

    assert "National Cybersecurity Authority" in html_doc
    assert "Saudi Central Bank" in html_doc
    assert "New obligation" in html_doc
    assert "Withdrawn" in html_doc
    # editorial change is material=False and excluded from the input list
    assert "Fixed a typo" not in html_doc


def test_summary_html_reflects_filters_block(db, seeded):
    changes = _material_changes(db)
    html_doc = build_summary_report_html(
        db, changes, filters={"regulator": "nca", "since": "2024-01-01", "band": "critical"}
    )
    assert "nca" in html_doc
    assert "2024-01-01" in html_doc
    assert "CRITICAL" in html_doc


# ── PDF ────────────────────────────────────────────────────────────────

def test_render_summary_pdf_produces_a_real_pdf(db, seeded):
    changes = _material_changes(db)
    pdf_bytes = render_summary_pdf(db, changes, filters={})
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000


def test_render_summary_pdf_handles_empty_change_list(db, seeded):
    pdf_bytes = render_summary_pdf(db, [], filters={"band": "critical"})
    assert pdf_bytes.startswith(b"%PDF-")


# ── Route ──────────────────────────────────────────────────────────────

def test_export_summary_route_returns_pdf(client, seeded):
    resp = client.get("/exports/summary")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
    assert "attachment" in resp.headers["content-disposition"]


def test_export_summary_route_filters_by_regulator(client, db, seeded):
    resp = client.get("/exports/summary", params={"regulator": "sama"})
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")


def test_export_summary_route_filters_by_band_and_since(client, seeded):
    resp = client.get("/exports/summary", params={"band": "critical", "since": "2020-01-01"})
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")

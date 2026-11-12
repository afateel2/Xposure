"""
M7 GET /trends tests.

Same discipline as test_routes.py: a real SQLAlchemy session against an
in-memory SQLite database via FastAPI's dependency_overrides on get_db.
routes/trends.py groups in Python rather than via SQL date_trunc()
specifically so this file can run against SQLite unchanged from how the
route runs against the real Postgres backend — see that module's docstring.

trends.router is not yet registered on app.main.app (that registration is
a separate, concurrently-run integration pass — see this module's task
boundary). This file therefore builds its own minimal FastAPI app around
just trends.router rather than importing app.main.app, so these tests do
not depend on, or need to wait for, that integration pass landing.
"""

from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Change, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.routes import trends

app = FastAPI()
app.include_router(trends.router)


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
    """Two regulators, one regulation each, and a handful of Change rows
    spread across two months and a mix of change_types/materiality —
    enough to exercise the group-by-(month, regulator, regulation,
    change_type, band) aggregation and the material_only/regulator/
    regulation filters."""
    nca = Regulator(code="nca", name_ar="الهيئة", name_en="National Cybersecurity Authority", weight=1.0)
    sama = Regulator(code="sama", name_ar="ساما", name_en="Saudi Central Bank", weight=1.0)
    db.add_all([nca, sama])
    db.flush()

    ecc = Regulation(regulator_id=nca.id, code="ecc", title_ar="الضوابط", title_en="Essential Cybersecurity Controls")
    crf = Regulation(regulator_id=sama.id, code="crf", title_ar="اطار", title_en="Cyber Resilience Framework")
    db.add_all([ecc, crf])
    db.flush()

    v1 = RegulationVersion(regulation_id=ecc.id, version_label="1", file_sha256="aaa", source_url="")
    v2 = RegulationVersion(regulation_id=crf.id, version_label="1", file_sha256="bbb", source_url="")
    db.add_all([v1, v2])
    db.flush()

    def make_change(**kwargs):
        defaults = dict(
            from_version_id=v1.id,
            to_version_id=v1.id,
            old_clause_id="1",
            new_clause_id="1",
            match_kind="exact_id",
            material=True,
            confidence=0.9,
            summary_en="",
            summary_ar="",
        )
        defaults.update(kwargs)
        return Change(**defaults)

    changes = [
        # September, nca/ecc, two tightened changes -> should collapse to one row with count=2
        make_change(regulation_id=ecc.id, change_type="tightened", created_at=datetime(2026, 9, 5)),
        make_change(regulation_id=ecc.id, change_type="tightened", created_at=datetime(2026, 9, 20)),
        # September, nca/ecc, new_obligation -> separate row (different change_type)
        make_change(regulation_id=ecc.id, change_type="new_obligation", created_at=datetime(2026, 9, 10)),
        # October, sama/crf, withdrawn
        make_change(regulation_id=crf.id, change_type="withdrawn", created_at=datetime(2026, 10, 1)),
        # September, sama/crf, editorial and non-material -> excluded when material_only=True
        make_change(regulation_id=crf.id, change_type="editorial", material=False, created_at=datetime(2026, 9, 15)),
        # unclassified (change_type None) -> always excluded, never raises
        make_change(regulation_id=ecc.id, change_type=None, created_at=datetime(2026, 9, 12)),
    ]
    db.add_all(changes)
    db.commit()

    return {"nca_id": nca.id, "sama_id": sama.id}


# ── GET /trends ─────────────────────────────────────────────────────────

def test_trends_groups_by_month_regulator_regulation_change_type_band(client, seeded):
    response = client.get("/trends")
    assert response.status_code == 200
    body = response.json()

    # material_only defaults to True: the non-material editorial row and
    # the unclassified row are both excluded, leaving 4 changes across 3
    # groups (the two September nca/ecc/tightened rows collapse into one).
    assert sum(row["count"] for row in body) == 4

    tightened_row = next(
        r for r in body if r["change_type"] == "tightened" and r["regulator_code"] == "nca"
    )
    assert tightened_row["period"] == "2026-09"
    assert tightened_row["regulation_code"] == "ecc"
    assert tightened_row["count"] == 2
    assert tightened_row["band"] in ("critical", "high", "medium", "low")

    new_obligation_row = next(r for r in body if r["change_type"] == "new_obligation")
    assert new_obligation_row["period"] == "2026-09"
    assert new_obligation_row["count"] == 1

    withdrawn_row = next(r for r in body if r["change_type"] == "withdrawn")
    assert withdrawn_row["period"] == "2026-10"
    assert withdrawn_row["regulator_code"] == "sama"
    assert withdrawn_row["regulation_code"] == "crf"
    assert withdrawn_row["count"] == 1

    assert not any(r["change_type"] == "editorial" for r in body)


def test_trends_material_only_false_includes_editorial(client, seeded):
    response = client.get("/trends?material_only=false")
    body = response.json()
    assert sum(row["count"] for row in body) == 5  # +1 editorial, unclassified still excluded

    editorial_row = next(r for r in body if r["change_type"] == "editorial")
    assert editorial_row["count"] == 1
    assert editorial_row["band"] == "low"  # material=False gate caps it, per priority.py


def test_trends_regulator_filter(client, seeded):
    response = client.get("/trends?regulator=sama")
    body = response.json()
    assert all(r["regulator_code"] == "sama" for r in body)
    assert sum(row["count"] for row in body) == 1  # only the material withdrawn change


def test_trends_regulation_filter(client, seeded):
    response = client.get("/trends?regulation=ecc")
    body = response.json()
    assert all(r["regulation_code"] == "ecc" for r in body)
    assert sum(row["count"] for row in body) == 3


def test_trends_invalid_group_by_is_rejected(client, seeded):
    response = client.get("/trends?group_by=week")
    assert response.status_code == 422


def test_trends_empty_db_returns_empty_list(client, db):
    response = client.get("/trends")
    assert response.status_code == 200
    assert response.json() == []

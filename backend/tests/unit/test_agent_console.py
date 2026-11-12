"""
Tests for the agent control pad (app/routes/agent_console.py).

Same in-memory-SQLite pattern as tests/unit/test_routes.py. The most
important test here is test_command_matching_nothing_returns_empty_lists:
the endpoint's whole safety property is that an unrecognized command
returns nothing, never "everything" — if that test ever fails, the
free-text box has stopped being a preview and started being a way to
silently select every row in the database.
"""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Action, Change, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.routes import agent_console

# This router isn't registered on app.main's FastAPI instance yet — that's
# a separate integration pass happening concurrently with this task (see
# the task boundaries: main.py is off-limits here). So these tests mount
# the router on a throwaway FastAPI app of their own, same dependency-
# override pattern tests/unit/test_routes.py uses against the real app.
_test_app = FastAPI()
_test_app.include_router(agent_console.router)


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

    _test_app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(_test_app)
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def seeded(db):
    """One regulator/regulation/version pair, plus four changes chosen so
    priority.explain_priority() lands them in known, verified bands
    (checked by hand against app/priority.py before writing these tests):
      - tightened_high: change_type=tightened, 2 impacted nodes, due in
        10 days -> score 63, band "high".
      - tightened_medium: same change_type, 0 impacted nodes, no deadline
        -> score 30, band "medium". Same type as above, different band —
        exists to prove the band signal actually filters, not just the
        change_type signal.
      - clarification_low: change_type=clarification, 0 impacted nodes, no
        deadline -> score 14, band "low". Different type from both above —
        exists to prove the change_type signal filters.
      - resolved_tightened_high: identical shape to tightened_high (so it
        matches every signal a command could name) but its one Action is
        already "approved", not "pending" — exists to prove a resolved
        action never appears in matched_action_ids even when its change
        matches everything.
    """
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

    def make_change(**kwargs):
        change = Change(
            regulation_id=regulation.id,
            from_version_id=v1.id,
            to_version_id=v2.id,
            match_kind="exact_id",
            material=True,
            confidence=0.9,
            summary_en="x",
            summary_ar="x",
            **kwargs,
        )
        db.add(change)
        db.flush()
        return change

    tightened_high = make_change(
        old_clause_id="2-5-3-1", new_clause_id="2-5-3-1", change_type="tightened",
        effective_date=date.today() + timedelta(days=10), grace_days=0,
    )
    tightened_medium = make_change(
        old_clause_id="2-5-4-1", new_clause_id="2-5-4-1", change_type="tightened",
    )
    clarification_low = make_change(
        old_clause_id="2-6-1-1", new_clause_id="2-6-1-1", change_type="clarification",
    )
    resolved_tightened_high = make_change(
        old_clause_id="2-5-3-9", new_clause_id="2-5-3-9", change_type="tightened",
        effective_date=date.today() + timedelta(days=10), grace_days=0,
    )
    db.flush()

    from app.db.models import Impact, OrgNode

    node1 = OrgNode(type="policy", name="Node 1", attrs_json={})
    node2 = OrgNode(type="policy", name="Node 2", attrs_json={})
    db.add_all([node1, node2])
    db.flush()
    db.add_all([
        Impact(change_id=tightened_high.id, node_id=node1.id, path_json={}, recommended_actions_json=[]),
        Impact(change_id=tightened_high.id, node_id=node2.id, path_json={}, recommended_actions_json=[]),
        Impact(change_id=resolved_tightened_high.id, node_id=node1.id, path_json={}, recommended_actions_json=[]),
        Impact(change_id=resolved_tightened_high.id, node_id=node2.id, path_json={}, recommended_actions_json=[]),
    ])
    db.flush()

    pending_action = Action(
        change_id=tightened_high.id, type="update_policy", level="draft_then_approve", status="pending",
        payload_json={},
    )
    medium_action = Action(
        change_id=tightened_medium.id, type="update_policy", level="draft_then_approve", status="pending",
        payload_json={},
    )
    clarification_action = Action(
        change_id=clarification_low.id, type="update_policy", level="draft_then_approve", status="pending",
        payload_json={},
    )
    resolved_action = Action(
        change_id=resolved_tightened_high.id, type="update_policy", level="draft_then_approve", status="approved",
        payload_json={},
    )
    db.add_all([pending_action, medium_action, clarification_action, resolved_action])
    db.commit()

    return {
        "tightened_high_id": tightened_high.id,
        "tightened_medium_id": tightened_medium.id,
        "clarification_low_id": clarification_low.id,
        "resolved_tightened_high_id": resolved_tightened_high.id,
        "pending_action_id": pending_action.id,
        "medium_action_id": medium_action.id,
        "clarification_action_id": clarification_action.id,
        "resolved_action_id": resolved_action.id,
    }


# ── GET /agent/suggestions ─────────────────────────────────────────────

def test_suggestions_returns_nonempty_bilingual_list(client):
    response = client.get("/agent/suggestions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    for item in body:
        assert item["text_en"]
        assert item["text_ar"]
        assert item["id"]


# ── POST /agent/command_preview ────────────────────────────────────────

def test_change_type_and_band_signals_and_together(client, seeded):
    response = client.post("/agent/command_preview", json={"command": "show me tightened changes at high priority"})
    assert response.status_code == 200
    body = response.json()
    # Both tightened_high and resolved_tightened_high are change_type=tightened,
    # band=high — the change-level match correctly includes both; medium_id and
    # clarification_low_id (wrong band / wrong type) are correctly excluded.
    assert set(body["matched_change_ids"]) == {seeded["tightened_high_id"], seeded["resolved_tightened_high_id"]}
    # resolved_tightened_high's only Action is already "approved" (not pending),
    # so only tightened_high's pending action shows up as bulk-actionable.
    assert body["matched_action_ids"] == [seeded["pending_action_id"]]
    assert body["confidence"] == pytest.approx(0.75)  # change_type + band + verb(list/show)
    assert body["proposed_decision"] == "summarize"
    assert "tightened" in body["explanation_en"]
    assert body["explanation_ar"]


def test_command_matching_nothing_returns_empty_lists(client, seeded):
    response = client.post("/agent/command_preview", json={"command": "good morning, how is everyone doing today"})
    assert response.status_code == 200
    body = response.json()
    assert body["matched_change_ids"] == []
    assert body["matched_action_ids"] == []
    assert body["proposed_decision"] is None
    assert body["confidence"] == 0.0
    assert "No changes matched" in body["explanation_en"]


def test_bare_verb_with_no_scoping_signal_matches_nothing(client, seeded):
    """Regression test for a real bug found by reproducing it, not just
    reading the code: a verb alone ("approve") used to count as one
    matched signal and fall through into an unscoped `select(Change)`,
    silently matching every change in the table — exactly the "matched
    everything" failure mode this module's own docstring says can never
    happen. A decision verb must never be enough on its own; it needs at
    least one scoping signal (change type, band, clause id, or
    regulator/regulation) alongside it."""
    response = client.post("/agent/command_preview", json={"command": "approve"})
    assert response.status_code == 200
    body = response.json()
    assert body["matched_change_ids"] == []
    assert body["matched_action_ids"] == []
    assert body["proposed_decision"] is None
    assert body["confidence"] == 0.0
    assert "approve" in body["explanation_en"]
    assert "nothing scopes" in body["explanation_en"]


def test_approve_verb_sets_proposed_decision_approve(client, seeded):
    response = client.post(
        "/agent/command_preview",
        json={"command": "approve the clarification changes"},
    )
    body = response.json()
    assert body["proposed_decision"] == "approve"
    assert body["matched_change_ids"] == [seeded["clarification_low_id"]]
    assert body["matched_action_ids"] == [seeded["clarification_action_id"]]


def test_dismiss_verb_sets_proposed_decision_dismiss(client, seeded):
    response = client.post(
        "/agent/command_preview",
        json={"command": "dismiss the tightened changes at medium priority"},
    )
    body = response.json()
    assert body["proposed_decision"] == "dismiss"
    assert body["matched_change_ids"] == [seeded["tightened_medium_id"]]


def test_resolved_action_never_included_even_when_change_matches_every_signal(client, seeded):
    response = client.post(
        "/agent/command_preview",
        json={"command": "approve the tightened changes for clause 2-5-3-9 at high priority"},
    )
    body = response.json()
    assert body["matched_change_ids"] == [seeded["resolved_tightened_high_id"]]
    assert body["matched_action_ids"] == []


def test_clause_id_signal_matches_by_regex(client, seeded):
    response = client.post(
        "/agent/command_preview",
        json={"command": "what about clause 2-5-4-1"},
    )
    body = response.json()
    assert body["matched_change_ids"] == [seeded["tightened_medium_id"]]


def test_regulator_keyword_matches_all_seeded_changes(client, seeded):
    response = client.post(
        "/agent/command_preview",
        json={"command": "list ecc changes"},
    )
    body = response.json()
    assert set(body["matched_change_ids"]) == {
        seeded["tightened_high_id"],
        seeded["tightened_medium_id"],
        seeded["clarification_low_id"],
        seeded["resolved_tightened_high_id"],
    }

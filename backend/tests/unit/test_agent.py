"""
M6 agent-loop tests.

Two deliberate choices about how these are written:

1. The database is real (SQLite in-memory, the project's own SQLAlchemy
   models, `Base.metadata.create_all`), not a mock. The nodes' interesting
   behaviour IS their SQL — "which changes still need action", "don't
   create a second Action for the same (change, node, type)", "an audit row
   per node" — and a MagicMock session would happily agree with whatever
   the code did, including the wrong thing.

2. The LLM-calling steps are patched out, exactly as tests/unit/test_diff.py
   patches classify_change: `run_diff` (M3, calls the model) and M4's
   `compute_impact_for_change` (impact notes) are replaced at the single
   deferred-import seam each has in graph.py. What is under test here is
   orchestration — ordering, routing, persistence, the interrupt — not the
   model.

The full-run tests use LangGraph's InMemorySaver rather than
PostgresSaver so they need no live Postgres; PostgresSaver is exercised
separately against the real database (see the milestone report), since
what differs between the two is storage, not graph semantics.
"""

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import audit
from app.agent import graph
from app.db.base import Base
from app.db.models import (
    Action,
    AuditLog,
    Change,
    Impact,
    OrgNode,
    Regulation,
    RegulationVersion,
    Regulator,
)

ECC1 = "Essential Cybersecurity Controls (ECC-1-2018).pdf"
ECC2 = "Essential Cybersecurity Controls (ECC-2-2024).pdf"


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def engine():
    # StaticPool + a single shared connection: every node opens its OWN
    # Session(get_engine()), and a default in-memory SQLite engine would
    # hand each one a separate, empty database.
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _wire_engine(engine):
    """Both graph.py and audit.py resolve their engine through the
    db.session helper; pointing that at the test engine is the whole
    wiring these tests need."""
    with patch.object(graph, "get_engine", lambda: engine), patch.object(
        audit, "get_engine", lambda: engine
    ):
        yield


def seed_regulation(db: Session, labels: tuple[str, ...] = ("1-2018", "2-2024"), hashes: tuple[str, ...] | None = None) -> list[RegulationVersion]:
    regulator = Regulator(code="nca", name_en="NCA", name_ar="الهيئة", weight=1.0)
    db.add(regulator)
    db.flush()
    regulation = Regulation(regulator_id=regulator.id, code="ecc", title_en="ECC", title_ar="الضوابط")
    db.add(regulation)
    db.flush()
    versions = []
    for i, label in enumerate(labels):
        version = RegulationVersion(
            regulation_id=regulation.id,
            version_label=label,
            file_sha256=(hashes[i] if hashes else f"hash-{label}"),
        )
        db.add(version)
        versions.append(version)
    db.commit()
    return versions


def make_change(db: Session, versions: list[RegulationVersion], **kwargs) -> Change:
    defaults = dict(
        regulation_id=versions[0].regulation_id,
        from_version_id=versions[0].id,
        to_version_id=versions[1].id,
        old_clause_id="2-5-1",
        new_clause_id="2-5-1",
        match_kind="exact_id",
        change_type="tightened",
        material=True,
        confidence=0.9,
    )
    defaults.update(kwargs)
    change = Change(**defaults)
    db.add(change)
    db.commit()
    return change


def write_source_file(dirpath: Path, name: str, content: bytes = b"%PDF-1.4 fake") -> Path:
    path = dirpath / name
    path.write_bytes(content)
    return path


# ── check_sources ─────────────────────────────────────────────────────────

def test_known_file_whose_hash_is_in_the_db_is_already_ingested(db, tmp_path):
    path = write_source_file(tmp_path, ECC1)
    digest = graph._sha256(path)
    versions = seed_regulation(db, labels=("1-2018",), hashes=(digest,))

    with patch.object(graph, "SOURCES_DIR", tmp_path):
        found = graph.detect_new_sources(db)

    assert len(found) == 1
    assert found[0]["status"] == "already_ingested"
    assert found[0]["version_id"] == versions[0].id


def test_known_file_absent_from_the_db_is_new(db, tmp_path):
    write_source_file(tmp_path, ECC2)
    seed_regulation(db, labels=("1-2018",))

    with patch.object(graph, "SOURCES_DIR", tmp_path):
        found = graph.detect_new_sources(db)

    assert found[0]["status"] == "new"
    assert found[0]["version_label"] == "2-2024"
    assert found[0]["regulator"] == "nca"


def test_unknown_filename_is_reported_not_guessed_at(db, tmp_path):
    # Auto-detecting regulator/regulation/version/table-convention from an
    # arbitrary PDF is explicitly unsolved (KnownSource's docstring) — the
    # file must surface as needing attention, never be ingested on a guess.
    write_source_file(tmp_path, "SASO Technical Regulation 2026.pdf")
    seed_regulation(db)

    with patch.object(graph, "SOURCES_DIR", tmp_path):
        found = graph.detect_new_sources(db)

    assert found[0]["status"] == "unrecognized"
    assert "version_label" not in found[0]


def test_known_file_with_changed_bytes_under_an_ingested_label_is_a_conflict(db, tmp_path):
    # regulation_version rows are immutable (M2). A recognized file whose
    # content differs from what was ingested under that label must never be
    # silently re-ingested over the top of it.
    write_source_file(tmp_path, ECC1, content=b"%PDF-1.4 REPUBLISHED")
    seed_regulation(db, labels=("1-2018",), hashes=("some-other-hash",))

    with patch.object(graph, "SOURCES_DIR", tmp_path):
        found = graph.detect_new_sources(db)

    assert found[0]["status"] == "conflict"
    assert found[0]["existing_version_sha256"] == "some-other-hash"


def test_check_sources_node_audits_what_it_saw(db, tmp_path):
    write_source_file(tmp_path, ECC2)
    seed_regulation(db, labels=("1-2018",))

    with patch.object(graph, "SOURCES_DIR", tmp_path):
        out = graph.check_sources_node({"run_id": "r1"})

    assert len(out["new_files"]) == 1
    entry = db.scalar(select(AuditLog).where(AuditLog.event == "sources_checked"))
    assert entry is not None
    assert entry.actor == "agent:check_sources_node"
    assert entry.payload_json["counts"] == {"new": 1}


# ── ingest_new ────────────────────────────────────────────────────────────

def test_ingest_new_ingests_only_files_marked_new(db, tmp_path):
    seed_regulation(db, labels=("1-2018",))
    calls = []

    def fake_ingest(regulator, regulation, version_label, path, code_before_text=False, replace=False):
        calls.append((regulator, regulation, version_label, Path(path).name, code_before_text))

    state = {
        "run_id": "r1",
        "sources": [
            {"path": ECC1, "sha256": "h1", "status": "already_ingested"},
            {"path": ECC2, "sha256": "h2", "status": "new",
             "regulator": "nca", "regulation": "ecc", "version_label": "2-2024"},
        ],
        "new_files": [
            {"path": ECC2, "sha256": "h2", "status": "new",
             "regulator": "nca", "regulation": "ecc", "version_label": "2-2024"},
        ],
    }
    with patch.object(graph, "SOURCES_DIR", tmp_path), patch.object(
        graph, "_load_ingest", lambda: fake_ingest
    ):
        out = graph.ingest_new_node(state)

    # The code-before-text flag is not a detail the loop may get wrong:
    # passing ECC-2:2024 the ECC-1 convention silently mis-parses the whole
    # document (see ingest.py's module docstring).
    assert calls == [("nca", "ecc", "2-2024", ECC2, True)]
    assert len(out["ingested"]) == 1


def test_ingest_new_preserves_earlier_files_audit_trail_when_a_later_file_fails(db, tmp_path):
    """Regression test for the same bug class as
    test_diff_node_preserves_earlier_pairs_audit_trail_when_a_later_pair_fails,
    found by tracing the identical shape in ingest_new_node: ingest()
    commits a file's RegulationVersion/Clause rows itself, in its own
    transaction, the moment it succeeds. The old ingest_new_node deferred
    every file's audit record to a pass over the whole batch, so a later
    file failing (a malformed PDF, a conflicting version label) left an
    earlier, successfully-ingested file's rows committed with no
    source_ingested audit row — and on retry, detect_new_sources() would
    report it as already_ingested (it only checks file_sha256) and never
    surface that it has no audit record. Fixed the same way: record each
    file's audit trail immediately after its own ingest() call, in the
    same loop iteration."""
    seed_regulation(db, labels=())  # regulator/regulation only, no versions yet
    state = {
        "run_id": "r1",
        "sources": [],
        "new_files": [
            {"path": ECC1, "sha256": "h1", "status": "new",
             "regulator": "nca", "regulation": "ecc", "version_label": "1-2018"},
            {"path": ECC2, "sha256": "h2", "status": "new",
             "regulator": "nca", "regulation": "ecc", "version_label": "2-2024"},
        ],
    }

    def flaky_ingest(regulator, regulation, version_label, path, code_before_text=False, replace=False):
        if version_label == "1-2018":
            # Mirrors what a real ingest() does on success: it commits its
            # own RegulationVersion (and Clause rows), in its own
            # transaction, before returning — see app/ingest.py's ingest().
            regulation_row = db.scalar(select(Regulation).where(Regulation.code == "ecc"))
            db.add(RegulationVersion(regulation_id=regulation_row.id, version_label="1-2018", file_sha256="h1"))
            db.commit()
            return
        raise RuntimeError("simulated malformed PDF on the second file")

    with patch.object(graph, "SOURCES_DIR", tmp_path), patch.object(graph, "_load_ingest", lambda: flaky_ingest):
        with pytest.raises(RuntimeError, match="simulated malformed PDF"):
            graph.ingest_new_node(state)

    # The first file's RegulationVersion is real and committed, exactly as
    # a real ingest() call would leave it — its audit trail must be too,
    # even though the node as a whole raised on the second file.
    db.expire_all()
    version = db.scalar(select(RegulationVersion).where(RegulationVersion.version_label == "1-2018"))
    assert version is not None

    source_ingested = db.scalar(select(AuditLog).where(AuditLog.event == "source_ingested"))
    assert source_ingested is not None
    assert source_ingested.payload_json["version_label"] == "1-2018"
    assert source_ingested.ref_id == version.id

    # The run-level summary must NOT exist — the node never reached it.
    assert db.scalar(select(AuditLog).where(AuditLog.event == "ingest_new_completed")) is None


def test_ingest_new_writes_baseline_ingested_when_the_regulation_has_no_prior_version(db, tmp_path):
    """A brand-new regulation's first-ever version has nothing to diff
    against, so diff_node will never produce a Change for it — without a
    distinct signal, the Dashboard (and the audit trail) would show
    nothing at all for that ingest, indistinguishable from it never having
    happened. baseline_ingested is that signal, written alongside (not
    instead of) the normal source_ingested row."""
    seed_regulation(db, labels=())  # regulator/regulation only, no versions yet

    def fake_ingest(regulator, regulation, version_label, path, code_before_text=False, replace=False):
        regulation_row = db.scalar(select(Regulation).where(Regulation.code == "ecc"))
        db.add(RegulationVersion(regulation_id=regulation_row.id, version_label=version_label, file_sha256="h1"))
        db.commit()

    state = {
        "run_id": "r1",
        "sources": [],
        "new_files": [
            {"path": ECC1, "sha256": "h1", "status": "new",
             "regulator": "nca", "regulation": "ecc", "version_label": "1-2018"},
        ],
    }
    with patch.object(graph, "SOURCES_DIR", tmp_path), patch.object(graph, "_load_ingest", lambda: fake_ingest):
        graph.ingest_new_node(state)

    db.expire_all()
    baseline = db.scalar(select(AuditLog).where(AuditLog.event == "baseline_ingested"))
    assert baseline is not None
    assert baseline.payload_json["version_label"] == "1-2018"
    assert baseline.payload_json["note"] == "no prior version to diff against yet"


def test_ingest_new_does_not_write_baseline_ingested_when_a_prior_version_already_exists(db, tmp_path):
    seed_regulation(db, labels=("1-2018",))  # a prior version already exists

    def fake_ingest(regulator, regulation, version_label, path, code_before_text=False, replace=False):
        regulation_row = db.scalar(select(Regulation).where(Regulation.code == "ecc"))
        db.add(RegulationVersion(regulation_id=regulation_row.id, version_label=version_label, file_sha256="h2"))
        db.commit()

    state = {
        "run_id": "r1",
        "sources": [],
        "new_files": [
            {"path": ECC2, "sha256": "h2", "status": "new",
             "regulator": "nca", "regulation": "ecc", "version_label": "2-2024"},
        ],
    }
    with patch.object(graph, "SOURCES_DIR", tmp_path), patch.object(graph, "_load_ingest", lambda: fake_ingest):
        graph.ingest_new_node(state)

    db.expire_all()
    assert db.scalar(select(AuditLog).where(AuditLog.event == "baseline_ingested")) is None
    assert db.scalar(select(AuditLog).where(AuditLog.event == "source_ingested")) is not None


def test_ingest_new_surfaces_files_it_would_not_touch(db, tmp_path):
    seed_regulation(db)
    state = {
        "run_id": "r1",
        "sources": [
            {"path": "mystery.pdf", "sha256": "h", "status": "unrecognized"},
            {"path": ECC1, "sha256": "h2", "status": "conflict"},
        ],
        "new_files": [],
    }
    with patch.object(graph, "SOURCES_DIR", tmp_path):
        graph.ingest_new_node(state)

    entry = db.scalar(select(AuditLog).where(AuditLog.event == "ingest_new_completed"))
    flagged = {s["path"] for s in entry.payload_json["needs_manual_attention"]}
    assert flagged == {"mystery.pdf", ECC1}


# ── diff ──────────────────────────────────────────────────────────────────

def test_pending_diff_pairs_finds_consecutive_undiffed_versions(db):
    versions = seed_regulation(db)
    pairs = graph.pending_diff_pairs(db)
    assert len(pairs) == 1
    assert (pairs[0]["from_label"], pairs[0]["to_label"]) == ("1-2018", "2-2024")
    assert pairs[0]["from_version_id"] == versions[0].id


def test_pending_diff_pairs_skips_a_pair_that_already_has_changes(db):
    versions = seed_regulation(db)
    make_change(db, versions)
    assert graph.pending_diff_pairs(db) == []


def test_pending_diff_pairs_only_pairs_consecutive_versions(db):
    seed_regulation(db, labels=("1-2018", "2-2024", "3-2029"))
    pairs = graph.pending_diff_pairs(db)
    assert [(p["from_label"], p["to_label"]) for p in pairs] == [
        ("1-2018", "2-2024"),
        ("2-2024", "3-2029"),
    ]


def test_diff_node_calls_run_diff_once_per_pending_pair(db):
    seed_regulation(db)
    calls = []

    def fake_run_diff(regulator, regulation, from_label, to_label, dry_run=False, replace=False):
        calls.append((regulator, regulation, from_label, to_label, dry_run, replace))

    with patch.object(graph, "_load_run_diff", lambda: fake_run_diff):
        out = graph.diff_node({"run_id": "r1"})

    assert calls == [("nca", "ecc", "1-2018", "2-2024", False, False)]
    assert len(out["diffed_pairs"]) == 1
    assert db.scalar(select(AuditLog).where(AuditLog.event == "diff_completed")) is not None


def test_diff_node_does_not_call_the_model_when_nothing_is_pending(db):
    versions = seed_regulation(db)
    make_change(db, versions)

    def explode():  # _load_run_diff must not even be reached
        raise AssertionError("run_diff must not be loaded when no pair needs diffing")

    with patch.object(graph, "_load_run_diff", explode):
        out = graph.diff_node({"run_id": "r1"})

    assert out["diffed_pairs"] == []


def test_diff_node_preserves_earlier_pairs_audit_trail_when_a_later_pair_fails(db):
    """Regression test for a real bug found while stress-testing the
    agent's resumability (not hypothesized — traced through the actual
    code, then reproduced here): run_diff() commits a pair's Change rows
    itself, in its own transaction, the moment it succeeds. The old
    diff_node deferred that pair's audit trail and webhook notification to
    a second pass over EVERY pair processed in the run. If a later pending
    pair then failed (a flaky LLM call, say), the earlier pair's Change
    rows stayed committed with no audit_log row and no webhook ever sent —
    and pending_diff_pairs() would skip that pair as "already diffed" on
    every future retry, forever, since it only checks whether Change rows
    exist for it. Not exercised by today's single-regulation corpus (one
    pair only) but a live gap the moment a second regulation exists — see
    docs/PLAN.md's bulletproofing section. Fixed by recording each pair's
    audit trail immediately after its own run_diff() call, in the same
    loop iteration, not deferred to the end of the node."""
    versions = seed_regulation(db, labels=("1-2018", "2-2024", "3-2029"))

    def flaky_run_diff(regulator, regulation, from_label, to_label, dry_run=False, replace=False):
        if to_label == "2-2024":
            # Mirrors what a real run_diff() does on success: it commits
            # its own Change row(s), in its own transaction, before
            # returning — see app/diff.py's run_diff().
            db.add(Change(
                regulation_id=versions[0].regulation_id,
                from_version_id=versions[0].id, to_version_id=versions[1].id,
                old_clause_id="1-1", new_clause_id="1-1", match_kind="exact_id",
                change_type="tightened", material=True, confidence=0.9,
                summary_en="x", summary_ar="x",
            ))
            db.commit()
            return
        raise RuntimeError("simulated LLM failure on the second pending pair")

    with patch.object(graph, "_load_run_diff", lambda: flaky_run_diff):
        with pytest.raises(RuntimeError, match="simulated LLM failure"):
            graph.diff_node({"run_id": "r1"})

    # The first pair's Change row is real and committed, exactly as a real
    # run_diff() call would leave it. The point of this test: its audit
    # trail must be durable too, even though the node as a whole raised
    # partway through the second pair.
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Change)) == 1

    versions_diffed = db.scalar(select(AuditLog).where(AuditLog.event == "versions_diffed"))
    assert versions_diffed is not None
    assert versions_diffed.payload_json["from_label"] == "1-2018"
    assert versions_diffed.payload_json["to_label"] == "2-2024"
    assert db.scalar(select(AuditLog).where(AuditLog.event == "diff_pair_completed")) is not None

    # The run-level summary must NOT exist — the node never reached it,
    # and the run as a whole correctly still counts as failed.
    assert db.scalar(select(AuditLog).where(AuditLog.event == "diff_completed")) is None


# ── impact ────────────────────────────────────────────────────────────────

def test_changes_needing_action_excludes_immaterial_and_already_actioned(db):
    versions = seed_regulation(db)
    material = make_change(db, versions, new_clause_id="1-1-1")
    make_change(db, versions, new_clause_id="1-1-2", change_type="editorial", material=False)
    acted = make_change(db, versions, new_clause_id="1-1-3")
    db.add(Action(change_id=acted.id, type="update_policy", level="notify_only"))
    db.commit()

    assert [c.id for c in graph.changes_needing_action(db)] == [material.id]


def test_impact_node_does_not_recompute_existing_impacts(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    node = OrgNode(type="policy", name="Access Control Policy")
    db.add(node)
    db.flush()
    db.add(Impact(change_id=change.id, node_id=node.id, recommended_actions_json=["update_policy"]))
    db.commit()

    def explode(db_, change_):
        raise AssertionError("M4's impact traversal (and its LLM call) must not run twice for one change")

    with patch.object(graph, "_load_compute_impact", lambda: explode):
        out = graph.impact_node({"run_id": "r1"})

    assert out["change_ids"] == [change.id]
    assert out["impacted"][0]["recomputed"] is False
    assert db.scalar(select(AuditLog).where(AuditLog.event == "impact_reused")) is not None


def test_impact_node_calls_m4_for_a_change_with_no_impacts(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    node = OrgNode(type="product", name="Radar Unit")
    db.add(node)
    db.commit()

    def fake_impact(session, change_):
        row = Impact(change_id=change_.id, node_id=node.id, recommended_actions_json=["reassess_control"])
        session.add(row)
        session.flush()
        return [row]

    with patch.object(graph, "_load_compute_impact", lambda: fake_impact):
        out = graph.impact_node({"run_id": "r1"})

    assert out["impacted"][0]["recomputed"] is True
    assert out["impacted"][0]["impact_count"] == 1


# ── prioritize ────────────────────────────────────────────────────────────

def test_prioritize_node_records_score_and_band_per_change(db):
    versions = seed_regulation(db)
    change = make_change(db, versions, effective_date=date.today())
    node = OrgNode(type="process", name="Change Management")
    db.add(node)
    db.flush()
    db.add(Impact(change_id=change.id, node_id=node.id, recommended_actions_json=["update_procedure"]))
    db.commit()

    seen = {}

    def fake_priority(change_, impacted_node_count, days_to_effective, regulator_weight=1.0):
        seen["args"] = (change_.id, impacted_node_count, days_to_effective, regulator_weight)
        return {"score": 72, "band": "high"}

    with patch.object(graph, "_load_explain_priority", lambda: fake_priority):
        out = graph.prioritize_node({"run_id": "r1", "change_ids": [change.id]})

    # The regulator weight is resolved by this node and passed in, keeping
    # compute_priority() a pure function of its arguments.
    assert seen["args"] == (change.id, 1, 0, 1.0)
    assert out["priorities"][str(change.id)]["score"] == 72
    assert out["priorities"][str(change.id)]["band"] == "high"
    entry = db.scalar(select(AuditLog).where(AuditLog.event == "change_prioritized"))
    assert entry.ref_id == change.id


def test_prioritize_node_rejects_a_score_outside_0_100(db):
    # Priority is specified as a deterministic 0-100 integer; a value
    # outside that is a bug in the formula, and writing it into an action
    # payload would quietly corrupt every ranking downstream.
    versions = seed_regulation(db)
    change = make_change(db, versions)

    with patch.object(
        graph, "_load_explain_priority", lambda: (lambda c, n, d, regulator_weight=1.0: {"score": 140, "band": "critical"})
    ):
        with pytest.raises(ValueError, match="out-of-range score"):
            graph.prioritize_node({"run_id": "r1", "change_ids": [change.id]})


def test_prioritize_node_passes_none_when_no_effective_date(db):
    versions = seed_regulation(db)
    change = make_change(db, versions, effective_date=None)
    seen = {}

    def fake_priority(change_, count, days, regulator_weight=1.0):
        seen["days"] = days
        return {"score": 10, "band": "low"}

    with patch.object(graph, "_load_explain_priority", lambda: fake_priority):
        graph.prioritize_node({"run_id": "r1", "change_ids": [change.id]})

    assert seen["days"] is None


# ── apply_policy ──────────────────────────────────────────────────────────

def _policy(level="draft_then_approve"):
    return lambda: (lambda action_type, change_type, confidence: {"level": level, "requested": level, "gates": []})


def test_apply_policy_creates_one_action_per_recommended_action(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    node = OrgNode(type="policy", name="Crypto Policy")
    db.add(node)
    db.flush()
    db.add(Impact(change_id=change.id, node_id=node.id,
                  recommended_actions_json=["update_policy", "collect_evidence"]))
    db.commit()

    with patch.object(graph, "_load_explain_automation", _policy()):
        out = graph.apply_policy_node({
            "run_id": "r1",
            "change_ids": [change.id],
            "priorities": {str(change.id): {"score": 80, "band": "critical"}},
        })

    actions = list(db.scalars(select(Action)))
    assert {a.type for a in actions} == {"update_policy", "collect_evidence"}
    assert all(a.status == "pending" and a.level == "draft_then_approve" for a in actions)
    assert actions[0].payload_json["priority_band"] == "critical"
    assert actions[0].payload_json["impact_node_id"] == node.id
    assert out["review_action_ids"] == [a.id for a in actions]
    assert out["auto_executable_action_ids"] == []


def test_apply_policy_does_not_create_duplicates_on_a_second_pass(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    node = OrgNode(type="policy", name="Crypto Policy")
    db.add(node)
    db.flush()
    db.add(Impact(change_id=change.id, node_id=node.id, recommended_actions_json=["update_policy"]))
    db.commit()

    state = {"run_id": "r1", "change_ids": [change.id], "priorities": {}}
    with patch.object(graph, "_load_explain_automation", _policy()):
        graph.apply_policy_node(state)
        second = graph.apply_policy_node(state)

    assert db.scalar(select(Action).where(Action.type == "update_policy")) is not None
    assert len(list(db.scalars(select(Action)))) == 1
    assert second["action_ids"] == []


def test_apply_policy_refuses_an_action_type_outside_the_vocabulary(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    node = OrgNode(type="policy", name="P")
    db.add(node)
    db.flush()
    db.add(Impact(change_id=change.id, node_id=node.id, recommended_actions_json=["delete_everything"]))
    db.commit()

    with patch.object(graph, "_load_explain_automation", _policy()):
        with pytest.raises(ValueError, match="fixed action vocabulary"):
            graph.apply_policy_node({"run_id": "r1", "change_ids": [change.id], "priorities": {}})


def test_apply_policy_refuses_an_unknown_automation_level(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    node = OrgNode(type="policy", name="P")
    db.add(node)
    db.flush()
    db.add(Impact(change_id=change.id, node_id=node.id, recommended_actions_json=["update_policy"]))
    db.commit()

    with patch.object(graph, "_load_explain_automation", _policy(level="just_do_it")):
        with pytest.raises(ValueError, match="unknown automation level"):
            graph.apply_policy_node({"run_id": "r1", "change_ids": [change.id], "priorities": {}})


def test_apply_policy_sets_owner_only_when_the_impacted_node_is_an_owner(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    owner = OrgNode(type="owner", name="Head of Cybersecurity")
    product = OrgNode(type="product", name="Radar Unit")
    db.add_all([owner, product])
    db.flush()
    db.add_all([
        Impact(change_id=change.id, node_id=owner.id, recommended_actions_json=["notify_owner"]),
        Impact(change_id=change.id, node_id=product.id, recommended_actions_json=["technical_change"]),
    ])
    db.commit()

    with patch.object(graph, "_load_explain_automation", _policy()):
        graph.apply_policy_node({"run_id": "r1", "change_ids": [change.id], "priorities": {}})

    by_type = {a.type: a for a in db.scalars(select(Action))}
    assert by_type["notify_owner"].owner_node_id == owner.id
    assert by_type["technical_change"].owner_node_id is None  # never a guessed owner


def test_due_date_is_effective_date_plus_grace_or_nothing(db):
    versions = seed_regulation(db)
    with_grace = make_change(db, versions, effective_date=date(2026, 1, 1), grace_days=90)
    no_date = make_change(db, versions, new_clause_id="9-9-9", effective_date=None, grace_days=None)

    assert graph._due_date(with_grace) == date(2026, 4, 1)
    assert graph._due_date(no_date) is None  # never an invented deadline


# ── auto_execute ──────────────────────────────────────────────────────────

def test_auto_execute_marks_done_and_says_nothing_external_happened(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    action = Action(change_id=change.id, type="collect_evidence", level="auto_execute", payload_json={})
    db.add(action)
    db.commit()

    out = graph.auto_execute_node({"run_id": "r1", "auto_executable_action_ids": [action.id]})

    db.refresh(action)
    assert out["auto_executed_action_ids"] == [action.id]
    assert action.status == "done"
    assert "no downstream GRC/ERP system" in action.payload_json["external_effect"]
    entry = db.scalar(select(AuditLog).where(AuditLog.event == "action_auto_executed"))
    assert entry.ref_id == action.id
    assert entry.payload_json["previous_status"] == "pending"
    assert entry.payload_json["via"] == "auto_execute"


def test_auto_execute_leaves_an_already_decided_action_alone(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    action = Action(change_id=change.id, type="collect_evidence", level="auto_execute", status="dismissed")
    db.add(action)
    db.commit()

    out = graph.auto_execute_node({"run_id": "r1", "auto_executable_action_ids": [action.id]})

    db.refresh(action)
    assert out["auto_executed_action_ids"] == []
    assert action.status == "dismissed"


# ── routing ───────────────────────────────────────────────────────────────

def test_routing_after_policy():
    assert graph.route_after_policy({"auto_executable_action_ids": [1], "review_action_ids": [2]}) == "auto_execute"
    assert graph.route_after_policy({"review_action_ids": [2]}) == "human_review"
    assert graph.route_after_policy({}) == "deliver"


def test_routing_after_auto_execute():
    assert graph.route_after_auto_execute({"review_action_ids": [2]}) == "human_review"
    assert graph.route_after_auto_execute({}) == "deliver"


# ── human review decision validation ──────────────────────────────────────

def test_decision_with_an_unknown_action_id_is_rejected():
    with pytest.raises(ValueError, match="not awaiting review"):
        graph._validate_decision({"approved": [99]}, {1, 2})


def test_decision_approving_and_dismissing_the_same_action_is_rejected():
    with pytest.raises(ValueError, match="both approved and dismissed"):
        graph._validate_decision({"approved": [1], "dismissed": [1]}, {1})


def test_decision_must_be_a_mapping():
    with pytest.raises(ValueError, match="must be a dict"):
        graph._validate_decision(["approve everything"], {1})


# ── whole graph: interrupt + resume ───────────────────────────────────────

def _memory_checkpointer_factory():
    """One saver shared across run_once() and resume_run() within a test —
    they each open the checkpointer independently, which is the point of a
    checkpointer, so a per-call InMemorySaver would lose the checkpoint
    between them and the "resume" would silently be a fresh run."""
    saver = InMemorySaver()

    @contextmanager
    def _cm():
        yield saver

    return _cm


def _fixture_for_full_run(db, action_types: list[str], level_by_type: dict[str, str]):
    versions = seed_regulation(db)
    change = make_change(db, versions, effective_date=date(2026, 1, 1))
    node = OrgNode(type="policy", name="Access Control Policy")
    db.add(node)
    db.flush()
    db.add(Impact(change_id=change.id, node_id=node.id, recommended_actions_json=action_types))
    db.commit()
    return change, node


def _patched_full_run(db, level_by_type: dict[str, str], tmp_path: Path):
    """Every seam the loop has to the outside world, replaced at once:
    file drops (an empty directory), M2 ingestion, M3's diff (the LLM
    call), M4's impact traversal, M5's two pure functions, and the
    checkpointer."""
    return [
        patch.object(graph, "SOURCES_DIR", tmp_path),
        patch.object(graph, "_load_ingest", lambda: (lambda *a, **k: None)),
        patch.object(graph, "_load_run_diff", lambda: (lambda *a, **k: None)),
        patch.object(graph, "_load_compute_impact", lambda: (lambda *a, **k: [])),
        patch.object(
            graph, "_load_explain_priority", lambda: (lambda c, n, d, regulator_weight=1.0: {"score": 65, "band": "high"})
        ),
        patch.object(
            graph, "_load_explain_automation",
            lambda: (lambda action_type, change_type, confidence: {
                "level": level_by_type[action_type], "requested": level_by_type[action_type], "gates": [],
            }),
        ),
        patch.object(graph, "checkpointer", _memory_checkpointer_factory()),
    ]


def test_full_run_pauses_at_human_review_then_resumes_and_delivers(db, tmp_path):
    change, _ = _fixture_for_full_run(db, ["update_policy", "collect_evidence"], {})
    levels = {"update_policy": "draft_then_approve", "collect_evidence": "auto_execute"}

    patches = _patched_full_run(db, levels, tmp_path)
    for p in patches:
        p.start()
    try:
        result = graph.run_once(thread_id="t-full")

        # Paused, genuinely: the interrupt is in the returned state and
        # `deliver` has NOT run yet.
        assert "__interrupt__" in result
        awaiting = result["__interrupt__"][0].value["awaiting"]
        assert [a["type"] for a in awaiting] == ["update_policy"]
        assert awaiting[0]["priority_band"] == "high"
        assert db.scalar(select(AuditLog).where(AuditLog.event == "run_delivered")) is None

        # The auto_execute branch ran before the pause.
        auto = db.scalar(select(Action).where(Action.type == "collect_evidence"))
        assert auto.status == "done"
        review = db.scalar(select(Action).where(Action.type == "update_policy"))
        assert review.status == "pending"

        final = graph.resume_run("t-full", approved=[review.id], dismissed=[])
    finally:
        for p in patches:
            p.stop()

    db.refresh(review)
    assert review.status == "approved"
    assert final["summary"]["actions_created"] == 2
    assert final["summary"]["actions_auto_executed"] == 1
    assert final["review_decision"]["approved"] == [review.id]
    assert db.scalar(select(AuditLog).where(AuditLog.event == "run_delivered")) is not None

    resumed_approval = db.scalar(
        select(AuditLog).where(AuditLog.event == "action_approved", AuditLog.ref_id == review.id)
    )
    assert resumed_approval.payload_json["previous_status"] == "pending"
    assert resumed_approval.payload_json["via"] == "cli_resume"


def test_resume_rejects_a_decision_on_an_action_the_api_already_resolved(db, tmp_path):
    """Regression test for a real bug found while stress-testing the
    resume path (not the bug originally hypothesized — the real behavior
    turned out worse): a graph run pauses at human_review with action X
    awaiting a decision; meanwhile M7's API (routes/actions.py) approves
    or dismisses X directly, independently of this paused run — which is
    the documented, deliberate design (human_review_node's own docstring:
    "The global inbox is M7's UI, which approves/dismisses through the
    API rather than by resuming a graph thread"). The first hypothesis was
    that resuming the stale thread would hit _validate_decision and raise
    a clean "not awaiting review" error. Running it for real showed
    something quieter and worse: human_review_node re-queries
    Action.status == "pending" on resume, finds nothing pending (X is no
    longer "pending"), takes its own early-return path ("nothing pending
    — not pausing") WITHOUT ever calling interrupt() again — so
    _validate_decision is never even reached, the stale --approve is
    silently discarded, and the run reports success as if nothing was
    unusual. resume_run() now checks the named action ids' current status
    before ever invoking Command(resume=...), the same way it already
    checked thread existence — see that function's docstring for the
    full account, and docs/PLAN.md's bulletproofing section."""
    change, _ = _fixture_for_full_run(db, ["update_policy"], {})
    levels = {"update_policy": "draft_then_approve"}

    patches = _patched_full_run(db, levels, tmp_path)
    for p in patches:
        p.start()
    try:
        result = graph.run_once(thread_id="t-race")
        awaiting = result["__interrupt__"][0].value["awaiting"]
        action_id = awaiting[0]["action_id"]

        # Simulate the API resolving this exact action while the graph
        # thread is still paused — precisely what routes/actions.py's
        # approve_action() does: set status, audit it, commit. Done
        # directly against the DB here (not through the FastAPI route)
        # since this test is about graph.py's own resume-time defenses,
        # not the API layer.
        action = db.get(Action, action_id)
        action.status = "approved"
        db.commit()

        # A stale resume that still tries to decide on the now-resolved
        # action must be refused, not applied on top of the API's
        # decision and not silently treated as a no-op.
        with pytest.raises(SystemExit, match="no longer pending"):
            graph.resume_run("t-race", approved=[action_id], dismissed=[])
    finally:
        for p in patches:
            p.stop()

    # The API's decision must survive untouched — the stale resume
    # neither overwrote it nor produced a second, conflicting audit trail —
    # and the refusal itself is audited, the same way an unknown-thread
    # resume already is.
    db.refresh(action)
    assert action.status == "approved"
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.event == "action_approved")
        )
        == 0  # this test approved the action directly, not through audited API/CLI code paths
    )
    assert db.scalar(select(AuditLog).where(AuditLog.event == "resume_failed")) is not None


def test_resuming_an_unknown_thread_refuses_instead_of_starting_a_new_run(db, tmp_path):
    # LangGraph itself will happily run the graph from the top if you
    # resume a thread_id it has never seen. For this loop that would mean
    # a typo silently re-scanning sources and creating a second set of
    # actions, so resume_run() checks first.
    with patch.object(graph, "checkpointer", _memory_checkpointer_factory()):
        with pytest.raises(SystemExit, match="No paused run found"):
            graph.resume_run("never-ran", approved=[], dismissed=[])

    assert list(db.scalars(select(AuditLog))) != []  # the refusal is itself audited
    assert db.scalar(select(AuditLog).where(AuditLog.event == "resume_failed")) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.event == "sources_checked")) is None


def test_full_run_with_nothing_to_review_goes_straight_to_deliver(db, tmp_path):
    _fixture_for_full_run(db, ["collect_evidence"], {})
    patches = _patched_full_run(db, {"collect_evidence": "auto_execute"}, tmp_path)
    for p in patches:
        p.start()
    try:
        result = graph.run_once(thread_id="t-auto")
    finally:
        for p in patches:
            p.stop()

    assert "__interrupt__" not in result
    assert result["summary"]["actions_auto_executed"] == 1
    assert result["summary"]["actions_created"] == 1


def test_every_node_that_ran_wrote_an_audit_row(db, tmp_path):
    # The takeoff prompt's hard guardrail for M6: every node writes to the
    # append-only audit log — including the ones that found nothing to do.
    _fixture_for_full_run(db, ["collect_evidence"], {})
    patches = _patched_full_run(db, {"collect_evidence": "auto_execute"}, tmp_path)
    for p in patches:
        p.start()
    try:
        graph.run_once(thread_id="t-audit")
    finally:
        for p in patches:
            p.stop()

    actors = {row.actor for row in db.scalars(select(AuditLog))}
    assert actors >= {
        "agent:check_sources_node",
        "agent:ingest_new_node",
        "agent:diff_node",
        "agent:impact_node",
        "agent:prioritize_node",
        "agent:apply_policy_node",
        "agent:auto_execute_node",
        "agent:deliver_node",
    }


def test_a_failing_node_aborts_the_run_and_is_audited(db, tmp_path):
    # No silent fallback: a failure inside the loop must surface as a
    # failure, with a record of it, not as a quietly shorter run.
    _fixture_for_full_run(db, ["update_policy"], {})

    def boom(*args, **kwargs):
        raise RuntimeError("LLM endpoint unreachable")

    patches = _patched_full_run(db, {"update_policy": "notify_only"}, tmp_path)
    patches.append(patch.object(graph, "_load_explain_priority", lambda: boom))
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError, match="LLM endpoint unreachable"):
            graph.run_once(thread_id="t-fail")
    finally:
        for p in patches:
            p.stop()

    failure = db.scalar(select(AuditLog).where(AuditLog.event == "run_failed"))
    assert failure is not None
    assert "LLM endpoint unreachable" in failure.payload_json["error"]
    assert db.scalar(select(AuditLog).where(AuditLog.event == "run_delivered")) is None


# ── plumbing ──────────────────────────────────────────────────────────────

def test_checkpoint_dsn_drops_the_sqlalchemy_driver_prefix():
    # langgraph-checkpoint-postgres hands the DSN to psycopg, which does
    # not understand SQLAlchemy's "+psycopg" dialect suffix.
    with patch.object(graph.settings, "database_url", "postgresql+psycopg://u:p@127.0.0.1:5442/xposure"):
        assert graph.checkpoint_dsn() == "postgresql://u:p@127.0.0.1:5442/xposure"


def test_version_labels_sort_numerically_not_lexicographically():
    labels = ["10-2030", "2-2024", "1-2018"]
    assert sorted(labels, key=graph._version_sort_key) == ["1-2018", "2-2024", "10-2030"]


def test_graphs_copy_of_the_action_vocabulary_matches_m4s():
    # graph.py keeps its own copy so the loop can validate what it is
    # about to PERSIST without importing M4 just for a constant. That is
    # only safe if the two lists cannot drift apart unnoticed.
    from app import impact

    assert graph.ACTION_VOCABULARY == set(impact.ACTION_TYPES)


def test_graphs_copy_of_the_automation_levels_matches_m5s():
    from app import policy

    assert graph.AUTOMATION_LEVELS == set(policy.AUTOMATION_LEVELS)


def test_regulator_weight_is_resolved_not_assumed(db):
    versions = seed_regulation(db)
    change = make_change(db, versions)
    regulator = db.scalar(select(Regulator))
    regulator.weight = 1.4
    db.commit()

    assert graph._regulator_weight(db, change, {}) == 1.4

    orphan = make_change(db, versions, new_clause_id="7-7-7", regulation_id=999)
    with pytest.raises(ValueError, match="refusing to assume"):
        graph._regulator_weight(db, orphan, {})


def test_audit_record_writes_an_append_only_row(db):
    entry = audit.record(db, actor="agent:test", event="something_happened",
                         ref_type="change", ref_id=7, payload={"k": "v"})
    assert entry.id is not None
    stored = db.get(AuditLog, entry.id)
    assert (stored.actor, stored.event, stored.ref_type, stored.ref_id) == (
        "agent:test", "something_happened", "change", 7,
    )
    assert stored.payload_json == {"k": "v"}


def test_audit_record_in_new_session_survives_a_caller_with_a_broken_session(db):
    # The failure path's whole reason for existing.
    entry_id = audit.record_in_new_session(actor="agent:runner", event="run_failed", payload={"error": "boom"})
    assert db.get(AuditLog, entry_id).payload_json["error"] == "boom"


# ── pipeline_lock (closes the "no run-level concurrency lock" risk) ──────

def test_pipeline_lock_is_a_noop_on_sqlite(db):
    # _wire_engine (autouse) points graph.get_engine at the SQLite test
    # engine; pg_try_advisory_lock does not exist there, so this must not
    # try to call it — every unit test in this file runs the real pipeline
    # against SQLite and would break if pipeline_lock assumed Postgres.
    with graph.pipeline_lock() as acquired:
        assert acquired is True


def test_pipeline_lock_acquires_and_releases_a_real_postgres_advisory_lock():
    """Mocked DBAPI connection (dialect name alone decides the code path,
    see pipeline_lock's docstring) — no real Postgres needed to verify the
    SQL it issues and that it always releases on the way out."""
    from unittest.mock import MagicMock

    cursor = MagicMock()
    cursor.fetchone.return_value = (True,)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    engine.raw_connection.return_value = conn

    with patch.object(graph, "get_engine", lambda: engine):
        with graph.pipeline_lock() as acquired:
            assert acquired is True

    lock_call = cursor.execute.call_args_list[0]
    assert "pg_try_advisory_lock" in lock_call.args[0]
    unlock_call = cursor.execute.call_args_list[-1]
    assert "pg_advisory_unlock" in unlock_call.args[0]
    conn.close.assert_called_once()


def test_pipeline_lock_reports_not_acquired_without_calling_unlock():
    from unittest.mock import MagicMock

    cursor = MagicMock()
    cursor.fetchone.return_value = (False,)  # another process holds it
    conn = MagicMock()
    conn.cursor.return_value = cursor
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    engine.raw_connection.return_value = conn

    with patch.object(graph, "get_engine", lambda: engine):
        with graph.pipeline_lock() as acquired:
            assert acquired is False

    assert all("pg_advisory_unlock" not in c.args[0] for c in cursor.execute.call_args_list)
    conn.close.assert_called_once()  # the connection itself is still cleaned up


def test_run_once_refuses_to_start_when_the_pipeline_lock_is_held(db):
    """A busy lock is reported the same honest way any other failed run is
    (run_failed, re-raised), not silently queued or silently ignored."""
    from contextlib import contextmanager

    @contextmanager
    def _always_busy(timeout_seconds: float = 0.0):
        yield False

    with patch.object(graph, "pipeline_lock", _always_busy):
        with pytest.raises(graph.PipelineBusy):
            graph.run_once()

    rows = db.scalars(select(AuditLog).where(AuditLog.event == "run_failed")).all()
    assert rows and "advisory lock" in rows[-1].payload_json["error"]

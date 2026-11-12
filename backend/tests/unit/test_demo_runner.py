"""
The demo scan end to end on SQLite: state machine, stage counts, honest
cache reporting, restart safety, double click, failure, reset idempotency.

The graph is the REAL graph (LangGraph, InMemorySaver, its own nodes, the
real human_review interrupt). Only the model call, the PDF ingest and the
scoring seams are fakes (see demo_fixtures.py).
"""

import threading

import pytest
from sqlalchemy import func, select

from app import audit, llm_cache
from app.agent import graph
from app.config import settings
from app.db.models import Action, AuditLog, Change, Clause, Impact, RegulationVersion
from app.demo import baseline, mirror, runner
from app.demo import constants as C
from app.demo.tracker import TRACKER, DemoConflict, RunTracker

from .demo_fixtures import ECC1, ECC2, ECC2_BYTES, demo_env  # noqa: F401  (fixture)


def _run_scan_sync(run_id="run-test-1"):
    assert TRACKER.try_start(run_id)
    runner._execute(run_id)
    return TRACKER.snapshot()


def _stage(run, key):
    return next(s for s in run["stages"] if s["key"] == key)


def _events(env, *names):
    with env.session() as db:
        return [e for e in db.scalars(select(AuditLog).where(AuditLog.event.in_(names)).order_by(AuditLog.id))]


# ── the happy path ────────────────────────────────────────────────────────

def test_scan_reaches_awaiting_review_with_every_stage_done(demo_env):
    demo_env.seed_baseline()
    run = _run_scan_sync()

    assert run["status"] == "awaiting_review"
    assert [s["key"] for s in run["stages"]] == list(C.STAGE_KEYS)
    assert all(s["status"] == "done" for s in run["stages"]), [(s["key"], s["status"]) for s in run["stages"]]
    assert run["finished_at"] and run["started_at"]

    assert _stage(run, "portal")["counts"] == {
        "documents_on_portal": 2, "already_known": 1, "new_documents": 1, "needs_attention": 0}
    assert "ECC-2:2024" in _stage(run, "portal")["detail_en"]
    fetch = _stage(run, "fetch")
    assert fetch["counts"]["files_fetched"] == 1 and "portal mirror" in fetch["detail_en"]
    assert (demo_env.sources / "nca" / ECC2).read_bytes() == ECC2_BYTES  # really copied and verified
    assert _stage(run, "ingest")["counts"]["clauses_ingested"] == 3
    align = _stage(run, "align")["counts"]
    assert (align["exact_id"], align["new"], align["to_classify"]) == (2, 1, 3)
    classify = _stage(run, "classify")["counts"]
    assert classify["changes_classified"] == 3 and classify["material_changes"] == 2
    assert _stage(run, "impact")["counts"]["impacted_nodes"] == 2
    assert _stage(run, "policy")["counts"]["actions_created"] == 4
    assert _stage(run, "auto_execute")["counts"]["auto_executed"] == 2
    assert _stage(run, "review")["counts"]["awaiting_review"] == 2

    with demo_env.session() as db:
        assert db.scalar(select(func.count()).select_from(Action)) == 4
        assert db.scalar(select(func.count()).select_from(Action).where(Action.status == "done")) == 2
    assert demo_env.ingest_calls[-1][2] == "2-2024"


def test_scan_writes_the_audit_events_with_the_run_id(demo_env):
    demo_env.seed_baseline()
    _run_scan_sync("run-audit-1")
    events = _events(demo_env, *C.RUN_EVENTS)
    names = [e.event for e in events]
    assert names[0] == "scan_requested" and names[-1] == "scan_completed"
    assert names.count("stage_started") == 10 and names.count("stage_completed") == 10
    assert all(e.payload_json["run_id"] == "run-audit-1" for e in events)
    done = next(e for e in events if e.event == "stage_completed" and e.payload_json["stage"] == "classify")
    assert done.payload_json["counts"]["changes_classified"] == 3
    # the pipeline's own events carry the same run id, so the feed can join them
    with demo_env.session() as db:
        delivered = db.scalars(select(AuditLog).where(AuditLog.event == "run_paused_for_human_review")).all()
    assert delivered and delivered[0].payload_json["run_id"] == "run-audit-1"


def test_first_run_reports_live_answers_and_second_run_reports_cache_hits(demo_env):
    demo_env.seed_baseline()
    first = _run_scan_sync("run-cold")
    c1 = _stage(first, "classify")["counts"]
    assert (c1["llm_calls"], c1["llm_cache_hits"], c1["llm_live_calls"]) == (3, 0, 3)
    assert "0 of 3 answered from the local cache" in _stage(first, "classify")["detail_en"]
    assert "produced live" in first["note_en"] or "live" in first["note_en"]

    baseline.reset_to_baseline()
    demo_env.model_calls = 0
    second = _run_scan_sync("run-warm")
    c2 = _stage(second, "classify")["counts"]
    assert (c2["llm_calls"], c2["llm_cache_hits"], c2["llm_live_calls"]) == (3, 3, 0)
    assert "3 of 3 answered from the local cache of an earlier identical run" in _stage(second, "classify")["detail_en"]
    assert "من الذاكرة المحلية لتشغيل سابق مطابق" in _stage(second, "classify")["detail_ar"]
    i2 = _stage(second, "impact")["counts"]
    assert i2["llm_cache_hits"] == i2["llm_calls"] == 2
    assert demo_env.model_calls == 0  # nothing reached the "model" on the replay
    assert "of" in second["note_en"] and "local cache" in second["note_en"]
    assert "replays the regulator portal from a local mirror folder" in second["note_en"]
    assert second["summary"]["llm_cache_hits"] == 5


def test_pacing_pause_is_declared_in_the_note(demo_env, monkeypatch):
    monkeypatch.setattr(settings, "demo_stage_pacing_ms", 1)
    demo_env.seed_baseline()
    run = _run_scan_sync()
    assert "1 ms pause between stages is a demo setting" in run["note_en"]


# ── nothing new, double click, failure ────────────────────────────────────

def test_scan_with_nothing_new_completes_honestly_with_only_the_portal_stage(demo_env):
    demo_env.seed_baseline()
    _run_scan_sync("run-b")  # the company now has ECC-2:2024 ingested and its actions created
    # a further scan: mirror has nothing new and no unfinished work remains
    with demo_env.session() as db:
        for a in db.scalars(select(Action).where(Action.status == "pending")):
            a.status = "approved"
        db.commit()
    third = _run_scan_sync("run-c")
    assert third["status"] == "completed"
    assert [s["key"] for s in third["stages"]] == ["portal"]
    assert _stage(third, "portal")["counts"]["new_documents"] == 0
    assert "nothing was run" in third["note_en"]


def test_second_start_while_running_is_refused_atomically(demo_env):
    demo_env.seed_baseline()
    assert TRACKER.try_start("run-1") is True
    assert TRACKER.try_start("run-2") is False
    assert TRACKER.snapshot()["run_id"] == "run-1"


def test_start_scan_double_click_returns_the_running_run(demo_env, monkeypatch):
    demo_env.seed_baseline()
    started = threading.Event()
    release = threading.Event()

    def blocking_execute(run_id):
        started.set()
        release.wait(5)

    monkeypatch.setattr(runner, "_execute", blocking_execute)
    first = runner.start_scan()
    assert first["already_running"] is False and first["status"] == "running"
    started.wait(5)
    second = runner.start_scan()
    assert second["already_running"] is True and second["run_id"] == first["run_id"]
    release.set()


def test_scan_is_refused_when_demo_mode_is_off(demo_env, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    with pytest.raises(DemoConflict):
        runner.start_scan()
    with pytest.raises(DemoConflict):
        baseline.reset_to_baseline()


def test_pipeline_failure_marks_the_stage_failed_and_the_run_failed(demo_env, monkeypatch):
    demo_env.seed_baseline()

    def broken_diff():
        def run_diff(*a, **k):
            raise RuntimeError("model unreachable")
        return run_diff

    monkeypatch.setattr(graph, "_load_run_diff", broken_diff)
    run = _run_scan_sync("run-fail")
    assert run["status"] == "failed"
    assert run["error"]["reason"].startswith("RuntimeError: ") or "model unreachable" in run["error"]["reason"]
    failed = [s for s in run["stages"] if s["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["key"] == "align"
    assert "model unreachable" in failed[0]["detail_en"]
    assert [s["status"] for s in run["stages"] if s["key"] in ("impact", "review")] == ["pending", "pending"]
    events = [e.event for e in _events(demo_env, "scan_failed", "scan_completed", "run_failed")]
    assert "scan_failed" in events and "run_failed" in events and "scan_completed" not in events


def test_empty_portal_mirror_fails_loudly(demo_env):
    demo_env.seed_baseline()
    for f in list(demo_env.portal.rglob("*.pdf")):
        f.unlink()
    for f in list((demo_env.sources).rglob("*.pdf")):
        f.unlink()
    run = _run_scan_sync("run-empty")
    assert run["status"] == "failed" and _stage(run, "portal")["status"] == "failed"
    assert "portal mirror is empty" in run["error"]["reason"]


# ── restart safety ────────────────────────────────────────────────────────

def test_run_is_reconstructed_from_audit_after_a_restart(demo_env):
    demo_env.seed_baseline()
    _run_scan_sync("run-restart")
    fresh = RunTracker()  # a new process: empty memory
    run = fresh.snapshot()
    assert run["run_id"] == "run-restart" and run["status"] == "awaiting_review"
    assert _stage(run, "classify")["counts"]["changes_classified"] == 3
    assert run["summary"]["awaiting_review"] == 2


def test_orphaned_running_scan_becomes_failed_never_running(demo_env):
    demo_env.seed_baseline()
    TRACKER.try_start("run-orphan")
    TRACKER.stage_start("portal")
    fresh = RunTracker()  # the process that owned the thread is gone (same pid, no thread)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.demo.tracker.pid_alive", lambda pid: False)
        run = fresh.snapshot()
    assert run["status"] == "failed" and run["error"]["error_type"] == "Interrupted"
    assert _stage(run, "portal")["status"] == "failed"
    assert [e.event for e in _events(demo_env, "scan_failed")] == ["scan_failed"]
    assert fresh.is_running() is False


def test_scan_owned_by_a_live_other_process_reads_as_running(demo_env, monkeypatch):
    demo_env.seed_baseline()
    audit.record_in_new_session(
        actor="user:demo", event="scan_requested",
        payload={"run_id": "run-foreign", "started_at": "2026-09-19T10:00:00Z", "pid": 4242, "host": "x"},
    )
    monkeypatch.setattr("app.demo.tracker.pid_alive", lambda pid: pid == 4242)
    fresh = RunTracker()
    assert fresh.snapshot()["status"] == "running" and fresh.is_running() is True
    assert fresh.try_start("run-mine") is False
    # the other process finishes: the next read sees the terminal event
    audit.record_in_new_session(
        actor="agent:demo_runner", event="scan_completed",
        payload={"run_id": "run-foreign", "status": "awaiting_review", "finished_at": "2026-09-19T10:01:00Z"},
    )
    assert fresh.snapshot()["status"] == "awaiting_review"


def test_reset_written_by_another_process_clears_this_process_view(demo_env):
    demo_env.seed_baseline()
    _run_scan_sync("run-x")
    assert TRACKER.snapshot()["status"] == "awaiting_review"
    audit.record_in_new_session(actor="user:demo", event="demo_reset", payload={"source": "prepare"})
    assert TRACKER.snapshot()["status"] == "idle"


# ── reset ─────────────────────────────────────────────────────────────────

def test_reset_restores_baseline_and_is_idempotent(demo_env):
    demo_env.seed_baseline()
    _run_scan_sync("run-r")
    first = baseline.reset_to_baseline()
    assert first["status"] == "ok" and first["phase"] == "baseline"
    assert first["cleared"]["actions"] == 4 and first["cleared"]["changes"] == 3
    assert first["cleared"]["versions_removed"] == ["2-2024"]
    assert first["cleared"]["clauses_removed"] == 3
    assert first["cleared"]["source_files_removed"] == [f"nca/{ECC2}"]
    assert first["baseline"] == {"regulation_versions": ["1-2018"], "clauses": 2, "indexed_points": 2, "repaired": False}
    assert not (demo_env.sources / "nca" / ECC2).exists()
    assert (demo_env.portal / "nca" / ECC2).exists()  # the mirror keeps the document

    with demo_env.session() as db:
        assert [v.version_label for v in db.scalars(select(RegulationVersion))] == ["1-2018"]
        for model in (Action, Impact, Change):
            assert db.scalar(select(func.count()).select_from(model)) == 0

    again = baseline.reset_to_baseline()
    assert again["cleared"]["actions"] == 0 and again["cleared"]["versions_removed"] == []
    assert again["cleared"]["source_files_removed"] == []
    assert TRACKER.snapshot()["status"] == "idle"


def test_reset_never_deletes_audit_rows_and_appends_demo_reset(demo_env):
    demo_env.seed_baseline()
    _run_scan_sync("run-audit")
    with demo_env.session() as db:
        before = db.scalar(select(func.count()).select_from(AuditLog))
    baseline.reset_to_baseline()
    with demo_env.session() as db:
        after = db.scalar(select(func.count()).select_from(AuditLog))
        last = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert after == before + 1
    assert last.event == "demo_reset" and last.payload_json["cleared"]["actions"] == 4


def test_reset_is_refused_while_a_scan_runs(demo_env):
    demo_env.seed_baseline()
    TRACKER.try_start("run-busy")
    with pytest.raises(DemoConflict):
        baseline.reset_to_baseline()


def test_reset_repairs_a_missing_baseline_index(demo_env, monkeypatch):
    demo_env.seed_baseline()
    counts = iter([0, 0, 2])  # non-baseline count, baseline before (0 points), baseline after repair

    def fake_count(label):
        return next(counts)

    monkeypatch.setattr(baseline, "_qdrant_count", fake_count)
    monkeypatch.setattr(baseline, "_ingest_baseline_again", lambda: None)
    result = baseline.reset_to_baseline()
    assert result["baseline"]["repaired"] is True and result["baseline"]["indexed_points"] == 2


def test_reset_blocks_when_the_safety_backup_fails(demo_env, monkeypatch):
    demo_env.seed_baseline()
    _run_scan_sync("run-b")

    def failing():
        raise baseline.backup_mod.BackupError("pg_dump missing")

    monkeypatch.setattr(baseline.backup_mod, "ensure_first_backup", failing)
    with pytest.raises(baseline.DemoResetError, match="backup failed"):
        baseline.reset_to_baseline()
    with demo_env.session() as db:  # nothing was destroyed
        assert db.scalar(select(func.count()).select_from(Action)) == 4


def test_reset_reports_partial_when_the_company_reset_fails(demo_env, monkeypatch):
    demo_env.seed_baseline()
    monkeypatch.setattr(baseline, "_reset_company", lambda: {"status": "failed", "detail": "boom"})
    result = baseline.reset_to_baseline()
    assert result["status"] == "partial" and result["company_reset"]["status"] == "failed"


def test_mirror_status_and_seed_never_lose_the_only_copy(demo_env):
    demo_env.seed_baseline(sources_has_ecc2=True)
    (demo_env.portal / "nca" / ECC2).unlink()  # mirror lacks it, sources has it
    baseline.reset_to_baseline()
    assert (demo_env.portal / "nca" / ECC2).read_bytes() == ECC2_BYTES  # seeded before removal
    assert not (demo_env.sources / "nca" / ECC2).exists()

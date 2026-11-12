"""
`python -m app.demo.prepare` pieces: retry with backoff, the parallel warm-up
loop, that the prompts it warms are exactly the ones run_diff sends, the
approve-then-undo file-edit warm-up, and the pg_dump backup helper.
"""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import diff, llm
from app.db.models import Action, Change, Clause, Regulation, RegulationVersion, Regulator
from app.demo import backup, prepare

from .demo_fixtures import demo_env  # noqa: F401  (fixture)


# ── retry ─────────────────────────────────────────────────────────────────

class RateLimitError(Exception):
    pass


def test_with_retry_backs_off_on_rate_limits_then_succeeds():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RateLimitError("429")
        return "ok"

    assert prepare.with_retry(flaky, sleep=sleeps.append) == "ok"
    assert len(calls) == 3 and len(sleeps) == 2
    assert 2.0 <= sleeps[0] < 3.1 and 4.0 <= sleeps[1] < 5.1  # base * 2^n plus jitter


def test_with_retry_does_not_retry_a_malformed_answer():
    calls = []

    def bad():
        calls.append(1)
        raise ValueError("Model returned an invalid change_type")

    with pytest.raises(ValueError):
        prepare.with_retry(bad, sleep=lambda s: None)
    assert len(calls) == 1


def test_with_retry_gives_up_after_the_last_attempt_and_treats_5xx_as_retryable():
    class Boom(Exception):
        status_code = 503

    with pytest.raises(Boom):
        prepare.with_retry(lambda: (_ for _ in ()).throw(Boom()), attempts=3, sleep=lambda s: None)


def test_warm_parallel_collects_failures_without_stopping():
    def ok():
        return 1

    def bad():
        raise ValueError("nope")

    stats = prepare.warm_parallel("t", [ok, bad, ok, ok], workers=2)
    assert stats.total == 4 and len(stats.latencies) == 3 and len(stats.failed) == 1
    assert "ValueError: nope" in stats.failed[0]
    assert stats.summary()["failed"] == 1


# ── the prompts prepare warms are the ones run_diff sends ─────────────────

def _seed_two_versions(env):
    with Session(env.engine) as db:
        regulator = Regulator(code="nca", name_en="NCA", name_ar="x", weight=1.0)
        db.add(regulator)
        db.flush()
        regulation = Regulation(regulator_id=regulator.id, code="ecc", title_en="ECC", title_ar="x")
        db.add(regulation)
        db.flush()
        v1 = RegulationVersion(regulation_id=regulation.id, version_label="1-2018", file_sha256="a")
        v2 = RegulationVersion(regulation_id=regulation.id, version_label="2-2024", file_sha256="b")
        db.add_all([v1, v2])
        db.flush()
        db.add_all([
            Clause(version_id=v1.id, clause_id="1-1", text_en="Same text.", order_index=0),
            Clause(version_id=v1.id, clause_id="1-2", text_en="Old two.", order_index=1),
            Clause(version_id=v1.id, clause_id="1-3", text_en="Gone.", order_index=2),
            Clause(version_id=v2.id, clause_id="1-1", text_en="Same text.", order_index=0),
            Clause(version_id=v2.id, clause_id="1-2", text_en="New two, stricter.", order_index=1),
            Clause(version_id=v2.id, clause_id="1-4", text_en="Brand new.", order_index=2),
        ])
        db.commit()


def test_classify_inputs_match_what_run_diff_actually_sends(demo_env):
    _seed_two_versions(demo_env)
    vectors = {"1-2": [1.0, 0.0], "1-3": [0.0, 1.0], "1-1": [0.5, 0.5]}
    new_vectors = {"1-2": [1.0, 0.0], "1-4": [0.6, 0.6], "1-1": [0.5, 0.5]}

    def fake_vectors(regulator, regulation, version):
        return vectors if version == "1-2018" else new_vectors

    sent: list[tuple] = []

    def fake_classify(old, new, kind):
        sent.append((old, new, kind))
        return {"change_type": "tightened", "confidence": 0.9, "summary_en": "s", "summary_ar": "ص",
                "effective_date": None, "grace_days": None}

    with patch.object(diff, "get_vectors_for_version", fake_vectors), \
            patch("app.retriever.get_vectors_for_version", fake_vectors), \
            patch.object(diff, "get_engine", lambda: demo_env.engine), \
            patch.object(llm, "classify_change", fake_classify):
        with Session(demo_env.engine) as db:
            planned = prepare.classify_inputs(db, "1-2018", "2-2024")
        diff.run_diff("nca", "ecc", "1-2018", "2-2024", dry_run=False, replace=False)

    assert planned == sent
    assert len(planned) == 3  # identical "1-1" is skipped in both
    assert ("Old two.", "New two, stricter.", "exact_id") in planned


# ── approve then undo (file-edit warm-up) ─────────────────────────────────

class FakeClient:
    def __init__(self, effect_ok=True):
        self.posts: list[str] = []
        self.effect_ok = effect_ok

    def post(self, url):
        self.posts.append(url)
        if url.endswith("/approve"):
            body = {"id": 1, "status": "approved",
                    "effect": {"path": "policies/x.md", "cached": False} if self.effect_ok else None,
                    "effect_note": None if self.effect_ok else "No file effect"}
            return SimpleNamespace(status_code=200, json=lambda: body, text="")
        return SimpleNamespace(status_code=200, json=lambda: {"status": "pending"}, text="")


def _action(env, change_id, action_type, node_name, clause):
    with Session(env.engine) as db:
        db.add(Action(change_id=change_id, type=action_type, level="draft_then_approve", status="pending",
                      payload_json={"impact_node_name": node_name, "clause_id": clause}))
        db.commit()
        return db.scalar(select(Action).order_by(Action.id.desc())).id


def test_warm_company_edits_approves_then_undoes_each_matching_action(demo_env):
    a1 = _action(demo_env, 1, "update_procedure", "Network Security Procedure", "2.5.3.9")
    a2 = _action(demo_env, 1, "update_policy", "Cryptography Policy", "2-8-3-1")
    _action(demo_env, 1, "update_policy", "Cryptography Policy", "2-8-3-2")  # different clause: untouched
    client = FakeClient()
    flows = [
        {"clause": (2, 5, 3, 9), "type": "update_procedure", "node_contains": "Network Security Procedure"},
        {"clause": (2, 8, 3, 1), "type": "update_policy", "node_contains": "Cryptography Policy"},
        {"clause": (2, 5, 3, 9), "type": "technical_change", "node_contains": "ICU-200"},
    ]
    results = prepare.warm_company_edits(flows, client=client)
    assert [r["status"] for r in results] == ["warmed", "warmed", "not_found"]
    assert client.posts == [f"/actions/{a1}/approve", f"/actions/{a1}/undo",
                            f"/actions/{a2}/approve", f"/actions/{a2}/undo"]


def test_warm_company_edits_flags_an_approve_that_produced_no_file_edit(demo_env):
    _action(demo_env, 1, "update_procedure", "Network Security Procedure", "2-5-3-9")
    results = prepare.warm_company_edits(
        [{"clause": (2, 5, 3, 9), "type": "update_procedure", "node_contains": "Network Security Procedure"}],
        client=FakeClient(effect_ok=False),
    )
    assert results[0]["status"] == "failed" and results[0]["note"] == "No file effect"


# ── backup ────────────────────────────────────────────────────────────────

def test_backup_is_skipped_when_one_exists_and_taken_once_otherwise(demo_env, tmp_path):
    with patch("subprocess.run") as run, patch.object(backup.shutil, "which", side_effect=lambda n: n if n == "docker" else None):
        def fake_run(command, env, stdout, stderr, timeout):
            assert command[:4] == ["docker", "exec", "-e", "PGPASSWORD"]
            assert "pg_dump" in command and "--clean" in command
            assert all("=" not in part for part in command)  # the password is never on the command line
            stdout.write(b"-- dump --\n" * 200)
            return subprocess.CompletedProcess(command, 0, b"", b"")

        run.side_effect = fake_run
        first = backup.ensure_first_backup()
        second = backup.ensure_first_backup()
    assert first["status"] == "created" and first["bytes"] > 1024
    assert second["status"] == "exists" and second["path"] == first["path"]
    assert run.call_count == 1


def test_backup_failure_raises_and_leaves_no_partial_file(demo_env, tmp_path):
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, b"", b"pg_dump: error: boom")), \
            patch.object(backup.shutil, "which", side_effect=lambda n: "pg_dump" if n == "pg_dump" else None):
        with pytest.raises(backup.BackupError, match="boom"):
            backup.ensure_first_backup()
    assert backup.existing_backups() == []
    assert not list(backup.backup_dir().glob("*.part"))

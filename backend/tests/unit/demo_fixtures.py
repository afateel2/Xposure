"""Shared fixtures for the demo pipeline tests.

Everything runs on in-memory SQLite (same StaticPool pattern as
test_agent.py) with the graph's model-calling and PDF-ingesting seams
replaced by small fakes, so no Postgres, Qdrant, network or model is needed.
The engine is wired into every module that opens its own session.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import audit, embedding_cache, llm_cache, progress
from app.agent import graph
from app.config import settings
from app.db import session as db_session
from app.db.base import Base
from app.db.models import Change, Clause, Impact, OrgNode, Regulation, RegulationVersion, Regulator
from app.erp import client as erp_client
from app.demo import backup as real_backup
from app.demo import baseline, mirror, tracker

ECC1 = "Essential Cybersecurity Controls (ECC-1-2018).pdf"
ECC2 = "Essential Cybersecurity Controls (ECC-2-2024).pdf"
ECC1_BYTES = b"%PDF-1.4 ecc one"
ECC2_BYTES = b"%PDF-1.4 ecc two"


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


class DemoEnv:
    """Handles to what the fixture built."""

    def __init__(self, engine, sources: Path, portal: Path) -> None:
        self.engine = engine
        self.sources = sources
        self.portal = portal
        self.ingest_calls: list[tuple] = []
        self.model_calls = 0

    def session(self) -> Session:
        return Session(self.engine)

    def seed_baseline(self, sources_has_ecc2: bool = False) -> None:
        with Session(self.engine) as db:
            regulator = Regulator(code="nca", name_en="NCA", name_ar="الهيئة", weight=1.0)
            db.add(regulator)
            db.flush()
            regulation = Regulation(regulator_id=regulator.id, code="ecc", title_en="ECC", title_ar="الضوابط")
            db.add(regulation)
            db.flush()
            version = RegulationVersion(
                regulation_id=regulation.id, version_label="1-2018", file_sha256=mirror.file_sha256(self.sources / "nca" / ECC1)
            )
            db.add(version)
            db.flush()
            db.add_all([
                Clause(version_id=version.id, clause_id="2-5-3", text_en="Old network text.", order_index=0),
                Clause(version_id=version.id, clause_id="2-8-3-1", text_en="Old crypto text.", order_index=1),
            ])
            db.add(OrgNode(type="control_mapping", name="ECC 2-5-3", attrs_json={"control_id": "2-5-3"}))
            db.commit()
        if sources_has_ecc2:
            (self.sources / "nca" / ECC2).write_bytes(ECC2_BYTES)


@pytest.fixture()
def demo_env(tmp_path, monkeypatch):
    engine = make_engine()
    sources = tmp_path / "sources"
    portal = tmp_path / "portal_mirror"
    (sources / "nca").mkdir(parents=True)
    (portal / "nca").mkdir(parents=True)
    (sources / "nca" / ECC1).write_bytes(ECC1_BYTES)
    (portal / "nca" / ECC1).write_bytes(ECC1_BYTES)
    (portal / "nca" / ECC2).write_bytes(ECC2_BYTES)
    env = DemoEnv(engine, sources, portal)

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "demo_stage_pacing_ms", 0)
    monkeypatch.setattr(settings, "demo_backup_dir", str(tmp_path / "backups"))
    monkeypatch.setattr(graph, "SOURCES_DIR", sources)
    monkeypatch.setattr(mirror, "MIRROR_DIR", portal)
    monkeypatch.setattr(embedding_cache, "CACHE_DIR", tmp_path / "emb")

    def _offline(request):  # a test must never reach a real Odoo, whatever .env says
        raise httpx.ConnectError("offline in tests", request=request)

    monkeypatch.setattr(erp_client, "TRANSPORT", httpx.MockTransport(_offline))

    patches = [
        patch.object(db_session, "get_engine", lambda: engine),
        patch.object(graph, "get_engine", lambda: engine),
        patch.object(audit, "get_engine", lambda: engine),
        patch.object(llm_cache, "get_engine", lambda: engine),
    ]
    for p in patches:
        p.start()

    # ---- fakes for the graph's heavy seams ----
    def fake_ingest(regulator, regulation, label, path, code_before_text=False, replace=False):
        env.ingest_calls.append((regulator, regulation, label, Path(path).name, replace))
        with Session(engine) as db:
            reg = db.scalar(select(Regulation))
            if replace:
                old = db.scalar(select(RegulationVersion).where(RegulationVersion.version_label == label))
                if old:
                    for c in db.scalars(select(Clause).where(Clause.version_id == old.id)):
                        db.delete(c)
                    db.delete(old)
                    db.flush()
            version = RegulationVersion(
                regulation_id=reg.id, version_label=label, file_sha256=mirror.file_sha256(Path(path))
            )
            db.add(version)
            db.flush()
            db.add_all([
                Clause(version_id=version.id, clause_id="2-5-3", text_en="New network text.", order_index=0),
                Clause(version_id=version.id, clause_id="2-8-3-1", text_en="New crypto text.", order_index=1),
                Clause(version_id=version.id, clause_id="2-5-3-9", text_en="DDoS protection.", order_index=2),
            ])
            db.commit()

    def fake_run_diff(regulator, regulation, from_label, to_label, dry_run=False, replace=False):
        with Session(engine) as db:
            reg = db.scalar(select(Regulation))
            versions = {v.version_label: v for v in db.scalars(select(RegulationVersion))}
            pairs = [("2-5-3", "2-5-3", "exact_id", "tightened", True),
                     ("2-8-3-1", "2-8-3-1", "exact_id", "editorial", False),
                     (None, "2-5-3-9", "new", "new_obligation", True)]
            progress.emit(
                "diff.aligned", from_label=from_label, to_label=to_label, from_clauses=2, to_clauses=3,
                pairs=3, match_counts={"exact_id": 2, "renumbered_candidate": 0, "new": 1, "withdrawn": 0},
                identical=0, to_classify=len(pairs), dry_run=False,
            )
            for i, (old, new, kind, ctype, material) in enumerate(pairs, 1):
                key = llm_cache.make_key("classify", "test-model", [{"role": "user", "content": f"{old}->{new}"}], {})
                answer = llm_cache.lookup("classify", key)
                if answer is None:
                    env.model_calls += 1
                    answer = {"change_type": ctype}
                    llm_cache.store("classify", key, "test-model", answer)
                db.add(Change(
                    regulation_id=reg.id, from_version_id=versions[from_label].id, to_version_id=versions[to_label].id,
                    old_clause_id=old, new_clause_id=new, match_kind=kind, change_type=answer["change_type"],
                    material=material, confidence=0.9, summary_en="s", summary_ar="ص",
                    effective_date=date(2027, 1, 1) if material else None,
                ))
                progress.emit("diff.classified", done=i, total=len(pairs), change_type=ctype,
                              old_clause_id=old, new_clause_id=new)
            db.commit()
            progress.emit("diff.stored", changes=len(pairs), material=2)

    def fake_compute_impact(db, change):
        # The cache opens its own Session, and on this single shared SQLite
        # connection closing it rolls back whatever the caller had flushed
        # but not committed. Postgres gives every Session its own connection,
        # so the real path has no such interaction; commit first here.
        db.commit()
        node = db.scalar(select(OrgNode).where(OrgNode.type == "control_mapping"))
        key = llm_cache.make_key("impact", "test-model", [{"role": "user", "content": str(change.id)}], {})
        if llm_cache.lookup("impact", key) is None:
            env.model_calls += 1
            llm_cache.store("impact", key, "test-model", {"note_en": "n"})
        row = Impact(change_id=change.id, node_id=node.id, path_json={}, note_en="n", note_ar="ن",
                     recommended_actions_json=["update_policy", "notify_owner"])
        db.add(row)
        db.flush()
        return [row]

    monkeypatch.setattr(graph, "_load_ingest", lambda: fake_ingest)
    monkeypatch.setattr(graph, "_load_run_diff", lambda: fake_run_diff)
    monkeypatch.setattr(graph, "_load_compute_impact", lambda: fake_compute_impact)
    monkeypatch.setattr(graph, "_load_explain_priority", lambda: (lambda change, n, days, regulator_weight=1.0: {"score": 60, "band": "medium"}))
    monkeypatch.setattr(
        graph, "_load_explain_automation",
        lambda: (lambda action_type, change_type, confidence: {
            "level": "auto_execute" if action_type == "notify_owner" else "draft_then_approve",
            "requested": "auto_execute" if action_type == "notify_owner" else "draft_then_approve",
            "gates": [],
        }),
    )

    @contextmanager
    def fake_checkpointer():
        yield InMemorySaver()

    monkeypatch.setattr(graph, "checkpointer", fake_checkpointer)

    # ---- reset seams ----
    monkeypatch.setattr(baseline, "_qdrant_count", lambda label: 2 if label == "1-2018" else 3)
    monkeypatch.setattr(baseline, "_qdrant_delete", lambda label: None)
    monkeypatch.setattr(baseline, "_clear_checkpoints", lambda: 1)
    monkeypatch.setattr(baseline, "_load_org_fragment", lambda: object())
    monkeypatch.setattr(baseline, "_persist_org", lambda db, fragment: (1, 0))
    monkeypatch.setattr(baseline, "_reset_company", lambda: {"status": "done", "detail": {"files": 8}})
    monkeypatch.setattr(
        baseline, "backup_mod",
        SimpleNamespace(
            ensure_first_backup=lambda: {"status": "exists", "path": "x.sql", "bytes": 2048},
            BackupError=real_backup.BackupError,
        ),
    )

    tracker.TRACKER.reset()
    tracker.TRACKER._reset_seen = 0
    llm_cache.reset_stats()
    try:
        yield env
    finally:
        progress.set_listener(None)
        tracker.TRACKER.reset()
        for p in patches:
            p.stop()
        engine.dispose()

"""
The demo reset: put the system back to "the company is compliant with
ECC-1:2018 and nothing else has happened".

BASELINE means:
  - regulator nca, regulation ecc, ONLY version 1-2018 ingested (clause rows
    in Postgres and points in Qdrant for 1-2018 only)
  - the ECC-2:2024 PDF is not in backend/data/sources/ (it lives in the
    portal mirror, backend/data/portal_mirror/)
  - the org graph is (re)loaded from data/org/demo_org.yaml
  - no Change, Impact or Action rows
  - the LangGraph checkpoints are cleared (a paused human-review thread from
    an earlier run would reference actions that no longer exist)
  - the company workspace is restored from its baseline (app.company.store)
  - the Odoo tasks Xposure created are deleted (best effort, app/demo/erp_cleanup.py)
  - one `demo_reset` audit event is appended

audit_log rows are NEVER deleted. The activity feed filters by "since the
last demo_reset". The first destructive reset on a machine takes a pg_dump
backup first (app/demo/backup.py) and is blocked if that fails.

Order matters: everything that can be validated is validated before the
first row is deleted (the org yaml is parsed and checked up front), and all
the Postgres changes happen in ONE transaction, so a failure rolls back
instead of leaving half a reset. Qdrant, file and checkpoint cleanup follow
the commit and are idempotent, so running reset again always converges.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import session as db_session
from ..db.models import Action, Change, Clause, Impact, Regulation, RegulationVersion, Regulator
from . import backup as backup_mod
from . import constants as C
from . import erp_cleanup, mirror
from .tracker import TRACKER, DemoConflict

_RESET_LOCK = threading.Lock()


class DemoResetError(RuntimeError):
    pass


# ── Small seams (patched in tests) ────────────────────────────────────────

def _load_org_fragment():
    """Parse and validate the org yaml BEFORE anything is deleted."""
    from ..adapters.org import validate_fragment
    from ..impact import DEFAULT_ORG_FILE, parse_org_yaml

    fragment = parse_org_yaml(DEFAULT_ORG_FILE)
    validate_fragment(fragment, source=str(DEFAULT_ORG_FILE))
    return fragment


def _persist_org(db: Session, fragment) -> tuple[int, int]:
    from ..impact import persist_org_graph

    return persist_org_graph(db, fragment, replace=True)


def _qdrant_count(version_label: str) -> int:
    from .. import retriever

    return retriever.count_indexed(C.BASELINE_REGULATOR, C.BASELINE_REGULATION, version_label)


def _qdrant_delete(version_label: str) -> None:
    from ..ingest import _delete_qdrant_version

    _delete_qdrant_version(C.BASELINE_REGULATOR, C.BASELINE_REGULATION, version_label)


def _ingest_baseline_again() -> None:
    from ..agent import graph

    known = next(
        (k for k in graph.KNOWN_SOURCES.values()
         if k.regulator_code == C.BASELINE_REGULATOR and k.regulation_code == C.BASELINE_REGULATION
         and k.version_label == C.BASELINE_VERSION),
        None,
    )
    if known is None:
        raise DemoResetError(f"No known source is configured for the baseline version {C.BASELINE_VERSION}.")
    path = graph.SOURCES_DIR / C.BASELINE_REGULATOR / known.filename
    if not path.is_file():
        mirror_copy = mirror.MIRROR_DIR / C.BASELINE_REGULATOR / known.filename
        if not mirror_copy.is_file():
            raise DemoResetError(
                f"The baseline document {known.filename} is in neither backend/data/sources/ nor the portal mirror."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(mirror_copy.read_bytes())
    graph._load_ingest()(
        known.regulator_code, known.regulation_code, known.version_label, path,
        code_before_text=known.code_before_text, replace=True,
    )


def _clear_checkpoints() -> int:
    """Delete every LangGraph thread. Returns how many threads were cleared.
    Zero (not an error) when the checkpoint tables do not exist."""
    with Session(db_session.get_engine()) as db:
        try:
            thread_ids = [row[0] for row in db.execute(text("SELECT DISTINCT thread_id FROM checkpoints"))]
        except Exception:
            return 0
    if not thread_ids:
        return 0
    from ..agent import graph

    with graph.checkpointer() as saver:
        for thread_id in thread_ids:
            saver.delete_thread(thread_id)
    return len(thread_ids)


def _clear_erp(task_ids: list[int]) -> dict[str, Any]:
    """Delete the Odoo tasks Xposure created. Never raises (seam for tests)."""
    try:
        return erp_cleanup.clear_erp_tasks(task_ids)
    except Exception as exc:  # belt and braces: clear_erp_tasks already swallows everything
        return {"deleted": 0, "referenced": len(task_ids), "skipped_reason": f"{type(exc).__name__}: {exc}"}


def _reset_company() -> dict[str, Any]:
    """Restore the company workspace, if that package exists (another agent
    builds it; its absence must not break the reset)."""
    try:
        from ..company import store
    except ImportError:
        return {"status": "unavailable", "detail": "app.company is not installed"}
    reset = getattr(store, "reset_company", None)
    if reset is None:
        return {"status": "unavailable", "detail": "app.company.store.reset_company does not exist"}
    try:
        return {"status": "done", "detail": reset()}
    except Exception as exc:
        return {"status": "failed", "detail": f"{type(exc).__name__}: {exc}"}


# ── The reset ─────────────────────────────────────────────────────────────

def _baseline_state(db: Session) -> dict[str, Any]:
    from ..agent import graph

    version = graph._find_version(db, C.BASELINE_REGULATOR, C.BASELINE_REGULATION, C.BASELINE_VERSION)
    clauses = (
        db.scalar(select(func.count()).select_from(Clause).where(Clause.version_id == version.id))
        if version else 0
    )
    return {"present": version is not None, "clauses": int(clauses or 0)}


def reset_to_baseline(*, source: str = "api", actor: str = C.ACTOR_USER) -> dict[str, Any]:
    if not settings.demo_mode:
        raise DemoConflict("Demo mode is off (DEMO_MODE=false): the reset is disabled.")
    if not _RESET_LOCK.acquire(blocking=False):
        raise DemoConflict("A reset is already in progress.")
    try:
        return _reset_locked(source, actor)
    finally:
        _RESET_LOCK.release()


def _reset_locked(source: str, actor: str) -> dict[str, Any]:
    if TRACKER.is_running():
        raise DemoConflict("A scan is running. Wait for it to finish before resetting.")
    started = time.monotonic()

    # 1. Everything that can fail cheaply, before anything is destroyed.
    fragment = _load_org_fragment()
    try:
        backup = backup_mod.ensure_first_backup()
    except backup_mod.BackupError as exc:
        raise DemoResetError(f"Reset blocked: the one-time safety backup failed. {exc}") from exc
    mirror.seed_mirror()  # the mirror must hold every recognised source before we remove any from sources/

    from ..agent import graph

    non_baseline_labels = sorted(
        {k.version_label for k in graph.KNOWN_SOURCES.values()
         if k.regulator_code == C.BASELINE_REGULATOR and k.regulation_code == C.BASELINE_REGULATION
         and k.version_label != C.BASELINE_VERSION}
    )

    # 2. All Postgres changes in one transaction.
    cleared: dict[str, Any] = {}
    qdrant_before: dict[str, int] = {}
    for label in non_baseline_labels:
        qdrant_before[label] = _qdrant_count(label)
    with Session(db_session.get_engine()) as db:
        # Odoo task ids must be read BEFORE the actions that carry them are deleted.
        erp_task_ids = erp_cleanup.collect_task_ids(db)
        cleared["actions"] = int(db.scalar(select(func.count()).select_from(Action)) or 0)
        cleared["impacts"] = int(db.scalar(select(func.count()).select_from(Impact)) or 0)
        cleared["changes"] = int(db.scalar(select(func.count()).select_from(Change)) or 0)
        db.execute(delete(Action))
        db.execute(delete(Impact))
        db.execute(delete(Change))

        regulation = db.scalar(
            select(Regulation).join(Regulator).where(
                Regulator.code == C.BASELINE_REGULATOR, Regulation.code == C.BASELINE_REGULATION
            )
        )
        removed_versions: list[str] = []
        clauses_removed = 0
        if regulation is not None:
            extra = list(db.scalars(
                select(RegulationVersion).where(
                    RegulationVersion.regulation_id == regulation.id,
                    RegulationVersion.version_label != C.BASELINE_VERSION,
                )
            ))
            for version in extra:
                clauses_removed += int(
                    db.scalar(select(func.count()).select_from(Clause).where(Clause.version_id == version.id)) or 0
                )
                db.execute(delete(Clause).where(Clause.version_id == version.id))
                db.execute(delete(RegulationVersion).where(RegulationVersion.id == version.id))
                removed_versions.append(version.version_label)
        cleared["versions_removed"] = sorted(removed_versions)
        cleared["clauses_removed"] = clauses_removed

        node_count, edge_count = _persist_org(db, fragment)
        db.commit()

    # 3. Idempotent cleanup outside Postgres.
    for label in sorted(set(non_baseline_labels) | set(removed_versions)):
        _qdrant_delete(label)
    cleared["qdrant_points_removed"] = sum(qdrant_before.values())
    cleared["source_files_removed"] = mirror.remove_non_baseline_sources(C.BASELINE_VERSION)
    cleared["checkpoint_threads"] = _clear_checkpoints()
    # Best effort and time capped: never fails or meaningfully slows the reset.
    erp_cleared = _clear_erp(erp_task_ids)

    # 4. Verify the baseline version is really there and indexed; repair if not.
    repaired = False
    with Session(db_session.get_engine()) as db:
        state = _baseline_state(db)
    indexed = _qdrant_count(C.BASELINE_VERSION)
    if not state["present"] or state["clauses"] == 0 or indexed != state["clauses"]:
        _ingest_baseline_again()
        repaired = True
        with Session(db_session.get_engine()) as db:
            state = _baseline_state(db)
        indexed = _qdrant_count(C.BASELINE_VERSION)
    if not state["present"] or indexed != state["clauses"]:
        raise DemoResetError(
            f"Baseline check failed after the reset: version {C.BASELINE_VERSION} has {state['clauses']} clause "
            f"rows and {indexed} indexed points."
        )

    # 5. Company workspace, then the audit event, then the in-memory run state.
    company = _reset_company()
    took_ms = int((time.monotonic() - started) * 1000)
    result = {
        "status": "ok" if company["status"] != "failed" else "partial",
        "phase": "baseline",
        "demo_mode": True,
        "took_ms": took_ms,
        "cleared": cleared,
        "baseline": {
            "regulation_versions": [C.BASELINE_VERSION],
            "clauses": state["clauses"],
            "indexed_points": indexed,
            "repaired": repaired,
        },
        "org": {"nodes": node_count, "edges": edge_count},
        "company_reset": company,
        "erp_cleared": erp_cleared,
        "backup": backup,
    }
    audit.record_in_new_session(
        actor=actor, event=C.EVT_DEMO_RESET, ref_type="demo",
        payload={"source": source, **{k: v for k, v in result.items() if k != "demo_mode"}},
    )
    TRACKER.reset()
    return result

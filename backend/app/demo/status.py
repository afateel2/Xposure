"""GET /demo/status: where the demo is right now."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import llm_cache
from ..config import settings
from ..db.models import Action, AuditLog, Clause, Regulation, RegulationVersion, Regulator
from . import constants as C
from . import mirror
from .tracker import TRACKER


def compute_status(db: Session) -> dict[str, Any]:
    run = TRACKER.snapshot()
    rows = db.execute(
        select(Regulator.code, Regulation.code, RegulationVersion)
        .join(Regulation, Regulation.regulator_id == Regulator.id)
        .join(RegulationVersion, RegulationVersion.regulation_id == Regulation.id)
        .order_by(Regulator.code, Regulation.code, RegulationVersion.version_label)
    ).all()
    counts = dict(db.execute(select(Clause.version_id, func.count()).group_by(Clause.version_id)).all())
    versions = [
        {
            "regulator": rc, "regulation": gc, "version_label": v.version_label,
            "clause_count": int(counts.get(v.id, 0)), "file_sha256": v.file_sha256,
            "ingested_at": v.ingested_at.isoformat() if v.ingested_at else None,
        }
        for rc, gc, v in rows
    ]
    has_new_version = any(v["version_label"] != C.BASELINE_VERSION for v in versions)
    total_actions = int(db.scalar(select(func.count()).select_from(Action)) or 0)
    pending_actions = int(db.scalar(select(func.count()).select_from(Action).where(Action.status == "pending")) or 0)

    scanning = run["status"] == "running"
    if scanning:
        phase = "scanning"
    elif has_new_version and total_actions > 0:
        phase = "review_ready"
    else:
        phase = "baseline"
    # An interrupted or failed run can leave a new version without actions: not a
    # state to scan from, the reset restores a clean start.
    needs_reset = (not scanning) and ((has_new_version and total_actions == 0) or run["status"] == "failed")

    last_reset = db.scalar(select(AuditLog.ts).where(AuditLog.event == C.EVT_DEMO_RESET).order_by(AuditLog.id.desc()).limit(1))
    portal = [
        {k: d.as_dict()[k] for k in ("path", "filename", "version_label", "size_bytes", "status")}
        for d in mirror.list_portal(db)
    ]
    return {
        "phase": phase,
        "demo_mode": bool(settings.demo_mode),
        "regulation_versions": versions,
        "run_status": run["status"],
        "run_id": run["run_id"],
        "pending_actions": pending_actions,
        "total_actions": total_actions,
        "needs_reset": needs_reset,
        "can_scan": bool(settings.demo_mode) and not scanning,
        "can_reset": bool(settings.demo_mode) and not scanning,
        "last_reset_at": last_reset.isoformat() + "Z" if last_reset else None,
        "portal": {
            "simulated": True,
            "note_en": C.SIMULATED_PORTAL_NOTE_EN,
            "note_ar": C.SIMULATED_PORTAL_NOTE_AR,
            "documents": portal,
            "new_available": sum(1 for d in portal if d["status"] == "new"),
        },
        "stage_pacing_ms": int(settings.demo_stage_pacing_ms) if settings.demo_mode else 0,
        "llm_cache": {"enabled": bool(settings.demo_mode), "entries": llm_cache.count_entries()},
    }

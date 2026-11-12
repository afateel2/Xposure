"""GET /sources — every ingested regulation_version, for M7's Sources screen.

POST /sources/check-live and GET /sources/check-live/last:
a real, on-demand check against the regulator's own public page (see
app/watcher.py's module docstring for exactly what this does and does not
do). Gated behind login (app/auth.py) because it is a deliberate action
that makes a real outbound request to a third party, not a passive read;
it is never scheduled by this code."""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, watcher
from ..auth import require_user
from ..db.models import AppUser, Clause, Regulation, RegulationVersion, Regulator
from ..db.session import get_db
from .schemas import RegulationOut, RegulatorOut, SourceVersionOut

router = APIRouter(tags=["sources"])


@router.get("/sources", response_model=list[SourceVersionOut])
def list_sources(db: Session = Depends(get_db)):
    rows = db.execute(
        select(RegulationVersion, Regulation, Regulator)
        .join(Regulation, RegulationVersion.regulation_id == Regulation.id)
        .join(Regulator, Regulation.regulator_id == Regulator.id)
        .order_by(Regulator.code, Regulation.code, RegulationVersion.version_label)
    ).all()

    clause_counts = dict(
        db.execute(select(Clause.version_id, func.count()).group_by(Clause.version_id)).all()
    )

    return [
        SourceVersionOut(
            regulator=RegulatorOut(code=regulator.code, name_en=regulator.name_en, name_ar=regulator.name_ar),
            regulation=RegulationOut(code=regulation.code, title_en=regulation.title_en, title_ar=regulation.title_ar),
            version_label=version.version_label,
            published_at=version.published_at,
            effective_at=version.effective_at,
            source_url=version.source_url,
            file_sha256=version.file_sha256,
            ingested_at=version.ingested_at,
            clause_count=clause_counts.get(version.id, 0),
            has_live_check=(regulator.code, regulation.code) in watcher.WATCH_TARGETS,
        )
        for version, regulation, regulator in rows
    ]


# ── Live portal check ──────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 600  # repeated UI loads within 10 minutes reuse the last real check
_last_results: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _watcher_http_error(exc: watcher.WatcherError) -> HTTPException:
    status = {
        "timeout": 504, "unreachable": 503, "bad_status": 502,
        "unrecognized_page": 502, "pdf_unreachable": 502,
    }.get(exc.kind, 502)
    return HTTPException(status_code=status, detail=exc.combined)


@router.post("/sources/check-live")
def check_live_portal(
    regulator: str, regulation: str, db: Session = Depends(get_db), user: AppUser = Depends(require_user)
) -> dict[str, Any]:
    target = watcher.WATCH_TARGETS.get((regulator, regulation))
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No live watcher is configured for {regulator}/{regulation} yet. | "
                f"لا توجد آلية فحص مباشر لهذه الجهة أو اللائحة بعد."
            ),
        )

    cached = _last_results.get((regulator, regulation))
    if cached is not None and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
        return {**cached[1], "from_cache": True}

    try:
        result = watcher.check_live(db, target)
    except watcher.WatcherError as exc:
        audit.record(
            db, actor=user.actor(), event="live_portal_check_failed", ref_type="regulation",
            payload={"regulator": regulator, "regulation": regulation, "kind": exc.kind, "reason": exc.message_en},
        )
        raise _watcher_http_error(exc) from exc

    _last_results[(regulator, regulation)] = (time.monotonic(), result)
    audit.record(db, actor=user.actor(), event="live_portal_checked", ref_type="regulation", payload=result)
    return {**result, "from_cache": False}


@router.get("/sources/check-live/last")
def last_live_check(regulator: str = Query(...), regulation: str = Query(...)) -> dict[str, Any]:
    """The last real check this process made, if any — never triggers a new
    one, so a plain page load never makes an outbound request by itself."""
    cached = _last_results.get((regulator, regulation))
    if cached is None:
        return {"checked": False}
    return {"checked": True, **cached[1]}

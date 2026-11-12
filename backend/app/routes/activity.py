"""
Visibility API, part 2 (mounted by routes/overview.py):

  GET /activity                    human-readable, newest-first feed
  GET /audit, /audit/events, /audit/actors    raw-but-readable audit log
  GET /agent/state                 idle | scanning | awaiting_review | failed
  GET /changes/{id}/timeline       ordered history of one change and its actions

Everything is derived from audit_log and real rows, read-only. audit_log is
append-only by design: nothing here (or anywhere) updates or deletes a row.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db.models import Action, AuditLog, Change, Regulation, Regulator, RegulationVersion
from ..db.session import get_db
from ..visibility import labels as L
from ..visibility.agent_state import compute_agent_state
from ..visibility.events import (
    KIND_ICON, NOISE_EVENTS, Desc, Ev, build_ctx, build_feed, describe, event_kind, event_label,
)
from ..visibility.labels import isolate
from ..visibility.schemas import (
    ActivityOut, AgentStateOut, AuditActorsOut, AuditEventsOut, AuditOut, TimelineOut,
)
from ..visibility.timeutil import as_utc, parse_iso, to_naive_utc
from ..visibility.window import get_window

router = APIRouter(tags=["visibility"])

# Upper bound on raw audit rows read per /activity call. Collapsing happens on
# these, so a page never splits a group unless the window really is this big.
MAX_RAW_ROWS = 5000


# ── GET /activity ─────────────────────────────────────────────────────────

@router.get("/activity", response_model=ActivityOut)
def get_activity(
    limit: int = Query(50, ge=1, le=200),
    since_reset: bool = Query(True, description="Start at the last demo_reset (when one exists)."),
    before_id: int | None = Query(None, description="Pagination cursor: return entries older than this audit id (use next_before_id from the previous page)."),
    kind: str | None = Query(None, description="Comma separated kinds to keep (scan, ingest, diff, classify, impact, action, delegate, confirm, undo, export, system, effect)."),
    include_stages: bool = Query(False, description="Also show stage_completed rows and stage_started rows that already completed (hidden by default: the domain events beside them say the same thing)."),
    db: Session = Depends(get_db),
):
    """Newest-first activity feed. Noisy repeats are collapsed (43 action_created
    rows of one run become one entry, `count` = 43); node-completion bookkeeping,
    webhooks that never left the process and per-action rows of a bulk decision
    are hidden (they remain visible in /audit)."""
    window = get_window(db, since_reset)
    stmt = select(AuditLog)
    if window.active and window.reset_id is not None:
        stmt = stmt.where(AuditLog.id >= window.reset_id)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    rows = list(db.scalars(stmt.order_by(AuditLog.id.desc()).limit(MAX_RAW_ROWS)))
    raw_capped = len(rows) >= MAX_RAW_ROWS
    evs = [Ev.from_row(r) for r in reversed(rows)]  # ascending
    ctx = build_ctx(db, evs, with_status_after=True)
    entries = build_feed(evs, ctx, include_stages=include_stages)
    entries.reverse()  # newest first
    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        entries = [e for e in entries if e["kind"] in wanted]

    page = entries[:limit]
    more = len(entries) > limit or (raw_capped and bool(page))
    for e in page:
        e["ts"], e["ts_start"] = as_utc(e["ts"]), as_utc(e["ts_start"])
    return {
        "items": page,
        "next_before_id": page[-1]["first_id"] if page and more else None,
        "window": {"since_reset": window.active, "reset_at": as_utc(window.reset_at)},
    }


# ── GET /audit ────────────────────────────────────────────────────────────

def _audit_filters(stmt, event: str | None, actor: str | None, since: datetime | None, ref_type: str | None,
                   ref_id: int | None, reset_id: int | None):
    if event:
        names = [e.strip() for e in event.split(",") if e.strip()]
        stmt = stmt.where(AuditLog.event.in_(names))
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if since is not None:
        stmt = stmt.where(AuditLog.ts >= since)
    if ref_type:
        stmt = stmt.where(AuditLog.ref_type == ref_type)
    if ref_id is not None:
        stmt = stmt.where(AuditLog.ref_id == ref_id)
    if reset_id is not None:
        stmt = stmt.where(AuditLog.id >= reset_id)
    return stmt


@router.get("/audit", response_model=AuditOut)
def list_audit(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event: str | None = Query(None, description="Event name, or several separated by commas."),
    actor: str | None = Query(None, description="Exact actor, for example user:web or agent:diff_node."),
    since: str | None = Query(None, description="ISO-8601 timestamp: only rows at or after it."),
    ref_type: str | None = Query(None, description="For example action, change, regulation_version."),
    ref_id: int | None = Query(None),
    since_reset: bool = Query(False, description="Start at the last demo_reset. Off by default: the audit page shows full history."),
    include_payload: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Paginated audit log, newest first, each row with a bilingual one-line summary."""
    since_dt = None
    if since:
        try:
            since_dt = to_naive_utc(parse_iso(since))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"`since` must be an ISO-8601 timestamp, got {since!r}.") from None
    window = get_window(db, since_reset)
    reset_id = window.reset_id if window.active else None

    base = _audit_filters(select(AuditLog), event, actor, since_dt, ref_type, ref_id, reset_id)
    total = db.scalar(_audit_filters(select(func.count()).select_from(AuditLog), event, actor, since_dt, ref_type, ref_id, reset_id)) or 0
    rows = list(db.scalars(base.order_by(AuditLog.id.desc()).offset(offset).limit(limit)))
    evs = [Ev.from_row(r) for r in rows]
    ctx = build_ctx(db, evs, with_status_after=True)
    items = []
    for r, ev in zip(rows, evs):
        d = describe(ev, ctx)
        items.append({
            "id": r.id, "ts": as_utc(r.ts), "actor": r.actor, "event": r.event, "ref_type": r.ref_type or "",
            "ref_id": r.ref_id, "kind": d.kind, "severity": d.severity, "icon": d.icon,
            "summary_en": d.en, "summary_ar": d.ar,
            "payload": (r.payload_json if isinstance(r.payload_json, dict) else {}) if include_payload else None,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/audit/events", response_model=AuditEventsOut)
def list_audit_events(db: Session = Depends(get_db)):
    """Distinct event names with counts and bilingual labels, for a filter dropdown."""
    rows = db.execute(select(AuditLog.event, func.count()).group_by(AuditLog.event).order_by(AuditLog.event)).all()
    events = []
    for name, count in rows:
        label_en, label_ar = event_label(name)
        events.append({"event": name, "count": count, "kind": event_kind(name), "label_en": label_en, "label_ar": label_ar})
    return {"events": events}


@router.get("/audit/actors", response_model=AuditActorsOut)
def list_audit_actors(db: Session = Depends(get_db)):
    """Distinct actors with counts, for a filter dropdown."""
    rows = db.execute(select(AuditLog.actor, func.count()).group_by(AuditLog.actor).order_by(AuditLog.actor)).all()
    return {"actors": [{"actor": a, "count": c} for a, c in rows]}


# ── GET /agent/state ──────────────────────────────────────────────────────

@router.get("/agent/state", response_model=AgentStateOut)
def get_agent_state(db: Session = Depends(get_db)):
    """What the agent is doing right now, derived from audit events (scan_requested,
    stage_*, scan_completed, scan_failed, run_*, human_review_*) since the last demo reset."""
    return compute_agent_state(db)


# ── GET /changes/{id}/timeline ────────────────────────────────────────────

def _detected_text(change: Change, reg_label: str, from_label: str | None, to_label: str | None) -> tuple[str, str]:
    clause = change.new_clause_id or change.old_clause_id or "?"
    a, b = from_label or "?", to_label or "?"
    if change.match_kind == "new":
        return (f"New clause {clause} found in {reg_label} {b}",
                f"تم رصد بند جديد {isolate(clause)} في {isolate(f'{reg_label} {b}')}")
    if change.match_kind == "withdrawn":
        return (f"Clause {clause} is no longer present in {reg_label} {b}",
                f"البند {isolate(clause)} لم يعد موجودًا في {isolate(f'{reg_label} {b}')}")
    return (f"Clause {clause} differs between {reg_label} {a} and {b}",
            f"تم رصد اختلاف في البند {isolate(clause)} بين {isolate(f'{reg_label} {a}')} و{isolate(b)}")


@router.get("/changes/{change_id}/timeline", response_model=TimelineOut)
def get_change_timeline(change_id: int, db: Session = Depends(get_db)):
    """Chronological history of one change: detected, classified, impact traced,
    priority computed, then every action step (created, approved, dismissed,
    delegated, confirmed, undone, agent edit applied or reverted, ERP task events).

    The first two items come from the change row itself (its created_at); the
    rest come from audit_log. Nothing is invented: a step with no audit row and
    no table row does not appear."""
    change = db.get(Change, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail=f"No change with id {change_id}.")
    regulation = db.get(Regulation, change.regulation_id)
    regulator = db.get(Regulator, regulation.regulator_id) if regulation else None
    from_v = db.get(RegulationVersion, change.from_version_id)
    to_v = db.get(RegulationVersion, change.to_version_id)
    reg_label = " ".join(x for x in ((regulator.code.upper() if regulator else ""), (regulation.code.upper() if regulation else "")) if x)

    actions = list(db.scalars(select(Action).where(Action.change_id == change_id).order_by(Action.id)))
    action_ids = [a.id for a in actions]
    cond = (AuditLog.ref_type == "change") & (AuditLog.ref_id == change_id)
    if action_ids:
        cond = or_(cond, (AuditLog.ref_type == "action") & (AuditLog.ref_id.in_(action_ids)))
    rows = list(db.scalars(select(AuditLog).where(cond).order_by(AuditLog.id)))
    evs = [Ev.from_row(r) for r in rows]
    ctx = build_ctx(db, evs, extra_change_ids=[change_id], with_status_after="all")

    items: list[tuple[tuple, dict]] = []

    def add(sort_key, ts, d, *, actor, action_id, event, audit_id, status_after=None):
        items.append((sort_key, {
            "ts": as_utc(ts), "kind": d.kind, "severity": d.severity, "icon": d.icon, "text_en": d.en, "text_ar": d.ar,
            "detail_en": d.detail_en, "detail_ar": d.detail_ar, "actor": actor, "action_id": action_id,
            "event": event, "audit_id": audit_id, "status_after": status_after,
        }))

    # 1. facts from the change row itself
    en, ar = _detected_text(change, reg_label, from_v.version_label if from_v else None, to_v.version_label if to_v else None)
    add((change.created_at, 0, 0), change.created_at,
        Desc("diff", "info", "git-compare", en, ar), actor=None, action_id=None, event="change_detected", audit_id=None)
    if change.change_type is None:
        cls = Desc("classify", "warning", "tags", "Not classified yet", "لم يُصنَّف بعد")
    else:
        t_en, t_ar = L.CHANGE_TYPE_LABEL.get(change.change_type, (change.change_type, isolate(change.change_type)))
        pct = f"{round(change.confidence * 100)}%" if change.confidence is not None else None
        c_en = f"Classified as {t_en}" + (f" with {pct} confidence" if pct else "")
        c_ar = f"صُنّف التغيير: {t_ar}" + (f" بدرجة ثقة {pct}" if pct else "")
        if change.material is False:
            c_en += " (not material: no alert generated)"
            c_ar += " (غير جوهري: لا يُنشأ له تنبيه)"
        cls = Desc("classify", "info", "tags", c_en, c_ar)
    add((change.created_at, 0, 1), change.created_at, cls, actor=None, action_id=None, event="change_classified", audit_id=None)

    # 2. audit rows about the change and its actions
    created_logged = {ev.ref_id for ev in evs if ev.event == "action_created" and ev.ref_type == "action"}
    for ev in evs:
        if ev.event in NOISE_EVENTS:
            continue
        if ev.event.startswith("webhook_") and not ev.event.startswith("webhook_received") and ev.p.get("sent") is not True:
            continue
        d = describe(ev, ctx)
        after = ctx.status_after.get(ev.id) or ("pending" if ev.event == "action_created" else None)
        add((ev.ts, 1, ev.id), ev.ts, d, actor=ev.actor, action_id=d.action_id or (ev.ref_id if ev.ref_type == "action" else None),
            event=ev.event, audit_id=ev.id, status_after=after)

    # 3. actions that exist but have no action_created audit row (created outside the pipeline)
    for a in actions:
        if a.id in created_logged:
            continue
        en_l, ar_l = L.action_type_label(a.type)
        payload = a.payload_json if isinstance(a.payload_json, dict) else {}
        node = payload.get("impact_node_name")
        d = Desc("action", "info", KIND_ICON["action"], f"Action created: {en_l}" + (f" on {node}" if node else ""),
                 f"تم إنشاء إجراء «{ar_l}»" + (f" على {isolate(node)}" if node else ""), action_id=a.id)
        add((a.created_at, 1, -a.id), a.created_at, d, actor=None, action_id=a.id, event="action_created", audit_id=None,
            status_after="pending")

    items.sort(key=lambda pair: pair[0])
    return {
        "change_id": change_id, "change_title_en": change.summary_en, "change_title_ar": change.summary_ar,
        "clause_ref": change.new_clause_id or change.old_clause_id,
        "items": [entry for _, entry in items],
    }

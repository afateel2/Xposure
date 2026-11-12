"""
Builds the GET /overview document. Read-only. See visibility/schemas.py for the
field-by-field contract.

Definitions (one place, so the dashboard, the Tasks page and the badges agree):

  review queue   material changes that still have at least one PENDING action
  task           an action delegated to a person or the ERP and not yet
                 confirmed done (status awaiting_confirmation)
  resolved       an action that is approved, dismissed or done
  source status  planned (not yet monitored) | attention (a source file
                 conflict in the newest check, or unresolved actions past their
                 due date) | stale (never checked in the window, or not checked
                 for STALE_AFTER_HOURS) | ok
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Action, AuditLog, Change, Regulation, RegulationVersion, Regulator
from . import labels as L
from .planned import PLANNED_REGULATORS
from .priority_index import Prio, load_priority_index
from .timeutil import as_utc, utc_now
from .window import Window, get_window

STALE_AFTER_HOURS = 24 * 7
DUE_SOON_DAYS = 5

SCOPE_NOTE_EN = (
    "A scan checks the regulator documents this build has access to (a local copy of the source documents), "
    "not the live regulator websites."
)
SCOPE_NOTE_AR = (
    "يفحص الوكيل وثائق الجهات التنظيمية المتاحة لهذه النسخة (نسخة محلية من وثائق المصادر) "
    "ولا يفحص المواقع الرسمية للجهات مباشرة."
)

BAND_MEANING: dict[str, tuple[str, str]] = {
    "critical": ("Drop other work: act this week.", "أولوية قصوى: تنفيذ فوري خلال هذا الأسبوع."),
    "high": ("Address soon: needs a named owner now.", "معالجة قريبة: يحتاج إلى مالك محدد الآن."),
    "medium": ("Plan early: schedule it in the current cycle.", "تخطيط مبكر: يُجدول ضمن دورة العمل الحالية."),
    "low": ("Watch only: log and monitor.", "متابعة فقط: سجّل وراقب."),
}

STATUS_LABEL: dict[str, tuple[str, str]] = {
    "ok": ("In sync", "متزامن"),
    "conflict": ("Needs attention: source file conflict", "يتطلب انتباهًا: تعارض في ملف المصدر"),
    "overdue_actions": ("Needs attention: actions are overdue", "يتطلب انتباهًا: توجد إجراءات متأخرة عن موعدها"),
    "never_checked": ("Not checked yet", "لم يُفحص بعد"),
    "not_checked_recently": ("Not checked recently", "لم يُفحص مؤخرًا"),
    "planned": ("Planned", "مخطط له"),
}


def _version_key(label: str) -> tuple[tuple[int, ...], str]:
    import re

    return (tuple(int(n) for n in re.findall(r"\d+", label)), label)


def _band_counts(bands: list[str]) -> dict[str, int]:
    return {b: sum(1 for x in bands if x == b) for b in ("critical", "high", "medium", "low")}


def _matrix_counts(band_counts: dict[str, int]) -> dict[str, int]:
    out = {"critical": 0, "quick": 0, "strategic": 0, "followup": 0}
    for band, n in band_counts.items():
        out[L.BAND_TO_MATRIX_KEY[band]] += n
    return out


def _checked_by_source(
    db: Session, window: Window, monitored_ids: set[int], version_reg: dict[int, int], code_reg: dict[tuple[str, str], int]
) -> tuple[datetime | None, dict[int, datetime], dict[int, int], dict[str, int]]:
    """(last_scan_ts, {regulation_id: last checked ts}, {regulation_id: conflict files in the newest check}, file_issue_counts)

    A sources_checked event covers the regulations its `files` entries resolve
    to (by version_id, or by regulator+regulation code). An event that resolves
    to none (older payloads, or only unrecognized files) covers every
    monitored regulation: the whole source folder was scanned."""
    stmt = select(AuditLog).where(AuditLog.event.in_(("sources_checked", "scan_completed")))
    if window.active and window.reset_id is not None:
        stmt = stmt.where(AuditLog.id >= window.reset_id)
    rows = list(db.scalars(stmt.order_by(AuditLog.id.desc()).limit(200)))

    last_scan: datetime | None = rows[0].ts if rows else None
    checked: dict[int, datetime] = {}
    conflicts: dict[int, int] = defaultdict(int)
    issues = {"conflict": 0, "unrecognized": 0}
    newest_checked_seen = False
    for row in rows:
        if row.event != "sources_checked":
            continue
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        files = payload.get("files") if isinstance(payload.get("files"), list) else []
        refs: set[int] = set()
        for entry in files:
            if not isinstance(entry, dict):
                continue
            reg_id = version_reg.get(entry.get("version_id")) if entry.get("version_id") is not None else None
            if reg_id is None:
                reg_id = code_reg.get((str(entry.get("regulator") or ""), str(entry.get("regulation") or "")))
            if reg_id is not None:
                refs.add(reg_id)
                if not newest_checked_seen and entry.get("status") == "conflict":
                    conflicts[reg_id] += 1
        if not newest_checked_seen:
            newest_checked_seen = True
            counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
            issues["conflict"] = int(counts.get("conflict") or 0)
            issues["unrecognized"] = int(counts.get("unrecognized") or 0)
        for reg_id in (refs or monitored_ids):
            checked.setdefault(reg_id, row.ts)  # rows are newest first
    return last_scan, checked, dict(conflicts), issues


def build_overview(db: Session, since_reset: bool = True, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    naive_now = now.replace(tzinfo=None)
    today = date.today()
    window = get_window(db, since_reset)

    regs = db.execute(select(Regulation, Regulator).join(Regulator, Regulation.regulator_id == Regulator.id).order_by(Regulator.code, Regulation.code)).all()
    versions = list(db.scalars(select(RegulationVersion)))
    changes = list(db.scalars(select(Change)))
    actions = db.execute(select(Action.id, Action.change_id, Action.status, Action.due_date, Action.created_at)).all()

    prio: dict[int, Prio] = load_priority_index(db, changes)
    change_by_id = {c.id: c for c in changes}
    material_ids = {c.id for c in changes if c.material is True and c.id in prio}

    # ── actions ──
    by_status = {s: 0 for s in L.ACTION_STATUSES}
    pending_change_ids: set[int] = set()
    overdue_by_reg: dict[int, int] = defaultdict(int)
    tasks_open = tasks_due_soon = tasks_overdue = 0
    for a in actions:
        by_status[a.status] = by_status.get(a.status, 0) + 1
        if a.status == "pending":
            pending_change_ids.add(a.change_id)
        due = a.due_date
        if due is None and a.change_id in prio:
            due = prio[a.change_id].due_date
        if a.status in L.OPEN_STATUSES and due is not None and due < today:
            change = change_by_id.get(a.change_id)
            if change is not None:
                overdue_by_reg[change.regulation_id] += 1
        if a.status == "awaiting_confirmation":
            tasks_open += 1
            if due is not None:
                if due < today:
                    tasks_overdue += 1
                elif (due - today).days <= DUE_SOON_DAYS:
                    tasks_due_soon += 1

    # ── review queue and priority matrix ──
    queue_change_ids = [cid for cid in pending_change_ids if cid in material_ids]
    queue_bands = _band_counts([prio[cid].band for cid in queue_change_ids])
    all_bands = _band_counts([prio[cid].band for cid in material_ids])
    matrix = _matrix_counts(queue_bands)
    total_actions = sum(by_status.values())
    resolved = sum(by_status.get(s, 0) for s in L.RESOLVED_STATUSES)

    review_queue = {
        "total": len(queue_change_ids),
        "critical": queue_bands["critical"], "urgent": queue_bands["high"],
        "strategic": queue_bands["medium"], "followup": queue_bands["low"],
        "awaiting_confirmation": by_status.get("awaiting_confirmation", 0),
        "pending_actions": by_status.get("pending", 0),
        "basis_en": "Material changes that still have at least one action waiting for a human decision.",
        "basis_ar": "التغييرات الجوهرية التي لا يزال لها إجراء واحد على الأقل بانتظار قرار بشري.",
    }
    priority_matrix = {
        **matrix,
        "total": sum(matrix.values()),
        "basis_en": "The same open review items as review_queue, placed in the four quadrants by the app's priority band.",
        "basis_ar": "عناصر المراجعة المفتوحة نفسها الواردة في قائمة المراجعة، موزعة على أربعة أرباع بحسب مستوى الأولوية في التطبيق.",
        "mapping": [
            {
                "band": band, "review_key": L.BAND_TO_REVIEW_KEY[band], "matrix_key": L.BAND_TO_MATRIX_KEY[band],
                "band_label_en": L.BAND_LABEL[band][0], "band_label_ar": L.BAND_LABEL[band][1],
                "matrix_label_en": L.MATRIX_LABEL[L.BAND_TO_MATRIX_KEY[band]][0],
                "matrix_label_ar": L.MATRIX_LABEL[L.BAND_TO_MATRIX_KEY[band]][1],
                "meaning_en": BAND_MEANING[band][0], "meaning_ar": BAND_MEANING[band][1],
            }
            for band in ("critical", "high", "medium", "low")
        ],
        "all_material": _matrix_counts(all_bands),
    }
    tasks = {
        "open": tasks_open, "due_within_5_days": tasks_due_soon, "overdue": tasks_overdue,
        "definition_en": "Open tasks are actions delegated to a person or the ERP and not yet confirmed as done.",
        "definition_ar": "المهام المفتوحة هي الإجراءات المُسنَدة إلى شخص أو إلى نظام تخطيط الموارد ولم يُؤكَّد إنجازها بعد.",
    }
    remediation = {
        "total_actions": total_actions, "resolved_actions": resolved,
        "percent": round(100.0 * resolved / total_actions, 1) if total_actions else None,
        "by_status": by_status,
    }

    # ── per-source ──
    versions_by_reg: dict[int, list[RegulationVersion]] = defaultdict(list)
    version_reg = {}
    for v in versions:
        versions_by_reg[v.regulation_id].append(v)
        version_reg[v.id] = v.regulation_id
    code_reg = {(regulator.code, regulation.code): regulation.id for regulation, regulator in regs}
    monitored_ids = {regulation.id for regulation, _ in regs}
    last_scan, checked, conflicts, file_issues = _checked_by_source(db, window, monitored_ids, version_reg, code_reg)

    changes_by_reg: dict[int, list[Change]] = defaultdict(list)
    for c in changes:
        changes_by_reg[c.regulation_id].append(c)

    sources: list[dict[str, Any]] = []
    ok_count = 0
    for regulation, regulator in regs:
        vs = sorted(versions_by_reg.get(regulation.id, []), key=lambda v: _version_key(v.version_label))
        latest = vs[-1] if vs else None
        reg_changes = changes_by_reg.get(regulation.id, [])
        in_window = [c for c in reg_changes if window.ts_ok(c.created_at)]
        last_change = max((c.created_at for c in in_window), default=None)
        open_changes = sum(1 for c in reg_changes if c.id in material_ids and c.id in pending_change_ids)
        last_checked = checked.get(regulation.id)

        if conflicts.get(regulation.id):
            status, reason = "attention", "conflict"
        elif overdue_by_reg.get(regulation.id):
            status, reason = "attention", "overdue_actions"
        elif last_checked is None:
            status, reason = "stale", "never_checked"
        elif (naive_now - last_checked) > timedelta(hours=STALE_AFTER_HOURS):
            status, reason = "stale", "not_checked_recently"
        else:
            status, reason = "ok", "ok"
        if status == "ok":
            ok_count += 1
        sources.append({
            "code": f"{regulator.code}/{regulation.code}", "regulator_code": regulator.code, "regulation_code": regulation.code,
            "name_en": regulator.name_en, "name_ar": regulator.name_ar,
            "title_en": regulation.title_en, "title_ar": regulation.title_ar,
            "latest_version": latest.version_label if latest else None,
            "latest_version_ingested_at": as_utc(latest.ingested_at) if latest else None,
            "last_checked_at": as_utc(last_checked), "last_change_at": as_utc(last_change),
            "open_changes": open_changes, "changes_total": len(reg_changes),
            "status": status, "status_reason": reason,
            "status_label_en": STATUS_LABEL[reason][0], "status_label_ar": STATUS_LABEL[reason][1],
            "planned": False, "scope_en": None, "scope_ar": None,
        })

    known_codes = {regulator.code for _, regulator in regs}
    planned = [p for p in PLANNED_REGULATORS if p.code not in known_codes]
    for p in planned:
        sources.append({
            "code": p.code, "regulator_code": p.code, "regulation_code": None,
            "name_en": p.name_en, "name_ar": p.name_ar, "title_en": None, "title_ar": None,
            "latest_version": None, "latest_version_ingested_at": None, "last_checked_at": None, "last_change_at": None,
            "open_changes": 0, "changes_total": 0, "status": "planned", "status_reason": "planned",
            "status_label_en": STATUS_LABEL["planned"][0], "status_label_ar": STATUS_LABEL["planned"][1],
            "planned": True, "scope_en": p.scope_en, "scope_ar": p.scope_ar,
        })

    # ── releases: last detected, mean hours to alert ──
    to_versions = {c.to_version_id for c in changes}
    version_by_id = {v.id: v for v in versions}
    release_ts: list[datetime] = [
        version_by_id[vid].ingested_at for vid in to_versions
        if vid in version_by_id and window.ts_ok(version_by_id[vid].ingested_at)
    ]
    ingest_stmt = select(AuditLog).where(AuditLog.event.in_(("source_ingested", "baseline_ingested")))
    if window.active and window.reset_id is not None:
        ingest_stmt = ingest_stmt.where(AuditLog.id >= window.reset_id)
    ingest_rows = list(db.scalars(ingest_stmt))
    baseline_refs = {r.ref_id for r in ingest_rows if r.event == "baseline_ingested"}
    release_ts += [r.ts for r in ingest_rows if r.event == "source_ingested" and r.ref_id not in baseline_refs]
    last_release = max(release_ts) if release_ts else None

    first_alert: dict[int, datetime] = {}
    action_first: dict[int, datetime] = {}
    for a in actions:
        if a.created_at is not None and (a.change_id not in action_first or a.created_at < action_first[a.change_id]):
            action_first[a.change_id] = a.created_at
    for c in changes:
        stamp = action_first.get(c.id, c.created_at)
        if stamp is not None and (c.to_version_id not in first_alert or stamp < first_alert[c.to_version_id]):
            first_alert[c.to_version_id] = stamp
    hours: list[float] = []
    for vid in to_versions:
        v = version_by_id.get(vid)
        if v is None or v.published_at is None or vid not in first_alert or not window.ts_ok(v.ingested_at):
            continue
        published = v.published_at.replace(tzinfo=None) if v.published_at.tzinfo else v.published_at
        delta = (first_alert[vid] - published).total_seconds() / 3600.0
        if delta >= 0:
            hours.append(delta)

    monitoring = {
        "sources_total": len(regs), "sources_ok": ok_count, "sources_planned": len(planned),
        "last_scan_at": as_utc(last_scan), "last_release_detected_at": as_utc(last_release),
        "mean_hours_publish_to_alert": round(sum(hours) / len(hours), 1) if hours else None,
        "mean_hours_sample_size": len(hours),
        "stale_after_hours": STALE_AFTER_HOURS,
        "file_issues": file_issues,
        "scope_note_en": SCOPE_NOTE_EN, "scope_note_ar": SCOPE_NOTE_AR,
    }
    return {
        "generated_at": now,
        "window": {"since_reset": window.active, "reset_at": as_utc(window.reset_at)},
        "monitoring": monitoring, "review_queue": review_queue, "tasks": tasks,
        "priority_matrix": priority_matrix, "remediation": remediation, "sources": sources,
    }

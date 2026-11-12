"""
Audit event catalogue: how one audit_log row becomes a human-readable line,
and how noisy repeats collapse into a single activity-feed entry.

Every audit event the code base writes is described here (pipeline nodes in
agent/graph.py, the action endpoints in routes/actions.py, digest.py, the
webhook receiver) plus the events other workstreams add (scan_requested,
stage_*, scan_completed, scan_failed, demo_reset, action_effect_*, erp_*).
An event name that is not in the catalogue never raises: describe() falls
back to a generic, readable line derived from the name and its reference.

Text is generated ONLY from the audit row's own payload and from real rows
(Action, Change) looked up by the row's reference. Nothing here guesses.

Vocabulary of the output:
  kind      scan | ingest | diff | classify | impact | action | delegate |
            confirm | undo | export | system | effect
  severity  info | success | warning | danger
  icon      a Lucide icon name (lucide-react)
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Action, AuditLog, Change, OrgNode
from . import labels as L
from .labels import ar_count, isolate, trunc

# Same tuple as routes/actions.py TRANSITION_EVENTS (restated, not imported, so
# this module stays importable without pulling the action endpoints in).
TRANSITION_EVENTS = (
    "action_approved", "action_dismissed", "action_delegated",
    "action_confirmed_done", "action_auto_executed", "action_status_reverted",
)

KIND_ICON = {
    "scan": "scan-search", "ingest": "download", "diff": "git-compare", "classify": "tags",
    "impact": "network", "action": "list-checks", "delegate": "send", "confirm": "circle-check",
    "undo": "undo-2", "export": "send", "system": "activity", "effect": "file-pen",
}

DECISION = ("قرار واحد", "قرارين", "قرارات", "قرارًا")


# ── Row wrapper ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Ev:
    id: int
    ts: datetime  # naive UTC, as stored
    actor: str
    event: str
    ref_type: str
    ref_id: int | None
    p: dict[str, Any]

    @classmethod
    def from_row(cls, row: AuditLog) -> "Ev":
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        return cls(row.id, row.ts, row.actor, row.event, row.ref_type or "", row.ref_id, payload)

    @property
    def run_id(self) -> str:
        return str(self.p.get("run_id") or "")


@dataclass
class Desc:
    kind: str
    severity: str
    icon: str
    en: str
    ar: str
    detail_en: str | None = None
    detail_ar: str | None = None
    change_id: int | None = None
    action_id: int | None = None


@dataclass
class Ctx:
    """Real rows the text builders may consult (batched, one query per table)."""

    actions: dict[int, dict[str, Any]] = field(default_factory=dict)
    changes: dict[int, dict[str, Any]] = field(default_factory=dict)
    pair_types: dict[tuple[int, int], dict[str, int]] = field(default_factory=dict)
    status_after: dict[int, str] = field(default_factory=dict)  # audit id -> action status after that transition


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_ctx(db: Session, evs: Iterable[Ev], extra_change_ids: Iterable[int] = (), with_status_after: str | bool = False) -> Ctx:
    """with_status_after: False (skip), True (only for undo rows, what the feed
    needs) or "all" (every action transition, what the timeline needs)."""
    evs = list(evs)
    action_ids: set[int] = set()
    change_ids: set[int] = set(extra_change_ids)
    pairs: set[tuple[int, int]] = set()
    revert_action_ids: set[int] = set()
    for ev in evs:
        if ev.ref_type == "action" and ev.ref_id is not None:
            action_ids.add(ev.ref_id)
            if ev.event == "action_status_reverted":
                revert_action_ids.add(ev.ref_id)
        if ev.ref_type == "change" and ev.ref_id is not None:
            change_ids.add(ev.ref_id)
        for key in ("action_id",):
            v = _int(ev.p.get(key))
            if v is not None:
                action_ids.add(v)
        v = _int(ev.p.get("change_id"))
        if v is not None:
            change_ids.add(v)
        if ev.event == "versions_diffed":
            a, b = _int(ev.p.get("from_version_id")), _int(ev.p.get("to_version_id"))
            if a is not None and b is not None:
                pairs.add((a, b))

    ctx = Ctx()
    if action_ids:
        rows = db.scalars(select(Action).where(Action.id.in_(sorted(action_ids)))).all()
        owner_ids = {r.owner_node_id for r in rows if r.owner_node_id}
        owners = {n.id: n.name for n in db.scalars(select(OrgNode).where(OrgNode.id.in_(owner_ids)))} if owner_ids else {}
        for r in rows:
            payload = r.payload_json if isinstance(r.payload_json, dict) else {}
            ctx.actions[r.id] = {
                "type": r.type, "change_id": r.change_id, "status": r.status, "level": r.level,
                "node": payload.get("impact_node_name") or owners.get(r.owner_node_id),
                "clause": payload.get("clause_id"), "assignee": r.assignee_name,
            }
            change_ids.add(r.change_id)
    if change_ids:
        for c in db.scalars(select(Change).where(Change.id.in_(sorted(change_ids)))):
            ctx.changes[c.id] = {
                "clause": c.new_clause_id or c.old_clause_id, "summary_en": c.summary_en, "summary_ar": c.summary_ar,
                "change_type": c.change_type,
            }
    for from_id, to_id in pairs:
        rows = db.execute(
            select(Change.change_type, func.count())
            .where(Change.from_version_id == from_id, Change.to_version_id == to_id)
            .group_by(Change.change_type)
        ).all()
        ctx.pair_types[(from_id, to_id)] = {(t or "unclassified"): n for t, n in rows}

    if with_status_after == "all":
        every = {ev.ref_id for ev in evs if ev.ref_type == "action" and ev.ref_id is not None}
        if every:
            _fill_status_after(db, ctx, every)
    elif with_status_after and revert_action_ids:
        _fill_status_after(db, ctx, revert_action_ids)
    return ctx


def _fill_status_after(db: Session, ctx: Ctx, action_ids: set[int]) -> None:
    """Each transition row records the status BEFORE it (previous_status), so
    the status AFTER a transition is the next transition's previous_status,
    or the action's current status for the newest one."""
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.ref_type == "action", AuditLog.ref_id.in_(sorted(action_ids)), AuditLog.event.in_(TRANSITION_EVENTS))
        .order_by(AuditLog.id)
    ).all()
    per_action: dict[int, list[AuditLog]] = {}
    for r in rows:
        per_action.setdefault(r.ref_id, []).append(r)
    current = {a.id: a.status for a in db.scalars(select(Action).where(Action.id.in_(sorted(action_ids))))}
    for action_id, seq in per_action.items():
        for i, r in enumerate(seq):
            if i + 1 < len(seq):
                after = (seq[i + 1].payload_json or {}).get("previous_status")
            else:
                after = current.get(action_id)
            if after:
                ctx.status_after[r.id] = after


# ── Text helpers ──────────────────────────────────────────────────────────

def _reg_ref(p: dict[str, Any], version_key: str = "version_label") -> str:
    regulator = str(p.get("regulator") or "").upper()
    regulation = str(p.get("regulation") or "").upper()
    label = str(p.get(version_key) or "")
    return " ".join(x for x in (regulator, regulation, label) if x)


def _action_ref(ev: Ev, ctx: Ctx) -> tuple[int | None, int | None]:
    action_id = ev.ref_id if ev.ref_type == "action" else _int(ev.p.get("action_id"))
    info = ctx.actions.get(action_id) if action_id is not None else None
    change_id = (info or {}).get("change_id") or _int(ev.p.get("change_id"))
    if change_id is None and ev.ref_type == "change":
        change_id = ev.ref_id
    return action_id, change_id


def _action_phrase(ev: Ev, ctx: Ctx) -> tuple[str, str]:
    """'Update policy on Information Security Policy (clause 2-5-3)' in EN and AR."""
    action_id, change_id = _action_ref(ev, ctx)
    info = ctx.actions.get(action_id) if action_id is not None else None
    action_type = (info or {}).get("type") or ev.p.get("type")
    en_label, ar_label = L.action_type_label(action_type)
    node = (info or {}).get("node") or ev.p.get("impact_node_name")
    clause = (ctx.changes.get(change_id) or {}).get("clause") if change_id is not None else None
    clause = clause or (info or {}).get("clause") or ev.p.get("clause_id")
    en, ar = en_label, f"«{ar_label}»"
    if node:
        en += f" on {node}"
        ar += f" على {isolate(node)}"
    if clause:
        en += f" (clause {clause})"
        ar += f" (البند {isolate(clause)})"
    return en, ar


def _stage(p: dict[str, Any]) -> tuple[str, str, str]:
    key = str(p.get("stage") or p.get("key") or p.get("name") or "")
    en, ar = L.STAGE_LABEL.get(key, (None, None))
    en = p.get("label_en") or en or (L.humanize_event(key) if key else "Pipeline stage")
    ar = p.get("label_ar") or ar or (isolate(key) if key else "إحدى مراحل المعالجة")
    return key, en, ar


def _err(p: dict[str, Any]) -> str:
    return trunc(p.get("error") or p.get("message") or p.get("reason") or "", 200)


def _band_severity(band: str | None) -> str:
    return {"critical": "danger", "high": "warning"}.get(band or "", "info")


def _first_sentence_counts(counter: dict[str, int], label_map: dict[str, tuple[str, str]], order: Iterable[str] | None = None) -> tuple[str, str] | None:
    keys = [k for k in (order or counter.keys()) if counter.get(k)]
    if not keys:
        return None
    en = ", ".join(f"{label_map.get(k, (L.humanize_event(k), isolate(k)))[0]}: {counter[k]}" for k in keys)
    ar = "، ".join(f"{label_map.get(k, (L.humanize_event(k), isolate(k)))[1]}: {counter[k]}" for k in keys)
    return en, ar


# ── Handlers ──────────────────────────────────────────────────────────────

Handler = Callable[[Ev, Ctx], Desc]
HANDLERS: dict[str, Handler] = {}


def handles(*names: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        for name in names:
            HANDLERS[name] = fn
        return fn

    return deco


def _d(kind: str, severity: str, en: str, ar: str, *, icon: str | None = None, **extra: Any) -> Desc:
    return Desc(kind=kind, severity=severity, icon=icon or KIND_ICON[kind], en=en, ar=ar, **extra)


# -- scan lifecycle (demo runner) --

@handles("scan_requested")
def _scan_requested(ev: Ev, ctx: Ctx) -> Desc:
    return _d("scan", "info", "Scan requested", "تم طلب فحص المصادر", icon="scan-search")


@handles("stage_started")
def _stage_started(ev: Ev, ctx: Ctx) -> Desc:
    _, en, ar = _stage(ev.p)
    return _d("system", "info", f"Started: {en}", f"بدأت المرحلة: {ar}", icon="hourglass",
              detail_en=ev.p.get("detail_en"), detail_ar=ev.p.get("detail_ar"))


@handles("stage_completed")
def _stage_completed(ev: Ev, ctx: Ctx) -> Desc:
    _, en, ar = _stage(ev.p)
    if str(ev.p.get("status") or "").lower() in ("failed", "error"):
        return _d("system", "danger", f"Failed: {en}", f"تعذر إكمال المرحلة: {ar}", icon="circle-x",
                  detail_en=ev.p.get("detail_en"), detail_ar=ev.p.get("detail_ar"))
    return _d("system", "success", f"Completed: {en}", f"اكتملت المرحلة: {ar}", icon="circle-check",
              detail_en=ev.p.get("detail_en"), detail_ar=ev.p.get("detail_ar"))


@handles("scan_completed")
def _scan_completed(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    summary = p.get("summary") if isinstance(p.get("summary"), dict) else p
    changes = _int(summary.get("changes_processed", summary.get("changes", summary.get("change_count"))))
    actions = _int(summary.get("actions_created", summary.get("actions", summary.get("action_count"))))
    parts_en, parts_ar = [], []
    if changes is not None:
        parts_en.append(f"{changes} changes")
        parts_ar.append(f"عدد التغييرات {changes}")
    if actions is not None:
        parts_en.append(f"{actions} actions")
        parts_ar.append(f"عدد الإجراءات {actions}")
    return _d("scan", "success", "Scan completed", "اكتمل الفحص", icon="circle-check",
              detail_en=", ".join(parts_en) or p.get("detail_en"), detail_ar="، ".join(parts_ar) or p.get("detail_ar"))


@handles("scan_failed")
def _scan_failed(ev: Ev, ctx: Ctx) -> Desc:
    err = _err(ev.p)
    return _d("scan", "danger", f"Scan failed: {err}" if err else "Scan failed",
              f"فشل الفحص: {isolate(err)}" if err else "فشل الفحص", icon="circle-x")


@handles("demo_reset")
def _demo_reset(ev: Ev, ctx: Ctx) -> Desc:
    return _d("system", "info", "Demo data was reset to the baseline state",
              "تمت إعادة بيانات العرض التجريبي إلى الحالة الأساسية", icon="rotate-ccw")


# -- pipeline nodes (agent/graph.py) --

@handles("sources_checked")
def _sources_checked(ev: Ev, ctx: Ctx) -> Desc:
    counts = ev.p.get("counts") if isinstance(ev.p.get("counts"), dict) else {}
    total = sum(v for v in counts.values() if isinstance(v, int))
    if total == 0:
        return _d("scan", "info", "Checked the sources: no documents found",
                  "تم فحص المصادر ولم يُعثر على أي وثيقة", icon="radar")
    names = {
        "new": ("new", "جديدة"), "already_ingested": ("already ingested", "مستوعبة سابقًا"),
        "conflict": ("in conflict", "متعارضة"), "unrecognized": ("unrecognized", "غير معروفة"),
    }
    en_parts = [f"{counts[k]} {names[k][0]}" for k in names if counts.get(k)]
    ar_parts = [f"{counts[k]} {names[k][1]}" for k in names if counts.get(k)]
    attention = bool(counts.get("conflict") or counts.get("unrecognized"))
    return _d("scan", "warning" if attention else "info",
              f"Checked {L.en_count(total, 'source document')}: {', '.join(en_parts)}",
              f"تم فحص {ar_count(total, L.DOCUMENT)}: {'، '.join(ar_parts)}", icon="radar")


@handles("source_ingested")
def _source_ingested(ev: Ev, ctx: Ctx) -> Desc:
    ref = _reg_ref(ev.p)
    return _d("ingest", "success", f"New version ingested: {ref}", f"تم استيعاب إصدار جديد: {isolate(ref)}", icon="download")


@handles("baseline_ingested")
def _baseline_ingested(ev: Ev, ctx: Ctx) -> Desc:
    ref = _reg_ref(ev.p)
    return _d("ingest", "success", f"Baseline loaded: {ref} (no earlier version to compare against)",
              f"تم تحميل الإصدار الأساسي: {isolate(ref)} (لا يوجد إصدار سابق للمقارنة)", icon="layers")


@handles("ingest_new_completed")
def _ingest_completed(ev: Ev, ctx: Ctx) -> Desc:
    n = _int(ev.p.get("ingested_count")) or 0
    return _d("ingest", "info", f"Ingestion finished: {L.en_count(n, 'new version')}",
              f"انتهى الاستيعاب: عدد الإصدارات الجديدة {n}", icon="download")


@handles("versions_diffed")
def _versions_diffed(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    reg = " ".join(x for x in (str(p.get("regulator") or "").upper(), str(p.get("regulation") or "").upper()) if x)
    a, b = str(p.get("from_label") or "?"), str(p.get("to_label") or "?")
    total = _int(p.get("change_count")) or 0
    material = _int(p.get("material_count")) or 0
    en = f"Compared {reg} {a} with {b}: {L.en_count(total, 'change')} found, {material} material"
    ar = f"تمت مقارنة {isolate(f'{reg} {a}'.strip())} بالإصدار {isolate(b)}: تم رصد {ar_count(total, L.CHANGE)} (الجوهري منها: {material})"
    detail = None
    pair = (_int(p.get("from_version_id")), _int(p.get("to_version_id")))
    types = ctx.pair_types.get(pair)  # type: ignore[arg-type]
    if types:
        detail = _first_sentence_counts(types, L.CHANGE_TYPE_LABEL, sorted(types, key=lambda k: -types[k]))
    return _d("diff", "success" if total else "info", en, ar, icon="git-compare",
              detail_en=detail[0] if detail else None, detail_ar=detail[1] if detail else None)


@handles("diff_pair_completed")
def _diff_pair_completed(ev: Ev, ctx: Ctx) -> Desc:
    return _d("diff", "info", "Version pair comparison recorded", "تم تسجيل مقارنة زوج الإصدارات", icon="git-compare")


@handles("diff_completed")
def _diff_completed(ev: Ev, ctx: Ctx) -> Desc:
    n = _int(ev.p.get("pairs_diffed")) or 0
    return _d("diff", "info", f"Comparison finished: {L.en_count(n, 'version pair')} compared",
              f"انتهت المقارنة: عدد أزواج الإصدارات {n}", icon="git-compare")


@handles("impact_computed", "impact_reused")
def _impact(ev: Ev, ctx: Ctx) -> Desc:
    n = _int(ev.p.get("impact_count")) or 0
    clause = ev.p.get("clause_id")
    change_id = ev.ref_id if ev.ref_type == "change" else _int(ev.p.get("change_id"))
    where_en = f" for clause {clause}" if clause else ""
    where_ar = f" للبند {isolate(clause)}" if clause else ""
    reused = ev.event == "impact_reused"
    lead_en = "Earlier impact reused" if reused else "Impact traced"
    lead_ar = "أُعيد استخدام تحليل الأثر السابق" if reused else "تم تتبع الأثر"
    if n == 0:
        return _d("impact", "info", f"{lead_en}{where_en}: no impacted nodes", f"{lead_ar}{where_ar}: لا توجد عقد متأثرة",
                  change_id=change_id)
    return _d("impact", "info", f"{lead_en}{where_en}: {L.en_count(n, 'node')} affected",
              f"{lead_ar}{where_ar}: عدد العقد المتأثرة {n}", change_id=change_id)


@handles("impact_node_completed")
def _impact_completed(ev: Ev, ctx: Ctx) -> Desc:
    c, r = _int(ev.p.get("changes_considered")) or 0, _int(ev.p.get("impact_rows")) or 0
    return _d("impact", "info", f"Impact stage finished: {L.en_count(c, 'change')} considered, {r} impacted nodes in total",
              f"انتهت مرحلة الأثر: عدد التغييرات {c}، وإجمالي العقد المتأثرة {r}")


@handles("change_prioritized")
def _prioritized(ev: Ev, ctx: Ctx) -> Desc:
    band = str(ev.p.get("band") or "")
    score = ev.p.get("score")
    b_en, b_ar = L.BAND_LABEL.get(band, (band, isolate(band)) if band else ("", ""))
    change_id = ev.ref_id if ev.ref_type == "change" else _int(ev.p.get("change_id"))
    if score is None:
        en, ar = "Priority computed", "تم احتساب الأولوية"
    else:
        en, ar = f"Priority computed: {score}/100", f"تم احتساب الأولوية: {score}/100"
    if b_en:
        en, ar = f"{en} ({b_en})", f"{ar} ({b_ar})"
    return _d("classify", _band_severity(band), en, ar, icon="gauge", change_id=change_id)


@handles("prioritize_completed")
def _prioritize_completed(ev: Ev, ctx: Ctx) -> Desc:
    n = _int(ev.p.get("changes_prioritized")) or 0
    bands = ev.p.get("bands") if isinstance(ev.p.get("bands"), dict) else {}
    detail = _first_sentence_counts(bands, L.BAND_LABEL, ("critical", "high", "medium", "low"))
    return _d("classify", "info", f"Prioritization finished: {L.en_count(n, 'change')} scored",
              f"انتهى ترتيب الأولوية: عدد التغييرات {n}", icon="gauge",
              detail_en=detail[0] if detail else None, detail_ar=detail[1] if detail else None)


@handles("action_created")
def _action_created(ev: Ev, ctx: Ctx) -> Desc:
    action_id, change_id = _action_ref(ev, ctx)
    phrase_en, phrase_ar = _action_phrase(ev, ctx)
    level = str(ev.p.get("level") or "")
    lv_en, lv_ar = L.ACTION_LEVEL_LABEL.get(level, ("", ""))
    detail_en = f"Automation level: {lv_en}" if lv_en else None
    detail_ar = f"مستوى الأتمتة: {lv_ar}" if lv_ar else None
    return _d("action", "info", f"Action created: {phrase_en}", f"تم إنشاء إجراء {phrase_ar}",
              action_id=action_id, change_id=change_id, detail_en=detail_en, detail_ar=detail_ar)


@handles("apply_policy_completed")
def _apply_policy_completed(ev: Ev, ctx: Ctx) -> Desc:
    n = _int(ev.p.get("actions_created")) or 0
    by_level = ev.p.get("by_level") if isinstance(ev.p.get("by_level"), dict) else {}
    detail = _first_sentence_counts(by_level, L.ACTION_LEVEL_LABEL)
    return _d("action", "info", f"Automation policy applied: {L.en_count(n, 'action')} created",
              f"تم تطبيق سياسة الأتمتة: عدد الإجراءات المنشأة {n}",
              detail_en=detail[0] if detail else None, detail_ar=detail[1] if detail else None)


@handles("action_auto_executed")
def _auto_executed(ev: Ev, ctx: Ctx) -> Desc:
    action_id, change_id = _action_ref(ev, ctx)
    phrase_en, phrase_ar = _action_phrase(ev, ctx)
    return _d("action", "success", f"Auto-executed by policy: {phrase_en} (recorded in this database only, no external system called)",
              f"تم تنفيذ إجراء {phrase_ar} تلقائيًا وفق السياسة (سُجّل في قاعدة البيانات فقط دون استدعاء أي نظام خارجي)",
              icon="check-check", action_id=action_id, change_id=change_id)


@handles("auto_execute_completed")
def _auto_exec_completed(ev: Ev, ctx: Ctx) -> Desc:
    n = _int(ev.p.get("executed_count")) or 0
    return _d("action", "info", f"Auto-execution finished: {L.en_count(n, 'action')} closed",
              f"انتهى التنفيذ التلقائي: عدد الإجراءات {n}", icon="check-check")


@handles("human_review_skipped")
def _review_skipped(ev: Ev, ctx: Ctx) -> Desc:
    return _d("system", "info", "No actions needed human review in this run",
              "لم تتطلب أي إجراءات مراجعة بشرية في هذا التشغيل", icon="clipboard-check")


@handles("run_paused_for_human_review")
def _paused(ev: Ev, ctx: Ctx) -> Desc:
    ids = ev.p.get("awaiting_action_ids")
    n = len(ids) if isinstance(ids, list) else 0
    return _d("system", "warning", f"Run paused: {L.en_count(n, 'action')} waiting for a human decision",
              f"توقف التشغيل مؤقتًا بانتظار قرار بشري: عدد الإجراءات {n}", icon="pause")


@handles("human_review_applied")
def _review_applied(ev: Ev, ctx: Ctx) -> Desc:
    a = len(ev.p.get("approved") or [])
    d = len(ev.p.get("dismissed") or [])
    left = len(ev.p.get("left_pending") or [])
    return _d("action", "success", f"Review applied: {a} approved, {d} dismissed, {left} left pending",
              f"تم تطبيق قرار المراجعة: معتمد {a}، مُتجاهَل {d}، معلّق {left}", icon="clipboard-check")


@handles("run_delivered")
def _run_delivered(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    c, a = _int(p.get("changes_processed")) or 0, _int(p.get("actions_created")) or 0
    bands = p.get("priority_bands") if isinstance(p.get("priority_bands"), dict) else {}
    detail = _first_sentence_counts(bands, L.BAND_LABEL, ("critical", "high", "medium", "low"))
    return _d("system", "success", f"Run delivered: {L.en_count(c, 'change')} processed, {L.en_count(a, 'action')} created",
              f"اكتمل التشغيل: عدد التغييرات المعالجة {c}، وعدد الإجراءات المنشأة {a}", icon="circle-check",
              detail_en=detail[0] if detail else None, detail_ar=detail[1] if detail else None)


@handles("run_failed")
def _run_failed(ev: Ev, ctx: Ctx) -> Desc:
    err = _err(ev.p)
    return _d("system", "danger", f"Run failed: {err}" if err else "Run failed",
              f"فشل التشغيل: {isolate(err)}" if err else "فشل التشغيل", icon="circle-x")


@handles("resume_failed")
def _resume_failed(ev: Ev, ctx: Ctx) -> Desc:
    err = _err(ev.p)
    return _d("system", "danger", f"Resuming the paused run failed: {err}" if err else "Resuming the paused run failed",
              f"فشلت محاولة استئناف التشغيل المتوقف: {isolate(err)}" if err else "فشلت محاولة استئناف التشغيل المتوقف",
              icon="circle-x")


# -- human decisions (routes/actions.py) --

def _decision(ev: Ev, ctx: Ctx, severity: str, en_lead: str, ar_lead: str, icon: str, kind: str = "action") -> Desc:
    action_id, change_id = _action_ref(ev, ctx)
    phrase_en, phrase_ar = _action_phrase(ev, ctx)
    # A dismissal carries the reviewer's written reason (routes/actions.py);
    # shown as the detail line so the timeline answers "why" and not only "who".
    reason = str(ev.p.get("reason") or "").strip()
    return _d(kind, severity, f"{en_lead}: {phrase_en}", f"{ar_lead} {phrase_ar}", icon=icon,
              action_id=action_id, change_id=change_id,
              detail_en=f"Reason: {reason}" if reason else None,
              detail_ar=f"السبب: {isolate(reason)}" if reason else None)


@handles("action_approved")
def _approved(ev: Ev, ctx: Ctx) -> Desc:
    return _decision(ev, ctx, "success", "Approved", "تمت الموافقة على إجراء", "circle-check")


@handles("action_dismissed")
def _dismissed(ev: Ev, ctx: Ctx) -> Desc:
    return _decision(ev, ctx, "warning", "Dismissed", "تم تجاهل إجراء", "circle-x")


def _notification_detail(p: dict[str, Any]) -> tuple[str | None, str | None]:
    note = p.get("notification")
    if not isinstance(note, dict):
        return None, None
    if note.get("sent") is True:
        channel = note.get("channel") or "configured channel"
        return f"Notification sent via {channel}", f"تم إرسال إشعار عبر {isolate(channel)}"
    reason = str(note.get("reason") or "")
    known = {
        "no notification channel configured": "لم تُضبط أي قناة إشعار",
        "no recipient contact given": "لم يُحدَّد جهة اتصال للمستلم",
        "no SMTP host configured": "لم يُضبط خادم البريد",
    }
    en = f"No notification was sent: {reason}" if reason else "No notification was sent"
    ar = f"لم يُرسل أي إشعار: {known.get(reason, isolate(reason))}" if reason else "لم يُرسل أي إشعار"
    return en, ar


@handles("action_delegated")
def _delegated(ev: Ev, ctx: Ctx) -> Desc:
    action_id, change_id = _action_ref(ev, ctx)
    phrase_en, phrase_ar = _action_phrase(ev, ctx)
    who = ev.p.get("assignee_name")
    en = f"Delegated: {phrase_en}" + (f" to {who}" if who else "")
    ar = f"تم إسناد إجراء {phrase_ar}" + (f" إلى {isolate(who)}" if who else "")
    detail_en, detail_ar = _notification_detail(ev.p)
    erp = ev.p.get("erp") if isinstance(ev.p.get("erp"), dict) else None
    if erp or str(ev.p.get("channel") or "").lower() == "odoo":
        task_id = (erp or {}).get("task_id") or ev.p.get("task_id")
        tail_en = f"Escalated through Odoo" + (f", task #{task_id}" if task_id else "")
        tail_ar = "تم التصعيد عبر Odoo" + (f"، المهمة رقم {isolate(task_id)}" if task_id else "")
        detail_en = tail_en if not detail_en else f"{tail_en}. {detail_en}"
        detail_ar = tail_ar if not detail_ar else f"{tail_ar}. {detail_ar}"
    return _d("delegate", "info", en, ar, action_id=action_id, change_id=change_id, detail_en=detail_en, detail_ar=detail_ar)


@handles("action_confirmed_done")
def _confirmed(ev: Ev, ctx: Ctx) -> Desc:
    return _decision(ev, ctx, "success", "Completion confirmed", "تم تأكيد إنجاز إجراء", "user-round-check", kind="confirm")


_REVERTED_PHRASE = {
    "action_approved": ("the approval of", "الموافقة على"),
    "action_dismissed": ("the dismissal of", "تجاهل"),
    "action_delegated": ("the delegation of", "إسناد"),
    "action_confirmed_done": ("the completion confirmation of", "تأكيد إنجاز"),
    "action_auto_executed": ("the auto-execution of", "التنفيذ التلقائي لإجراء"),
    "action_status_reverted": ("an earlier undo of", "تراجع سابق عن"),
}


@handles("action_status_reverted")
def _reverted(ev: Ev, ctx: Ctx) -> Desc:
    action_id, change_id = _action_ref(ev, ctx)
    phrase_en, phrase_ar = _action_phrase(ev, ctx)
    what_en, what_ar = _REVERTED_PHRASE.get(str(ev.p.get("reverted_event") or ""), ("the last decision on", "آخر قرار بشأن"))
    en, ar = f"Undone: {what_en} {phrase_en}", f"تم التراجع عن {what_ar} {phrase_ar}"
    after = ctx.status_after.get(ev.id)
    detail_en = detail_ar = None
    if after:
        s_en, s_ar = L.status_label(after)
        detail_en, detail_ar = f"Status is now: {s_en}", f"الحالة الآن: {s_ar}"
    side = ev.p.get("side_effects_not_reversed")
    if isinstance(side, list) and side:
        note_en = "Not reversed: " + ", ".join(str(s) for s in side)
        note_ar = "لم يُتراجع عن: " + "، ".join(isolate(s) for s in side)
        detail_en = f"{detail_en}. {note_en}" if detail_en else note_en
        detail_ar = f"{detail_ar}. {note_ar}" if detail_ar else note_ar
    return _d("undo", "info", en, ar, action_id=action_id, change_id=change_id, detail_en=detail_en, detail_ar=detail_ar)


@handles("bulk_action_applied")
def _bulk(ev: Ev, ctx: Ctx) -> Desc:
    approve = str(ev.p.get("decision")) == "approve"
    n = len(ev.p.get("updated") or [])
    k = len(ev.p.get("skipped") or [])
    en = f"Bulk {'approved' if approve else 'dismissed'}: {L.en_count(n, 'action')}" + (f", {k} skipped" if k else "")
    ar = f"تم {'اعتماد' if approve else 'تجاهل'} {ar_count(n, L.ACTION)} دفعة واحدة" + (f" (تم تخطي {k})" if k else "")
    reason = str(ev.p.get("reason") or "").strip()
    return _d("action", "success" if approve else "warning", en, ar, icon="check-check" if approve else "circle-x",
              detail_en=f"Reason: {reason}" if reason else None,
              detail_ar=f"السبب: {isolate(reason)}" if reason else None)


# -- notifications and integrations --

_WEBHOOK_REASON_AR = {"no WEBHOOK_URL configured": "لم يُضبط عنوان WEBHOOK_URL"}


@handles("webhook_change_detected", "webhook_impact_computed", "webhook_action_approved", "webhook_action_delegated")
def _webhook(ev: Ev, ctx: Ctx) -> Desc:
    name = str(ev.p.get("event") or ev.event.removeprefix("webhook_").replace("_", "."))
    action_id, change_id = _action_ref(ev, ctx)
    if ev.p.get("sent") is True:
        return _d("system", "success", f"Webhook sent: {name}", f"تم إرسال إشعار Webhook: {isolate(name)}", icon="send",
                  action_id=action_id, change_id=change_id)
    reason = str(ev.p.get("reason") or "")
    return _d("system", "info", f"Webhook not sent ({name}): {reason}" if reason else f"Webhook not sent ({name})",
              f"لم يُرسل إشعار Webhook ({isolate(name)}): {_WEBHOOK_REASON_AR.get(reason, isolate(reason))}" if reason
              else f"لم يُرسل إشعار Webhook ({isolate(name)})", icon="plug-zap", action_id=action_id, change_id=change_id)


@handles("digest_sent")
def _digest_sent(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    changes = len(p.get("new_critical_or_high_changes") or [])
    overdue = len(p.get("newly_overdue_actions") or [])
    note = p.get("notify_result") if isinstance(p.get("notify_result"), dict) else {}
    core_en = f"{L.en_count(changes, 'critical or high change')}, {L.en_count(overdue, 'newly overdue action')}"
    core_ar = f"عدد التغييرات الحرجة أو العالية {changes}، وعدد الإجراءات المتأخرة حديثًا {overdue}"
    if note and note.get("sent") is False:
        reason = str(note.get("reason") or "")
        return _d("export", "warning", f"Digest prepared but not delivered ({reason}): {core_en}" if reason else f"Digest prepared but not delivered: {core_en}",
                  f"تم إعداد الملخص الدوري دون تسليمه: {core_ar}", icon="send")
    return _d("export", "success", f"Digest sent: {core_en}", f"تم إرسال الملخص الدوري: {core_ar}", icon="send")


@handles("digest_skipped")
def _digest_skipped(ev: Ev, ctx: Ctx) -> Desc:
    return _d("export", "info", "Digest skipped: nothing new since the last digest",
              "تم تخطي الملخص الدوري: لا يوجد جديد منذ آخر ملخص", icon="send")


# -- agent effects on company files (COMPANY workstream) --

@handles("action_effect_applied")
def _effect_applied(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    action_id, change_id = _action_ref(ev, ctx)
    path = p.get("path")
    added, removed = _int(p.get("added")), _int(p.get("removed"))
    if path:
        en = f"Agent edited {path}"
        ar = f"عدّل الوكيل الملف {isolate(path)}"
        if added is not None and removed is not None:
            en += f": +{added} / -{removed} lines"
            ar += f": أُضيف {added} وحُذف {removed} من الأسطر"
    else:
        en, ar = "Agent applied the approved change to a company file", "طبّق الوكيل التغيير المعتمد على أحد ملفات المنشأة"
    before, after = p.get("version_before"), p.get("version_after")
    detail_en = f"Version {before} to {after}" if before is not None and after is not None else None
    detail_ar = f"من الإصدار {isolate(before)} إلى {isolate(after)}" if before is not None and after is not None else None
    return _d("effect", "success", en, ar, icon="file-pen", action_id=action_id, change_id=change_id,
              detail_en=detail_en, detail_ar=detail_ar)


@handles("action_effect_reverted")
def _effect_reverted(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    action_id, change_id = _action_ref(ev, ctx)
    path = p.get("path")
    if path:
        en, ar = f"Agent edit reverted: {path} restored", f"تم التراجع عن تعديل الوكيل: استُعيد الملف {isolate(path)}"
    else:
        en, ar = "Agent edit reverted: the company file was restored", "تم التراجع عن تعديل الوكيل: استُعيد ملف المنشأة"
    return _d("effect", "info", en, ar, icon="undo-2", action_id=action_id, change_id=change_id)


# -- ERP (ODOO workstream) --

def _erp_system(p: dict[str, Any]) -> str:
    system = str(p.get("system") or "odoo")
    return "Odoo" if system.lower() == "odoo" else system


@handles("erp_task_created")
def _erp_created(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    action_id, change_id = _action_ref(ev, ctx)
    system, task_id, who = _erp_system(p), p.get("task_id"), p.get("assignee") or p.get("assignee_name")
    if isinstance(who, dict):
        who = who.get("name")
    en = f"ERP task created in {system}" + (f": #{task_id}" if task_id else "") + (f" for {who}" if who else "")
    ar = f"تم إنشاء مهمة في نظام {isolate(system)}" + (f": رقم {isolate(task_id)}" if task_id else "") + (f" للموظف {isolate(who)}" if who else "")
    return _d("delegate", "success", en, ar, icon="send", action_id=action_id, change_id=change_id)


_DONE_STAGES = {"done", "completed", "complete", "closed", "finished"}


@handles("erp_task_synced")
def _erp_synced(ev: Ev, ctx: Ctx) -> Desc:
    p = ev.p
    action_id, change_id = _action_ref(ev, ctx)
    system, stage = _erp_system(p), p.get("stage")
    if isinstance(stage, dict):
        stage = stage.get("name")
    if stage and str(stage).lower() in _DONE_STAGES:
        return _d("confirm", "success", f"ERP task completed in {system}", f"اكتملت المهمة في نظام {isolate(system)}",
                  icon="circle-check", action_id=action_id, change_id=change_id)
    en = f"ERP task status synced from {system}" + (f": {stage}" if stage else "")
    ar = f"تمت مزامنة حالة المهمة من نظام {isolate(system)}" + (f": {isolate(stage)}" if stage else "")
    return _d("system", "info", en, ar, icon="refresh-cw", action_id=action_id, change_id=change_id)


# -- inbound webhooks --

def _webhook_received(ev: Ev, ctx: Ctx) -> Desc:
    name = ev.event.split(":", 1)[1] if ":" in ev.event else "unknown"
    verified = ev.p.get("_verified") is True
    return _d("system", "info", f"Webhook received: {name}" + (" (signature verified)" if verified else " (not signature-checked)"),
              f"تم استلام إشعار Webhook: {isolate(name)}" + (" (تم التحقق من التوقيع)" if verified else " (دون تحقق من التوقيع)"),
              icon="plug-zap")


# ── Event names for filter dropdowns ──────────────────────────────────────

EVENT_LABELS: dict[str, tuple[str, str]] = {
    "scan_requested": ("Scan requested", "طلب فحص"),
    "stage_started": ("Stage started", "بدء مرحلة"),
    "stage_completed": ("Stage completed", "اكتمال مرحلة"),
    "scan_completed": ("Scan completed", "اكتمال الفحص"),
    "scan_failed": ("Scan failed", "فشل الفحص"),
    "demo_reset": ("Demo reset", "إعادة ضبط العرض التجريبي"),
    "sources_checked": ("Sources checked", "فحص المصادر"),
    "source_ingested": ("Source ingested", "استيعاب مصدر"),
    "baseline_ingested": ("Baseline ingested", "تحميل الإصدار الأساسي"),
    "ingest_new_completed": ("Ingestion finished", "اكتمال الاستيعاب"),
    "versions_diffed": ("Versions compared", "مقارنة الإصدارات"),
    "diff_pair_completed": ("Version pair recorded", "تسجيل مقارنة زوج"),
    "diff_completed": ("Comparison finished", "اكتمال المقارنة"),
    "impact_computed": ("Impact traced", "تتبع الأثر"),
    "impact_reused": ("Impact reused", "إعادة استخدام تحليل الأثر"),
    "impact_node_completed": ("Impact stage finished", "اكتمال مرحلة الأثر"),
    "change_prioritized": ("Priority computed", "احتساب الأولوية"),
    "prioritize_completed": ("Prioritization finished", "اكتمال ترتيب الأولوية"),
    "action_created": ("Action created", "إنشاء إجراء"),
    "apply_policy_completed": ("Policy applied", "اكتمال تطبيق السياسة"),
    "action_auto_executed": ("Action auto-executed", "تنفيذ إجراء تلقائيًا"),
    "auto_execute_completed": ("Auto-execution finished", "اكتمال التنفيذ التلقائي"),
    "human_review_skipped": ("Human review skipped", "تخطي المراجعة البشرية"),
    "run_paused_for_human_review": ("Run paused for review", "إيقاف التشغيل للمراجعة"),
    "human_review_applied": ("Review decision applied", "تطبيق قرار المراجعة"),
    "run_delivered": ("Run delivered", "تسليم التشغيل"),
    "run_failed": ("Run failed", "فشل التشغيل"),
    "resume_failed": ("Resume failed", "فشل الاستئناف"),
    "action_approved": ("Action approved", "الموافقة على إجراء"),
    "action_dismissed": ("Action dismissed", "تجاهل إجراء"),
    "action_delegated": ("Action delegated", "إسناد إجراء"),
    "action_confirmed_done": ("Completion confirmed", "تأكيد الإنجاز"),
    "action_status_reverted": ("Decision undone", "التراجع عن قرار"),
    "bulk_action_applied": ("Bulk decision", "قرار جماعي"),
    "webhook_change_detected": ("Webhook: change detected", "Webhook: رصد تغيير"),
    "webhook_impact_computed": ("Webhook: impact computed", "Webhook: احتساب الأثر"),
    "webhook_action_approved": ("Webhook: action approved", "Webhook: اعتماد إجراء"),
    "webhook_action_delegated": ("Webhook: action delegated", "Webhook: إسناد إجراء"),
    "digest_sent": ("Digest sent", "إرسال الملخص الدوري"),
    "digest_skipped": ("Digest skipped", "تخطي الملخص الدوري"),
    "action_effect_applied": ("Company file edited", "تعديل ملف المنشأة"),
    "action_effect_reverted": ("Company file edit reverted", "التراجع عن تعديل ملف المنشأة"),
    "erp_task_created": ("ERP task created", "إنشاء مهمة في نظام ERP"),
    "erp_task_synced": ("ERP task synced", "مزامنة مهمة ERP"),
}


def event_label(name: str) -> tuple[str, str]:
    if name in EVENT_LABELS:
        return EVENT_LABELS[name]
    if name.startswith("webhook_received:"):
        return (f"Webhook received: {name.split(':', 1)[1]}", f"استلام Webhook: {isolate(name.split(':', 1)[1])}")
    return (L.humanize_event(name), isolate(name))


def event_kind(name: str) -> str:
    """The kind an event is reported under (probed with an empty payload)."""
    probe = Ev(0, datetime(2000, 1, 1), "", name, "", None, {})
    return describe(probe, Ctx()).kind


# ── Fallback for events the catalogue does not know ───────────────────────

_PREFIX_KIND = (
    ("scan_", "scan"), ("sources_", "scan"), ("source_", "ingest"), ("baseline_", "ingest"), ("ingest", "ingest"),
    ("versions_", "diff"), ("diff_", "diff"), ("impact_", "impact"), ("erp_", "delegate"),
    ("action_effect", "effect"), ("company_", "effect"), ("export_", "export"), ("digest_", "export"),
    ("action_", "action"),
)
_REF_AR = {"action": "إجراء", "change": "تغيير", "regulation_version": "إصدار"}


def _generic(ev: Ev, ctx: Ctx) -> Desc:
    name = ev.event
    kind = next((k for prefix, k in _PREFIX_KIND if name.startswith(prefix)), "system")
    lowered = name.lower()
    if "fail" in lowered or "error" in lowered:
        severity = "danger"
    elif "skipped" in lowered or "conflict" in lowered or "warn" in lowered:
        severity = "warning"
    elif lowered.endswith(("completed", "succeeded", "applied", "success")):
        severity = "success"
    else:
        severity = "info"
    en = f"Event recorded: {L.humanize_event(name)}"
    ar = f"حدث مسجّل: {isolate(name)}"
    if ev.ref_type and ev.ref_id is not None:
        en += f" ({ev.ref_type} #{ev.ref_id})"
        ar += f" ({_REF_AR.get(ev.ref_type) or isolate(ev.ref_type)} رقم {ev.ref_id})"
    action_id, change_id = _action_ref(ev, ctx)
    return Desc(kind=kind, severity=severity, icon=KIND_ICON[kind], en=en, ar=ar, action_id=action_id, change_id=change_id)


def describe(ev: Ev, ctx: Ctx) -> Desc:
    """One audit row to one human-readable description. Never raises for an
    unknown event; a handler that hits an unexpected payload shape degrades to
    the generic line instead of failing the whole feed."""
    handler = HANDLERS.get(ev.event)
    if handler is None and ev.event.startswith("webhook_received:"):
        handler = _webhook_received
    if handler is None:
        return _clean_desc(_generic(ev, ctx))
    try:
        return _clean_desc(handler(ev, ctx))
    except Exception:  # noqa: BLE001 - a malformed payload must not take the feed down
        return _clean_desc(_generic(ev, ctx))


def _clean_desc(d: Desc) -> Desc:
    d.en, d.ar = L.clean(d.en) or "", L.clean(d.ar) or ""
    d.detail_en, d.detail_ar = L.clean(d.detail_en), L.clean(d.detail_ar)
    return d


# ── Activity feed: noise filtering and collapsing ─────────────────────────

# Node-level "stage finished" bookkeeping rows. They duplicate the domain
# events next to them, so the feed hides them (the audit view still lists them).
NOISE_EVENTS = frozenset({
    "ingest_new_completed", "diff_pair_completed", "diff_completed", "impact_node_completed",
    "prioritize_completed", "apply_policy_completed", "auto_execute_completed",
})

FAMILY = {
    "action_created": "action_created",
    "impact_computed": "impact", "impact_reused": "impact",
    "change_prioritized": "prioritize",
    "action_auto_executed": "auto_exec",
    "action_status_reverted": "undo",
}
_FAMILY_GAP_SECONDS = {"undo": 10.0, "webhook": 30.0}


def _is_webhook_delivery(ev: Ev) -> bool:
    return ev.event.startswith("webhook_") and not ev.event.startswith("webhook_received")


def _family(ev: Ev) -> str | None:
    if _is_webhook_delivery(ev):
        return "webhook"
    return FAMILY.get(ev.event)


def _family_key(family: str, ev: Ev) -> str:
    if family in ("undo",):
        return f"{family}:{ev.actor}"
    if family == "webhook":
        return f"{family}:{ev.event}:{ev.run_id}"
    return f"{family}:{ev.run_id}"


def visible_events(evs: list[Ev], include_stages: bool = False) -> list[Ev]:
    """Oldest-to-newest list of the rows that deserve a feed line.

    Hidden: node-completion bookkeeping rows, webhook deliveries that never
    left the process (sent is not true), stage_started rows whose stage already
    completed, stage_completed rows (unless include_stages), and the
    per-action rows of a bulk decision (the bulk_action_applied row that
    follows lists exactly which ids it covered)."""
    completed_stages = {(e.run_id, _stage(e.p)[0]) for e in evs if e.event == "stage_completed"}
    suppressed: set[int] = set()
    pending: dict[tuple[str, int], list[int]] = {}
    for ev in evs:  # ascending
        if ev.event in ("action_approved", "action_dismissed") and ev.p.get("via") == "bulk" and ev.ref_id is not None:
            pending.setdefault((ev.event, ev.ref_id), []).append(ev.id)
        elif ev.event == "bulk_action_applied":
            event = "action_approved" if str(ev.p.get("decision")) == "approve" else "action_dismissed"
            for action_id in ev.p.get("updated") or []:
                ids = pending.get((event, _int(action_id)) if _int(action_id) is not None else (event, -1))
                if ids:
                    suppressed.add(ids.pop())
    out: list[Ev] = []
    for ev in evs:
        if ev.id in suppressed or ev.event in NOISE_EVENTS:
            continue
        if _is_webhook_delivery(ev) and ev.p.get("sent") is not True:
            continue
        if not include_stages:
            if ev.event == "stage_completed":
                continue
            if ev.event == "stage_started" and (ev.run_id, _stage(ev.p)[0]) in completed_stages:
                continue
        out.append(ev)
    return out


def _group_desc(family: str, group: list[Ev], descs: list[Desc]) -> Desc:
    n = len(group)
    if family == "action_created":
        levels = Counter(str(e.p.get("level") or "") for e in group)
        auto = levels.get("auto_execute", 0)
        if auto:
            en = f"{n} actions created ({n - auto} for review, {auto} auto-executable)"
            ar = f"تم إنشاء {ar_count(n, L.ACTION)} (منها {n - auto} للمراجعة و{auto} للتنفيذ التلقائي)"
        else:
            en = f"{n} actions created for review"
            ar = f"تم إنشاء {ar_count(n, L.ACTION)} للمراجعة"
        types = Counter(str(e.p.get("type") or "") for e in group if e.p.get("type"))
        detail = _first_sentence_counts(dict(types), L.ACTION_TYPE_LABEL, [k for k, _ in types.most_common(6)])
        return Desc("action", "info", "list-checks", en, ar, detail_en=detail[0] if detail else None, detail_ar=detail[1] if detail else None)
    if family == "impact":
        total = sum(_int(e.p.get("impact_count")) or 0 for e in group)
        reused = sum(1 for e in group if e.event == "impact_reused")
        detail_en = detail_ar = None
        if reused:
            detail_en = f"{reused} reused from an earlier run"
            detail_ar = f"أُعيد استخدام {reused} من تحليل سابق"
        return Desc("impact", "info", "network", f"Impact traced for {L.en_count(n, 'change')}: {total} nodes affected",
                    f"تم تتبع الأثر على {ar_count(n, L.CHANGE)}: عدد العقد المتأثرة {total}", detail_en=detail_en, detail_ar=detail_ar)
    if family == "prioritize":
        bands = Counter(str(e.p.get("band") or "") for e in group)
        detail = _first_sentence_counts(dict(bands), L.BAND_LABEL, ("critical", "high", "medium", "low"))
        sev = "warning" if bands.get("critical") else "info"
        return Desc("classify", sev, "gauge", f"Prioritized {L.en_count(n, 'change')}", f"تم ترتيب أولوية {ar_count(n, L.CHANGE)}",
                    detail_en=detail[0] if detail else None, detail_ar=detail[1] if detail else None)
    if family == "auto_exec":
        return Desc("action", "success", "check-check",
                    f"{n} actions auto-executed by policy (recorded in this database only, no external system called)",
                    f"تم تنفيذ {ar_count(n, L.ACTION)} تلقائيًا وفق السياسة (سُجّلت في قاعدة البيانات فقط دون استدعاء أي نظام خارجي)")
    if family == "undo":
        return Desc("undo", "info", "undo-2", f"Undone: {n} earlier decisions", f"تم التراجع عن {ar_count(n, DECISION)}")
    if family == "webhook":
        name = str(group[0].p.get("event") or group[0].event.removeprefix("webhook_").replace("_", "."))
        return Desc("system", "success", "send", f"{n} webhook notifications sent ({name})",
                    f"تم إرسال {ar_count(n, L.NOTIFICATION)} عبر Webhook ({isolate(name)})")
    return descs[-1]


def build_feed(evs: list[Ev], ctx: Ctx, include_stages: bool = False) -> list[dict[str, Any]]:
    """Feed entries, OLDEST first (the route reverses). `evs` must be sorted
    ascending by id. A run of rows of one collapsible family (same run or
    actor, contiguous once hidden rows are removed) becomes one entry."""
    vis = visible_events(evs, include_stages=include_stages)
    groups: list[tuple[str | None, list[Ev]]] = []
    for ev in vis:
        family = _family(ev)
        if family is not None and groups:
            last_family, last_group = groups[-1]
            if last_family == family and _family_key(family, last_group[-1]) == _family_key(family, ev):
                gap = _FAMILY_GAP_SECONDS.get(family)
                if gap is None or (ev.ts - last_group[-1].ts).total_seconds() <= gap:
                    last_group.append(ev)
                    continue
        groups.append((family, [ev]))

    entries: list[dict[str, Any]] = []
    for family, group in groups:
        descs = [describe(e, ctx) for e in group]
        newest, oldest = group[-1], group[0]
        if len(group) == 1 or family is None:
            d = descs[-1]
            ref_type, ref_id, change_id, action_id = newest.ref_type or None, newest.ref_id, d.change_id, d.action_id
            count = 1
            event = newest.event
        else:
            d = _clean_desc(_group_desc(family, group, descs))
            ref_type = ref_id = change_id = action_id = None
            count = len(group)
            event = newest.event if len({e.event for e in group}) == 1 else family
        entries.append({
            "id": newest.id, "first_id": oldest.id, "ts": newest.ts, "ts_start": oldest.ts, "kind": d.kind,
            "severity": d.severity, "icon": d.icon, "text_en": d.en, "text_ar": d.ar,
            "detail_en": d.detail_en, "detail_ar": d.detail_ar, "ref_type": ref_type, "ref_id": ref_id,
            "change_id": change_id, "action_id": action_id, "actor": newest.actor, "event": event, "count": count,
        })
    return entries

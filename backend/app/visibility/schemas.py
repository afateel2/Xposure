"""
Response models for the visibility endpoints. Kept out of routes/schemas.py
(a shared file) on purpose. Field descriptions here are the API documentation:
they show up in the OpenAPI page at /docs.

All timestamps are timezone-aware UTC ("...Z"). All user-facing text is
bilingual as `<name>_en` / `<name>_ar`.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "success", "warning", "danger"]
Kind = Literal["scan", "ingest", "diff", "classify", "impact", "action", "delegate", "confirm", "undo", "export", "system", "effect"]


# ── /overview ─────────────────────────────────────────────────────────────

class WindowOut(BaseModel):
    since_reset: bool = Field(description="True when timestamps are limited to events after the last demo_reset.")
    reset_at: datetime | None = Field(description="Time of the newest demo_reset event, or null if the demo was never reset.")


class FileIssuesOut(BaseModel):
    conflict: int = Field(description="Source files whose version label exists with different content (needs a human).")
    unrecognized: int = Field(description="Source files the agent does not know how to ingest.")


class MonitoringOut(BaseModel):
    sources_total: int = Field(description="Monitored sources (regulations in the database). Planned regulators are NOT counted here.")
    sources_ok: int = Field(description="Monitored sources whose status is `ok`.")
    sources_planned: int = Field(description="Regulators documented as planned future work. Never counted as monitored.")
    last_scan_at: datetime | None = Field(description="When the sources were last checked (sources_checked / scan_completed audit event), inside the window. Null if never.")
    last_release_detected_at: datetime | None = Field(description="When a new regulation version (one that was diffed against an earlier one) was last ingested, inside the window. Null if none.")
    mean_hours_publish_to_alert: float | None = Field(description="Mean hours from a version's regulator publication date to Xposure's first alert (first action, else first change) for it. Null when not computable (publication dates are not recorded for the ingested versions). Never estimated.")
    mean_hours_sample_size: int = Field(description="How many releases the mean is based on (0 when the mean is null).")
    stale_after_hours: int = Field(description="A monitored source not checked for longer than this is reported as `stale`.")
    file_issues: FileIssuesOut
    scope_note_en: str = Field(description="What a scan actually checks. Honest scope statement to show next to the last-scan time.")
    scope_note_ar: str


class ReviewQueueOut(BaseModel):
    total: int = Field(description="Material changes with at least one action still `pending` (awaiting a human decision).")
    critical: int = Field(description="Of total: priority band critical.")
    urgent: int = Field(description="Of total: priority band high.")
    strategic: int = Field(description="Of total: priority band medium.")
    followup: int = Field(description="Of total: priority band low.")
    awaiting_confirmation: int = Field(description="Actions delegated to a person or the ERP and not yet confirmed done (counted in actions, not changes).")
    pending_actions: int = Field(description="Actions with status `pending` (the action-level size of the queue).")
    basis_en: str
    basis_ar: str


class TasksOut(BaseModel):
    open: int = Field(description="Tasks: actions delegated to a person or the ERP (status awaiting_confirmation) until someone confirms them done.")
    due_within_5_days: int = Field(description="Of open: due today or within the next 5 days.")
    overdue: int = Field(description="Of open: due date already passed.")
    definition_en: str
    definition_ar: str


class BandMapEntry(BaseModel):
    band: str = Field(description="The app's priority band (priority.py): critical | high | medium | low.")
    review_key: str = Field(description="Key used in review_queue.")
    matrix_key: str = Field(description="Key used in priority_matrix.")
    band_label_en: str
    band_label_ar: str
    matrix_label_en: str
    matrix_label_ar: str
    meaning_en: str
    meaning_ar: str


class PriorityMatrixOut(BaseModel):
    critical: int
    quick: int
    strategic: int
    followup: int
    total: int
    basis_en: str
    basis_ar: str
    mapping: list[BandMapEntry] = Field(description="How the app's four bands map to the four dashboard quadrants.")
    all_material: dict[str, int] = Field(description="Same four keys, counted over ALL classified material changes regardless of review state.")


class RemediationOut(BaseModel):
    total_actions: int
    resolved_actions: int = Field(description="Actions whose status is approved, dismissed or done.")
    percent: float | None = Field(description="resolved / total as a percentage with one decimal; null when there are no actions.")
    by_status: dict[str, int]


class OverviewSourceOut(BaseModel):
    code: str = Field(description="Stable key: `<regulator>/<regulation>` for monitored sources (e.g. nca/ecc), `<regulator>` for planned ones.")
    regulator_code: str
    regulation_code: str | None
    name_en: str = Field(description="Regulator name.")
    name_ar: str
    title_en: str | None = Field(description="Regulation title (null for planned entries).")
    title_ar: str | None
    latest_version: str | None = Field(description="Newest ingested version label, e.g. 2-2024.")
    latest_version_ingested_at: datetime | None
    last_checked_at: datetime | None = Field(description="When a scan last covered this source, inside the window. Null for planned sources.")
    last_change_at: datetime | None = Field(description="When the newest Change for this regulation was created, inside the window.")
    open_changes: int = Field(description="Material changes with a pending action.")
    changes_total: int
    status: Literal["ok", "attention", "stale", "planned"]
    status_reason: str = Field(description="ok | conflict | overdue_actions | never_checked | not_checked_recently | planned")
    status_label_en: str
    status_label_ar: str
    planned: bool
    scope_en: str | None = None
    scope_ar: str | None = None


class OverviewOut(BaseModel):
    generated_at: datetime
    window: WindowOut
    monitoring: MonitoringOut
    review_queue: ReviewQueueOut
    tasks: TasksOut
    priority_matrix: PriorityMatrixOut
    remediation: RemediationOut
    sources: list[OverviewSourceOut]


class NewCountOut(BaseModel):
    since: datetime
    total: int = Field(description="Changes created after `since`.")
    by_band: dict[str, int] = Field(description="critical | high | medium | low")
    by_matrix: dict[str, int] = Field(description="critical | quick | strategic | followup")
    latest_created_at: datetime | None


# ── /activity, /audit, /changes/{id}/timeline ─────────────────────────────

class ActivityItemOut(BaseModel):
    id: int = Field(description="Newest audit_log id in this entry. Unique across the feed and usable as a pagination cursor.")
    first_id: int = Field(description="Oldest audit_log id in this entry (equals id for a single row). Pass as before_id to fetch older entries.")
    ts: datetime = Field(description="Time of the newest row in the entry.")
    ts_start: datetime = Field(description="Time of the oldest row in the entry.")
    kind: Kind
    severity: Severity
    icon: str = Field(description="Lucide icon name (lucide-react).")
    text_en: str
    text_ar: str
    detail_en: str | None = Field(default=None, description="Optional second line (breakdown, notification result, and so on).")
    detail_ar: str | None = None
    ref_type: str | None
    ref_id: int | None
    change_id: int | None
    action_id: int | None
    actor: str
    event: str = Field(description="Raw audit event name, or the family name for a collapsed group of mixed events.")
    count: int = Field(description="How many audit rows this entry stands for (1 for a single event, more for a collapsed group).")


class ActivityOut(BaseModel):
    items: list[ActivityItemOut] = Field(description="Newest first.")
    next_before_id: int | None = Field(description="Pass as before_id to load the next (older) page; null when there is nothing older.")
    window: WindowOut


class AuditRowOut(BaseModel):
    id: int
    ts: datetime
    actor: str
    event: str
    ref_type: str
    ref_id: int | None
    kind: Kind
    severity: Severity
    icon: str
    summary_en: str
    summary_ar: str
    payload: dict[str, Any] | None = Field(description="Raw payload_json (null when include_payload=false).")


class AuditOut(BaseModel):
    items: list[AuditRowOut] = Field(description="Newest first.")
    total: int = Field(description="Rows matching the filters, for pagination.")
    limit: int
    offset: int


class AuditEventOut(BaseModel):
    event: str
    count: int
    kind: Kind
    label_en: str
    label_ar: str


class AuditEventsOut(BaseModel):
    events: list[AuditEventOut]


class AuditActorOut(BaseModel):
    actor: str
    count: int


class AuditActorsOut(BaseModel):
    actors: list[AuditActorOut]


class TimelineItemOut(BaseModel):
    ts: datetime
    kind: Kind
    severity: Severity
    icon: str
    text_en: str
    text_ar: str
    detail_en: str | None = None
    detail_ar: str | None = None
    actor: str | None = Field(description="Who did it (null for facts derived from the change row itself).")
    action_id: int | None
    event: str = Field(description="Audit event name, or `change_detected` / `change_classified` for facts derived from the change row.")
    audit_id: int | None = Field(description="audit_log id, null for facts derived from the change row.")
    status_after: str | None = Field(default=None, description="For action transitions: the action's status after this step, when known.")


class TimelineOut(BaseModel):
    change_id: int
    change_title_en: str
    change_title_ar: str
    clause_ref: str | None
    items: list[TimelineItemOut] = Field(description="Oldest first (chronological).")


# ── /agent/state ──────────────────────────────────────────────────────────

class AgentStageOut(BaseModel):
    key: str
    label_en: str
    label_ar: str


class AgentStateOut(BaseModel):
    state: Literal["idle", "scanning", "awaiting_review", "failed"]
    since: datetime | None = Field(description="When the agent entered this state (null when unknown).")
    awaiting_count: int = Field(description="Actions with status `pending` (waiting for a human decision).")
    awaiting_changes: int = Field(description="Distinct changes those pending actions belong to.")
    awaiting_confirmation_count: int = Field(description="Delegated actions not yet confirmed done.")
    last_scan_at: datetime | None
    last_run_status: Literal["completed", "failed", "awaiting_review"] | None
    last_run_summary: dict[str, Any] | None
    last_run_at: datetime | None
    run_id: str | None
    stage: AgentStageOut | None = Field(description="While scanning: the stage in progress, when the runner reports stages.")
    stalled: bool = Field(description="True when a run started but no progress was recorded for 30 minutes (reported as state `failed`).")
    message_en: str
    message_ar: str


# ── /tasks ────────────────────────────────────────────────────────────────

class ErpOut(BaseModel):
    system: str | None = None
    task_id: Any = None
    url: str | None = None
    stage: str | None = None
    assignee: Any = None
    synced_at: str | None = None


class TaskOut(BaseModel):
    id: int
    action_type: str
    action_type_label_en: str
    action_type_label_ar: str
    level: str
    status: str
    status_label_en: str
    status_label_ar: str
    change_id: int
    change_title_en: str
    change_title_ar: str
    clause_ref: str | None
    regulator_code: str | None
    regulation_code: str | None
    priority_band: str | None = Field(description="critical | high | medium | low (recomputed, same as /changes); null if the change is unclassified.")
    priority_key: str | None = Field(description="Dashboard quadrant: critical | quick | strategic | followup.")
    priority_score: int | None
    due_date: date | None
    is_overdue: bool = Field(description="Due date passed and the action is still unresolved (pending or awaiting_confirmation).")
    days_left: int | None = Field(description="Days until due (negative when overdue); null when there is no due date.")
    assignee_name: str | None
    assignee_contact: str | None
    owner_node_name: str | None
    impact_node_name: str | None
    erp: ErpOut | None = Field(description="From Action.payload_json['erp'] when the task was escalated through the ERP.")
    effect: dict[str, Any] | None = Field(description="From Action.payload_json['effect'] (agent edit of a company file). diff_unified is omitted unless include_effect_diff=true.")
    delegated_at: datetime | None
    confirmed_at: datetime | None
    created_at: datetime
    last_event_at: datetime | None = Field(description="Newest audit row about this action (falls back to created_at).")


class TasksSummaryOut(BaseModel):
    total: int = Field(description="All actions, regardless of filters.")
    by_status: dict[str, int]
    open: int = Field(description="Tasks: actions awaiting_confirmation (same definition as /overview tasks.open).")
    due_within_5_days: int = Field(description="Of open: due within 5 days.")
    overdue: int = Field(description="Of open: past due.")
    pending_review: int = Field(description="Actions still awaiting a human decision.")
    pending_review_overdue: int = Field(description="Of pending_review: past due.")
    assigned: int = Field(description="Actions with an assignee.")


class TasksOut(BaseModel):
    items: list[TaskOut] = Field(description="Overdue first, then by due date (no due date last), then id.")
    total: int = Field(description="Rows matching the filters (for pagination).")
    limit: int
    offset: int
    summary: TasksSummaryOut

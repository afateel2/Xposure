"""
API response models for M7. Every shape returned by app/routes/*.py is
defined here and mirrored by hand into frontend/lib/types.ts (the takeoff
prompt's rule: "Pydantic models for every API contract, mirrored in
frontend/lib/types.ts"). Request bodies live next to the endpoint that
reads them (actions.py) since there is only one, trivial one.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class RegulatorOut(BaseModel):
    code: str
    name_en: str
    name_ar: str


class RegulationOut(BaseModel):
    code: str
    title_en: str
    title_ar: str


class ActionOut(BaseModel):
    id: int
    type: str
    level: str
    status: str
    due_date: date | None
    owner_node_name: str | None
    created_at: datetime
    assignee_name: str | None = None
    assignee_contact: str | None = None
    delegated_at: datetime | None = None
    confirmed_at: datetime | None = None
    can_undo: bool = False
    is_redo: bool = False
    # The agent's file edit for this action (kind "file_edit": path, versions,
    # added, removed, diff_unified, executed_at, cached), null when the approval
    # had no file effect or the edit was undone. See app/company/executor.py.
    effect: dict[str, Any] | None = None
    # The ERP (Odoo) task when this action was delegated through Odoo:
    # {system, task_id, url, stage, stage_key, assignee, synced_at}, else null.
    erp: dict[str, Any] | None = None
    # Why this action got the automation level it has: the policy level the
    # YAML requested before any gate moved it, and which gates (if any)
    # capped or floored it there. See app/policy.py's explain_automation().
    automation_requested: str | None = None
    automation_gates: list[str] | None = None
    # The written reason a reviewer gave when dismissing this action (only set
    # while its status is "dismissed"). See POST /actions/{id}/dismiss.
    dismiss_reason: str | None = None


class ImpactOut(BaseModel):
    id: int
    node_id: int
    node_type: str
    node_name: str
    scope_match: str
    depth: int
    path_summary: str
    note_en: str
    note_ar: str
    recommended_actions: list[str]
    actions: list[ActionOut]


class PriorityBreakdownOut(BaseModel):
    """priority.explain_priority()'s full arithmetic, unpacked for the UI:
    "why is this critical" without recomputing anything client-side."""
    severity_weight: float
    impact_factor: float
    deadline_factor: float
    regulator_weight: float
    raw: float
    reference_raw: float
    ungated_score: int
    gate: dict[str, Any] | None


class ChangeSummaryOut(BaseModel):
    id: int
    regulator: RegulatorOut
    regulation: RegulationOut
    old_clause_id: str | None
    new_clause_id: str | None
    clause_ref: str | None
    match_kind: str
    change_type: str | None
    material: bool | None
    confidence: float | None
    summary_en: str
    summary_ar: str
    effective_date: date | None
    grace_days: int | None
    due_date: date | None
    priority_score: int
    priority_band: str
    priority_breakdown: PriorityBreakdownOut
    days_to_effective: int | None
    is_overdue: bool
    impacted_node_count: int
    action_status_counts: dict[str, int]
    assigned_to: list[str]
    created_at: datetime


class CitationCheckOut(BaseModel):
    """Result of app/citation.py for one side (old or new) of a change:
    verified | other_page | not_found | file_changed | unavailable."""
    status: str
    page: int | None = None
    cited_page: int | None = None
    file_hash_ok: bool | None = None
    reason: str | None = None


class CitationOut(BaseModel):
    old: CitationCheckOut | None = None
    new: CitationCheckOut | None = None


class ChangeDetailOut(ChangeSummaryOut):
    match_score: float | None
    old_text_en: str | None
    old_text_ar: str | None
    new_text_en: str | None
    new_text_ar: str | None
    old_page: int | None
    new_page: int | None
    old_version_label: str | None
    new_version_label: str | None
    from_file_sha256: str
    to_file_sha256: str
    diff_ops: list[dict[str, Any]]
    impacts: list[ImpactOut]
    # Whether the clause text shown above is actually in the stored source file
    # (app/citation.py). None for clients that predate the check.
    citation: CitationOut | None = None


class SourceVersionOut(BaseModel):
    regulator: RegulatorOut
    regulation: RegulationOut
    version_label: str
    published_at: datetime | None
    effective_at: datetime | None
    source_url: str
    file_sha256: str
    ingested_at: datetime
    clause_count: int
    # Whether POST /sources/check-live is wired up for this regulator/
    # regulation pair (see app/watcher.WATCH_TARGETS); lets the Sources
    # screen show the button only where it will actually do something.
    has_live_check: bool = False


class PolicyGateOut(BaseModel):
    id: str
    description_en: str


class PolicyOut(BaseModel):
    default_level: str
    action_types: list[str]
    automation_levels: list[str]
    action_levels: dict[str, str]
    auto_executable_change_types: list[str]
    tracked_decision_change_types: list[str]
    auto_executable_action_types: list[str]
    min_auto_execute_confidence: float
    gates: list[PolicyGateOut]


class DelegateActionRequest(BaseModel):
    # Required unless channel == "odoo" (then the employee supplies it).
    assignee_name: str | None = None
    assignee_contact: str | None = None
    message: str | None = None
    # channel "odoo": create a real task in the ERP for employee_id (an Odoo
    # hr.employee id from GET /erp/employees). Default (None) keeps the
    # original name/contact/email behaviour.
    channel: Literal["odoo"] | None = None
    employee_id: int | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _require_assignee_or_employee(self) -> "DelegateActionRequest":
        if self.channel == "odoo":
            if self.employee_id is None:
                raise ValueError("employee_id is required when channel is 'odoo'")
        elif not (self.assignee_name or "").strip():
            raise ValueError("assignee_name is required")
        return self


class DismissRequest(BaseModel):
    """Body of POST /actions/{id}/dismiss. A dismissal always carries a written
    reason (checked in routes/actions.py), so the audit log answers "why was
    this not acted on?" and not only "who dismissed it"."""
    reason: str | None = None


class BulkActionRequest(BaseModel):
    action_ids: list[int]
    decision: Literal["approve", "dismiss"]
    # Required when decision == "dismiss"; ignored for approvals.
    reason: str | None = None


class BulkActionResult(BaseModel):
    updated: list[int]
    skipped: list[dict[str, Any]]  # [{"id": ..., "reason": "not pending (status=approved)"}]


class UndoResult(BaseModel):
    id: int
    status: str
    # Honest caveat: undo only ever reverts our own status record. If a
    # webhook or notification already fired for the transition being
    # undone, that delivery cannot be recalled — named here so the UI never
    # implies a full rollback that didn't happen.
    side_effects_not_reversed: list[str]
    # A file edit IS reversible, so it is reported here instead of above:
    # effect_reverted when undo restored the file, effect_reapplied when a redo
    # applied the (cached) edit again.
    effect_reverted: dict[str, Any] | None = None
    effect_reapplied: dict[str, Any] | None = None


class EvalSummaryOut(BaseModel):
    """Mirrors tests/eval_diff.py's own summary shape (app/eval_summary.py
    reads its output file directly) — always paired with sample_size on
    the frontend so a percentage is never shown without the n behind it."""
    model: str
    base_url: str | None = None
    sample_size: int
    structured_output_validity_rate: float | None = None
    avg_latency_s: float | None = None
    labeled_sample_size: int
    accuracy_on_labeled: float | None = None


class DigestStatusOut(BaseModel):
    last_digest_at: datetime | None
    last_digest_status: str | None  # "sent" | "skipped" | None (never run yet)
    last_digest_summary: dict[str, Any] | None


class AgentStatusOut(BaseModel):
    """Backed entirely by audit_log — check_sources_node/deliver_node
    already write these events on every run; this just reads the most
    recent one of each rather than inventing a new signal. The graph run
    itself does not poll the web (the live check is a separate, on-demand
    action, see app/watcher.py), so `last_checked_at` is honestly scoped: it is when the agent last scanned its local
    backend/data/sources/** drop folder, not when it last polled a
    regulator's actual website."""
    last_checked_at: datetime | None
    last_run_at: datetime | None
    last_run_status: str | None  # "delivered" | "failed" | None (no run yet)
    last_run_summary: dict[str, Any] | None
    last_baseline_ingested_at: datetime | None
    last_baseline_ingested_label: str | None  # e.g. "NCA / ECC 2-2024", for a Dashboard first-ingest banner

"""
SQLAlchemy ORM models. Built incrementally, milestone by milestone (see
docs/PLAN.md) — regulator/regulation/regulation_version/clause (M2),
change (M3), and org_node/org_edge/impact/action/audit_log (M4/M5/M6,
added together in one migration so three parallel milestones don't each
generate their own conflicting alembic revision against the same HEAD)
exist so far.

regulation_version and clause rows are immutable once written (docs/PLAN.md
section 7 / the takeoff prompt's guardrails): ingestion never updates an
existing version's clauses, it only ever inserts a new version. change rows
are similarly append-only once a diff run has produced them.

Table ownership across M4/M5/M6 (decided up front, not left ambiguous,
specifically so the three milestones could be built in parallel without
stepping on each other):
  - M4 (impact.py): OrgNode, OrgEdge, Impact.
  - M5 (priority.py/policy.py): pure functions, no new tables. Given a
    Change + impacted OrgNode count, they return a score/band and an
    automation-level decision — they do not persist anything themselves.
  - M6 (agent/graph.py): Action (the agent loop is what actually
    materializes a decision into a persisted, owned, due-dated action)
    and AuditLog. agent_checkpoint is NOT modeled here — LangGraph's own
    PostgresSaver manages its checkpoint tables via its own setup() call;
    hand-defining them here would fight that.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Regulator(Base):
    __tablename__ = "regulator"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)  # e.g. "nca"
    name_ar: Mapped[str]
    name_en: Mapped[str]
    weight: Mapped[float] = mapped_column(default=1.0)  # M5 priority formula input

    regulations: Mapped[list["Regulation"]] = relationship(back_populates="regulator")


class Regulation(Base):
    __tablename__ = "regulation"
    __table_args__ = (UniqueConstraint("regulator_id", "code", name="uq_regulation_regulator_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    regulator_id: Mapped[int] = mapped_column(ForeignKey("regulator.id"))
    code: Mapped[str]  # e.g. "ecc"
    title_ar: Mapped[str]
    title_en: Mapped[str]

    regulator: Mapped["Regulator"] = relationship(back_populates="regulations")
    versions: Mapped[list["RegulationVersion"]] = relationship(back_populates="regulation")


class RegulationVersion(Base):
    __tablename__ = "regulation_version"
    __table_args__ = (UniqueConstraint("regulation_id", "version_label", name="uq_version_regulation_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    regulation_id: Mapped[int] = mapped_column(ForeignKey("regulation.id"))
    version_label: Mapped[str]  # e.g. "1-2018", "2-2024"
    published_at: Mapped[datetime | None]
    effective_at: Mapped[datetime | None]
    source_url: Mapped[str] = mapped_column(default="")
    file_sha256: Mapped[str]
    ingested_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    regulation: Mapped["Regulation"] = relationship(back_populates="versions")
    clauses: Mapped[list["Clause"]] = relationship(back_populates="version")


class Clause(Base):
    __tablename__ = "clause"
    __table_args__ = (UniqueConstraint("version_id", "clause_id", name="uq_clause_version_clause_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("regulation_version.id"))
    clause_id: Mapped[str]  # control code as printed, e.g. "2-5-3-1" or "1.10.3.1" — see ingest.py
    parent_clause_id: Mapped[str | None]  # points at another row's clause_id within the same version, not a DB FK (parent may not exist as its own row, e.g. domain-level codes)
    text_ar: Mapped[str] = mapped_column(default="")
    text_en: Mapped[str] = mapped_column(default="")
    page_ar: Mapped[int | None]
    page_en: Mapped[int | None]
    order_index: Mapped[int]

    version: Mapped["RegulationVersion"] = relationship(back_populates="clauses")


class Change(Base):
    """One row per aligned clause pair (or unpaired new/withdrawn clause)
    between two versions of the same regulation. old_clause_id/new_clause_id
    are plain clause_id strings (not FKs to Clause.id): either can be null
    (a pure new_obligation has no old_clause_id; a pure withdrawn has no
    new_clause_id), and they're scoped by from_version_id/to_version_id
    rather than needing their own nullable FK columns for a case that's
    inherently one-sided."""
    __tablename__ = "change"

    id: Mapped[int] = mapped_column(primary_key=True)
    regulation_id: Mapped[int] = mapped_column(ForeignKey("regulation.id"))
    from_version_id: Mapped[int] = mapped_column(ForeignKey("regulation_version.id"))
    to_version_id: Mapped[int] = mapped_column(ForeignKey("regulation_version.id"))
    old_clause_id: Mapped[str | None]
    new_clause_id: Mapped[str | None]
    # how diff.py's alignment step found this pair — not the content
    # classification (that's change_type, from the LLM): "exact_id" |
    # "renumbered_candidate" (embedding-similarity fallback) | "new" |
    # "withdrawn" (no candidate on the other side at all)
    match_kind: Mapped[str]
    match_score: Mapped[float | None]  # cosine similarity, only set for renumbered_candidate

    # LLM-classified (see diff.py): new_obligation | tightened | relaxed |
    # clarification | editorial | renumbered | withdrawn
    change_type: Mapped[str | None]
    material: Mapped[bool | None]  # false for editorial/renumbered — never generates an alert (M5/M6)
    confidence: Mapped[float | None]
    summary_ar: Mapped[str] = mapped_column(default="")
    summary_en: Mapped[str] = mapped_column(default="")
    effective_date: Mapped[date | None]
    grace_days: Mapped[int | None]
    diff_spans_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class OrgNode(Base):
    """One node in the demo organization graph — product, process, policy,
    control_mapping, evidence, owner, supplier, or site (type is a plain
    string, not a DB enum, validated in application code: adding a new
    node type shouldn't require a migration). attrs_json carries
    type-specific fields (e.g. a control_mapping's control_id, an
    evidence's collected_at date) rather than a wide sparse column set."""
    __tablename__ = "org_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]
    name: Mapped[str]
    attrs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    edges_from: Mapped[list["OrgEdge"]] = relationship(foreign_keys="OrgEdge.from_id", back_populates="from_node")
    edges_to: Mapped[list["OrgEdge"]] = relationship(foreign_keys="OrgEdge.to_id", back_populates="to_node")


class OrgEdge(Base):
    """A directed relationship between two org nodes (e.g. a product
    "implements" a control_mapping, a policy "governs" a process).
    `relation` is a plain string, not an enum, for the same
    don't-require-a-migration reason as OrgNode.type."""
    __tablename__ = "org_edge"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("org_node.id"))
    to_id: Mapped[int] = mapped_column(ForeignKey("org_node.id"))
    relation: Mapped[str]

    from_node: Mapped["OrgNode"] = relationship(foreign_keys=[from_id], back_populates="edges_from")
    to_node: Mapped["OrgNode"] = relationship(foreign_keys=[to_id], back_populates="edges_to")


class Impact(Base):
    """One row per (material change, impacted org node) pair — the output
    of M4's graph traversal from a change's affected control(s) outward.
    path_json records how the traversal got there (the chain of OrgEdges),
    so the UI can show impacted-nodes-with-paths, not just a flat list."""
    __tablename__ = "impact"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change.id"))
    node_id: Mapped[int] = mapped_column(ForeignKey("org_node.id"))
    path_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    note_ar: Mapped[str] = mapped_column(default="")
    note_en: Mapped[str] = mapped_column(default="")
    # Action types (from the fixed vocabulary: update_policy,
    # update_procedure, technical_change, collect_evidence,
    # reassess_control, notify_owner, request_license_review) the LLM
    # recommended for THIS impacted node specifically — M6 turns each into
    # an Action row via policy.decide_automation(). A list, not a single
    # value: the takeoff prompt allows 1-3 recommended actions per impact.
    recommended_actions_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class Action(Base):
    """One recommended/executed action against a material change, created
    by the M6 agent loop after applying M5's automation policy — never by
    M5 itself (see the module docstring's table-ownership note). `type` is
    restricted to the fixed vocabulary the takeoff prompt specifies
    (update_policy, update_procedure, technical_change, collect_evidence,
    reassess_control, notify_owner, request_license_review), validated in
    code rather than a DB enum for the same evolvability reason as
    OrgNode.type."""
    __tablename__ = "action"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change.id"))
    type: Mapped[str]
    level: Mapped[str]  # notify_only | draft_then_approve | auto_execute
    status: Mapped[str] = mapped_column(default="pending")  # pending | approved | dismissed | awaiting_confirmation | done
    owner_node_id: Mapped[int | None] = mapped_column(ForeignKey("org_node.id"))
    due_date: Mapped[date | None]
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Delegation (pending -> awaiting_confirmation -> done via self-attested
    # confirmation, distinct from an approve/auto_execute close). Real
    # columns, not payload_json, because routes/changes.py needs to filter/
    # aggregate "assigned to" across changes.
    assignee_name: Mapped[str | None]
    assignee_contact: Mapped[str | None]
    delegated_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]


class AuditLog(Base):
    """Append-only event log for the M6 agent loop — every node in the
    LangGraph state machine writes here (check_sources, diff, impact,
    prioritize, apply_policy, human_review/auto_execute, deliver), per the
    takeoff prompt's guardrail that every step of the automated pipeline
    is traceable after the fact."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    actor: Mapped[str]  # e.g. "agent:diff_node", "user:<id>"
    event: Mapped[str]
    ref_type: Mapped[str] = mapped_column(default="")  # e.g. "change", "action"
    ref_id: Mapped[int | None]
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AppUser(Base):
    """A real, named reviewer. Added so that approvals are no longer
    attributed to one fixed actor string. Every mutating endpoint now requires one of
    these, and app/audit.py's `actor` field carries its real identity
    (`user:<email>`) instead of the old literal "user:web" placeholder.

    `role` is deliberately a two-value open vocabulary, not a permissions
    matrix: "admin" may edit the automation policy (app/policy.py's hard
    gates still apply regardless, per that module's own docstring); every
    other authenticated user is "reviewer" and may approve/dismiss/
    delegate/undo exactly as before auth existed. No multi-tenant scoping
    yet (docs/DESIGN.md's Roadmap: still out of scope) — one organization,
    several named reviewers."""
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    name_en: Mapped[str]
    name_ar: Mapped[str]
    job_title_en: Mapped[str | None]
    job_title_ar: Mapped[str | None]
    role: Mapped[str] = mapped_column(default="reviewer")  # admin | reviewer
    password_hash: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    def actor(self) -> str:
        """The string stored in AuditLog.actor and Action-mutation calls."""
        return f"user:{self.email}"


class UserSession(Base):
    """A logged-in session. The cookie carries the raw token; only its
    SHA-256 hash is stored here (the same defense-in-depth reasoning as
    never storing a plaintext password), so a leaked database row alone
    cannot be replayed as a cookie."""
    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

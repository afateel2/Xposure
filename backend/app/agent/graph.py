"""
M6 — the agent loop, as a LangGraph state machine.

    check_sources -> ingest_new -> diff -> impact -> prioritize -> apply_policy
                                                                       |
                                                    (auto_execute) <---+---> (human_review)
                                                                       |
                                                                    deliver

Run as:
  python -m app.agent.graph                       # one full pass
  python -m app.agent.graph --dry-run             # read-only: what a pass would do, no LLM, no writes
  python -m app.agent.graph --resume <thread-id> --approve 3,4 --dismiss 5

This module ORCHESTRATES; it does not re-implement. Every real decision
belongs to a module that owns it and is called from here:
  - ingestion            app.ingest.ingest()                   (M2)
  - clause diff          app.diff.run_diff()                   (M3)
  - impact traversal     app.impact.compute_impact_for_change() (M4)
  - priority             app.priority.explain_priority()        (M5)
  - automation gating    app.policy.explain_automation()        (M5)
The two tables this milestone owns are `action` (the agent loop is what
materializes a policy decision into a persisted, owned, due-dated action)
and `audit_log` — see db/models.py's table-ownership note.

Guardrails this file implements, not just respects:
  - Every node writes an audit_log row, including when it found nothing to
    do. A node that "did nothing" is itself a fact worth being able to
    prove later.
  - No silent fallback. A missing regulator PDF, an unreachable LLM, an
    action type outside the fixed vocabulary, an automation level the
    policy module doesn't recognize: all raise and abort the run, with a
    `run_failed` audit row written from a fresh session first. The loop
    never invents a classification, an impact or a decision to keep going.
  - auto_execute is honest about what it does. There is no downstream GRC
    or ERP system connected from this step (that is M8), so an auto-executed
    action is marked done and its payload records, in so many words, that
    no external system was called. It never pretends something happened
    outside this database.

Human review is a REAL LangGraph interrupt, checkpointed in Postgres via
langgraph-checkpoint-postgres, not a modelled-but-fake pause: the run
stops inside `human_review`, the process can exit, and a later call
(CLI today, M7's UI later) resumes the same thread_id with the approve /
dismiss decision and the graph carries on from where it stopped. Note the
consequence — on resume, LangGraph re-executes the interrupted node's body
from the top, so everything before the interrupt() call in that node is
kept read-only on purpose.

Deferred imports (see _load_* below): the modules this loop orchestrates
are imported inside the nodes that use them, for two reasons that both
matter here. (1) Cost: `app.ingest` pulls in sentence-transformers/torch,
measured at ~14s of import time — `--dry-run`, which only hashes files and
queries Postgres, has no business paying that. (2) Parallel construction:
M4 and M5 were being built at the same time as this milestone, so the
module had to import, and its control flow had to be testable, before
impact.py/priority.py/policy.py existed. A missing module raises a plain
ImportError at the point of use, with the real traceback — it is not
caught and turned into a fallback.
"""

import argparse
import hashlib
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, progress, webhooks
from ..config import settings
from ..db.models import (
    Action,
    Change,
    Impact,
    OrgNode,
    Regulation,
    RegulationVersion,
    Regulator,
)
from ..db.session import get_engine

# backend/app/agent/graph.py -> backend/data/sources
SOURCES_DIR = Path(__file__).resolve().parents[2] / "data" / "sources"


@dataclass(frozen=True)
class KnownSource:
    """How to ingest one recognized source document.

    `ingest()` has no auto-detection: it needs the regulator, regulation,
    version label and table convention (--code-before-text) supplied by
    the caller, because deriving them from an arbitrary PDF is a real
    problem nobody has solved here (see ingest.py's module docstring on
    why the two ECC editions cannot even be told apart by looking at a
    rendered page). So `check_sources` recognizes documents it has been
    told about, by filename, and refuses to guess at anything else.

    This is a genuine limitation of the current version, stated rather
    than papered over: dropping a NEW, unknown regulation PDF into
    data/sources/ will be DETECTED (its hash is not in the database) and
    REPORTED, but not ingested. It needs an entry here, or a manual
    `python -m app.ingest` run. Fully automated ingestion of an arbitrary
    dropped file is not supported yet.
    """

    filename: str
    regulator_code: str
    regulation_code: str
    version_label: str
    code_before_text: bool


KNOWN_SOURCES: dict[str, KnownSource] = {
    s.filename: s
    for s in [
        KnownSource(
            filename="Essential Cybersecurity Controls (ECC-1-2018).pdf",
            regulator_code="nca",
            regulation_code="ecc",
            version_label="1-2018",
            code_before_text=False,  # text-before-code table convention
        ),
        KnownSource(
            filename="Essential Cybersecurity Controls (ECC-2-2024).pdf",
            regulator_code="nca",
            regulation_code="ecc",
            version_label="2-2024",
            code_before_text=True,  # code-before-text table convention
        ),
    ]
}

# The fixed action vocabulary from the takeoff prompt (section 3 / M4).
# M4's impact.py owns validating what the LLM is allowed to RECOMMEND;
# this copy is a second check at the point of PERSISTENCE, because an
# Action row with a type outside the vocabulary would quietly break both
# the policy matrix and the UI downstream. Duplicating seven strings is
# cheaper than importing M4 just for a constant, and a mismatch between
# the two lists fails loudly here rather than being written to the table.
ACTION_VOCABULARY = {
    "update_policy",
    "update_procedure",
    "technical_change",
    "collect_evidence",
    "reassess_control",
    "notify_owner",
    "request_license_review",
}

AUTOMATION_LEVELS = {"notify_only", "draft_then_approve", "auto_execute"}


# ── Deferred imports of the modules this loop orchestrates ────────────────
# See the module docstring for why these are functions rather than
# top-level imports. They are also the single seam the unit tests patch,
# which keeps the tests honest: they replace exactly one function each,
# not a whole import graph.

def _load_ingest() -> Callable[..., None]:
    from ..ingest import ingest

    return ingest


def _load_run_diff() -> Callable[..., None]:
    from ..diff import run_diff

    return run_diff


def _load_compute_impact() -> Callable[[Session, Change], list[Impact]]:
    from ..impact import compute_impact_for_change

    return compute_impact_for_change


def _load_explain_priority() -> Callable[..., dict[str, Any]]:
    from ..priority import explain_priority

    return explain_priority


def _load_explain_automation() -> Callable[..., dict[str, Any]]:
    from ..policy import explain_automation

    return explain_automation


# ── State ─────────────────────────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    """One pass of the loop. Everything here is checkpointed to Postgres
    between nodes, so it must stay JSON/msgpack-serializable: ids and
    plain dicts, never ORM objects or datetimes."""

    run_id: str
    started_at: str

    # check_sources / ingest_new
    sources: list[dict[str, Any]]
    new_files: list[dict[str, Any]]
    ingested: list[dict[str, Any]]

    # diff
    diffed_pairs: list[dict[str, Any]]

    # impact / prioritize / apply_policy
    change_ids: list[int]
    impacted: list[dict[str, Any]]
    priorities: dict[str, dict[str, Any]]  # str(change_id) -> {score, band}
    action_ids: list[int]
    auto_executable_action_ids: list[int]
    review_action_ids: list[int]

    # human_review / auto_execute
    auto_executed_action_ids: list[int]
    review_decision: dict[str, Any]

    summary: dict[str, Any]


# ── Small shared helpers ──────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    """Same hash ingest.py stores in RegulationVersion.file_sha256 —
    SHA-256 over the whole file. Read in chunks: source PDFs are only a
    couple of MB today, but a hash function has no reason to assume that."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version_sort_key(label: str) -> tuple[tuple[int, ...], str]:
    """Order version labels by their numeric segments ("1-2018" before
    "2-2024"), falling back to the raw string so labels with no digits
    still have a stable, total order rather than comparing equal."""
    numbers = tuple(int(n) for n in re.findall(r"\d+", label))
    return (numbers, label)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _due_date(change: Change) -> date | None:
    """A compliance deadline is only ever taken from what the regulator
    actually published: the effective date the LLM extracted (and only
    when it was stated explicitly — see llm.py's prompt), plus the stated
    grace period if there is one. No effective date means no due date.
    Inventing a plausible-looking deadline would be exactly the kind of
    fabrication the project's guardrails exist to prevent."""
    if change.effective_date is None:
        return None
    if change.grace_days:
        return change.effective_date + timedelta(days=change.grace_days)
    return change.effective_date


def _clause_ref(change: Change) -> str | None:
    return change.new_clause_id or change.old_clause_id


def _regulator_weight(db: Session, change: Change, cache: dict[int, float]) -> float:
    """The `regulator.weight` behind a change, for M5's priority formula.

    Raises rather than defaulting to 1.0 if it cannot be resolved: a
    silently-assumed weight would change every score downstream while
    still looking like a real number."""
    if change.regulation_id in cache:
        return cache[change.regulation_id]
    weight = db.scalar(
        select(Regulator.weight)
        .join(Regulation, Regulation.regulator_id == Regulator.id)
        .where(Regulation.id == change.regulation_id)
    )
    if weight is None:
        raise ValueError(
            f"Could not resolve a regulator weight for change {change.id} "
            f"(regulation_id={change.regulation_id}): refusing to assume one."
        )
    cache[change.regulation_id] = float(weight)
    return cache[change.regulation_id]


# ── check_sources ─────────────────────────────────────────────────────────

def detect_new_sources(db: Session) -> list[dict[str, Any]]:
    """Hash every file under backend/data/sources/** and compare against
    the RegulationVersion.file_sha256 values already in Postgres.

    This node detects file drops only; it does not poll the web. The
    separate on-demand live check against a regulator's own page lives in
    app/watcher.py.

    Status per file:
      already_ingested  this exact byte content is in the database
      new               recognized filename, content not yet ingested
      conflict          recognized filename, content not ingested, but its
                        version label already exists with DIFFERENT bytes.
                        regulation_version rows are immutable (M2), so this
                        is never re-ingested automatically: either the
                        regulator republished the document under the same
                        label, or someone edited the file. Both need a
                        human, and both are the sort of thing that must
                        not be quietly overwritten.
      unrecognized      content not ingested and the filename is not in
                        KNOWN_SOURCES — detected and reported, never
                        guessed at (see KnownSource's docstring).
    """
    if not SOURCES_DIR.is_dir():
        raise SystemExit(
            f"Source directory not found: {SOURCES_DIR}\n"
            f"Create it and place regulation PDFs there (see docs/PLAN.md section 1)."
        )

    ingested_by_hash = {
        v.file_sha256: v for v in db.scalars(select(RegulationVersion))
    }

    found: list[dict[str, Any]] = []
    for path in sorted(p for p in SOURCES_DIR.rglob("*") if p.is_file()):
        file_hash = _sha256(path)
        entry: dict[str, Any] = {
            "path": path.relative_to(SOURCES_DIR).as_posix(),
            "sha256": file_hash,
        }

        existing = ingested_by_hash.get(file_hash)
        if existing is not None:
            entry.update(
                status="already_ingested",
                version_id=existing.id,
                version_label=existing.version_label,
            )
            found.append(entry)
            continue

        known = KNOWN_SOURCES.get(path.name)
        if known is None:
            entry["status"] = "unrecognized"
            found.append(entry)
            continue

        label_taken = _find_version(db, known.regulator_code, known.regulation_code, known.version_label)
        entry.update(
            status="conflict" if label_taken is not None else "new",
            regulator=known.regulator_code,
            regulation=known.regulation_code,
            version_label=known.version_label,
        )
        if label_taken is not None:
            entry["existing_version_sha256"] = label_taken.file_sha256
        found.append(entry)

    return found


def _find_version(
    db: Session, regulator_code: str, regulation_code: str, version_label: str
) -> RegulationVersion | None:
    return db.scalar(
        select(RegulationVersion)
        .join(Regulation, Regulation.id == RegulationVersion.regulation_id)
        .join(Regulator, Regulator.id == Regulation.regulator_id)
        .where(
            Regulator.code == regulator_code,
            Regulation.code == regulation_code,
            RegulationVersion.version_label == version_label,
        )
    )


def check_sources_node(state: AgentState) -> dict[str, Any]:
    with Session(get_engine()) as db:
        sources = detect_new_sources(db)
        new_files = [s for s in sources if s["status"] == "new"]
        counts = _count_by(sources, "status")
        print(f"[check_sources] {len(sources)} file(s) under {SOURCES_DIR}: {counts}")
        for s in sources:
            if s["status"] in ("conflict", "unrecognized"):
                print(f"  [attention] {s['status']}: {s['path']}")

        audit.record(
            db,
            actor=audit.node_actor("check_sources"),
            event="sources_checked",
            payload={
                "run_id": state.get("run_id"),
                "sources_dir": str(SOURCES_DIR),
                "counts": counts,
                "files": sources,
            },
        )
    return {"sources": sources, "new_files": new_files}


# ── ingest_new ────────────────────────────────────────────────────────────

def ingest_new_node(state: AgentState) -> dict[str, Any]:
    """
    Each file's audit record is written and committed immediately after
    its own ingest() call succeeds — not deferred to a pass over every
    file in this run, once the whole loop finishes. Same bug class as
    diff_node's (see _record_pair_diffed's docstring for the full
    reasoning): ingest() commits a file's RegulationVersion/Clause rows
    itself, in its own transaction, the moment it succeeds. If a *later*
    file in the same batch then failed to ingest (a malformed PDF, a
    conflicting version label), the earlier file's rows used to stay
    committed with no audit_log row at all — and on retry,
    detect_new_sources() would correctly report it as "already_ingested"
    (it checks file_sha256, not the audit log) and silently never surface
    that it has no ingestion record. Not exercised by today's one-or-two-
    file-per-run corpus, but a live gap the moment a run drops multiple
    new source files at once. See docs/PLAN.md's bulletproofing section.
    """
    new_files = state.get("new_files") or []
    ingested: list[dict[str, Any]] = []

    if new_files:
        ingest = _load_ingest()
        for entry in new_files:
            known = KNOWN_SOURCES[Path(entry["path"]).name]
            path = SOURCES_DIR / entry["path"]
            print(f"[ingest_new] ingesting {entry['path']} as {known.regulator_code}/{known.regulation_code}/{known.version_label}")

            # Checked BEFORE ingest() so it reflects the count prior to
            # this file — used below to detect a true first-ever version
            # (nothing to diff against yet, so diff_node will never
            # produce a Change for it) and say so explicitly rather than
            # leaving that as silence for the Dashboard to guess at.
            with Session(get_engine()) as db:
                prior_version_count = db.scalar(
                    select(func.count())
                    .select_from(RegulationVersion)
                    .join(Regulation, Regulation.id == RegulationVersion.regulation_id)
                    .join(Regulator, Regulator.id == Regulation.regulator_id)
                    .where(Regulator.code == known.regulator_code, Regulation.code == known.regulation_code)
                )

            # No try/except: a failed ingestion must abort the run (the
            # runner records run_failed), not leave a half-ingested
            # version behind while the loop marches on to diff it.
            ingest(
                known.regulator_code,
                known.regulation_code,
                known.version_label,
                path,
                code_before_text=known.code_before_text,
                replace=False,
            )
            row = {
                "path": entry["path"],
                "sha256": entry["sha256"],
                "regulator": known.regulator_code,
                "regulation": known.regulation_code,
                "version_label": known.version_label,
            }
            ingested.append(row)

            with Session(get_engine()) as db:
                version = _find_version(db, row["regulator"], row["regulation"], row["version_label"])
                row["version_id"] = version.id if version else None
                audit.record(
                    db,
                    actor=audit.node_actor("ingest_new"),
                    event="source_ingested",
                    ref_type="regulation_version",
                    ref_id=row["version_id"],
                    payload={"run_id": state.get("run_id"), **row},
                )
                if prior_version_count == 0:
                    audit.record(
                        db,
                        actor=audit.node_actor("ingest_new"),
                        event="baseline_ingested",
                        ref_type="regulation_version",
                        ref_id=row["version_id"],
                        payload={
                            "run_id": state.get("run_id"),
                            **row,
                            "note": "no prior version to diff against yet",
                        },
                    )

    with Session(get_engine()) as db:
        skipped = [
            s for s in (state.get("sources") or []) if s["status"] in ("conflict", "unrecognized")
        ]
        audit.record(
            db,
            actor=audit.node_actor("ingest_new"),
            event="ingest_new_completed",
            payload={
                "run_id": state.get("run_id"),
                "ingested_count": len(ingested),
                "ingested": ingested,
                # Surfaced rather than dropped: these files exist, are not
                # in the database, and were not ingested. Whoever reads
                # the audit trail should be able to see that without
                # having to notice an absence.
                "needs_manual_attention": skipped,
            },
        )

    print(f"[ingest_new] ingested {len(ingested)} new version(s)")
    return {"ingested": ingested}


# ── diff ──────────────────────────────────────────────────────────────────

def pending_diff_pairs(db: Session) -> list[dict[str, Any]]:
    """Consecutive version pairs of the same regulation that are both
    ingested but have no Change rows yet.

    Consecutive-only, not every combination: a diff of 1-2018 -> 2-2024 is
    what a compliance officer asked for; 1-2018 -> 3-2029 skipping an
    edition in between is not, and would double-count the same obligations
    once a third version exists."""
    pairs: list[dict[str, Any]] = []
    for regulation in db.scalars(select(Regulation)):
        regulator = db.get(Regulator, regulation.regulator_id)
        versions = sorted(
            db.scalars(
                select(RegulationVersion).where(RegulationVersion.regulation_id == regulation.id)
            ),
            key=lambda v: _version_sort_key(v.version_label),
        )
        for older, newer in zip(versions, versions[1:]):
            already = db.scalar(
                select(func.count())
                .select_from(Change)
                .where(Change.from_version_id == older.id, Change.to_version_id == newer.id)
            )
            if already:
                continue
            pairs.append(
                {
                    "regulator": regulator.code,
                    "regulation": regulation.code,
                    "from_label": older.version_label,
                    "to_label": newer.version_label,
                    "from_version_id": older.id,
                    "to_version_id": newer.id,
                }
            )
    return pairs


def _record_pair_diffed(db: Session, state: AgentState, pair: dict[str, Any]) -> None:
    """Audit trail + webhook notification for one already-run_diff'd pair.

    Deliberately called once per pair, immediately after that pair's
    run_diff() call returns, inside diff_node's own per-pair loop — NOT
    deferred to a second pass over every pair processed in the run. A
    real bug lived in that deferred version, found while stress-testing
    the agent's resumability rather than assumed away: run_diff() commits
    a pair's Change rows itself, in its own transaction (see app/diff.py),
    the moment it succeeds. If a *second* pending pair then failed (a
    flaky LLM call, say) before the old code's deferred audit/webhook pass
    ever ran, the first pair's Change rows were left permanently committed
    with NO audit_log row and NO change.detected webhook ever sent — and
    pending_diff_pairs() would skip that pair as "already diffed" on
    every future run, forever, since it only looks at whether Change rows
    exist. The fix is exactly this: make each pair's full unit of work
    (diff + audit + webhook) durable together, in the same loop iteration
    that ran it, so a later pair's failure can never retroactively erase
    an earlier pair's audit trail. Not exercised by today's single-pair
    corpus (one regulation, one version pair) — the code already supports
    multiple regulations/pairs per run, so this was a live gap, not a
    hypothetical one. See docs/PLAN.md's bulletproofing section.
    """
    total = db.scalar(
        select(func.count())
        .select_from(Change)
        .where(
            Change.from_version_id == pair["from_version_id"],
            Change.to_version_id == pair["to_version_id"],
        )
    )
    material_changes = list(
        db.scalars(
            select(Change).where(
                Change.from_version_id == pair["from_version_id"],
                Change.to_version_id == pair["to_version_id"],
                Change.material.is_(True),
            )
        )
    )
    pair["change_count"] = total
    pair["material_count"] = len(material_changes)
    audit.record(
        db,
        actor=audit.node_actor("diff"),
        event="versions_diffed",
        ref_type="regulation_version",
        ref_id=pair["to_version_id"],
        payload={"run_id": state.get("run_id"), **pair},
        commit=False,
    )

    # M8: notify a configured downstream system of every material change
    # this pair just detected. Best-effort (webhooks.py never raises) — a
    # webhook receiver being down must not fail a diff run, so the result
    # is only ever recorded, never branched on.
    for change in material_changes:
        result = webhooks.send_webhook(
            "change.detected",
            {
                "change_id": change.id,
                "regulation_id": change.regulation_id,
                "old_clause_id": change.old_clause_id,
                "new_clause_id": change.new_clause_id,
                "change_type": change.change_type,
                "confidence": change.confidence,
                "summary_en": change.summary_en,
            },
        )
        audit.record(
            db,
            actor=audit.node_actor("diff"),
            event="webhook_change_detected",
            ref_type="change",
            ref_id=change.id,
            payload={"run_id": state.get("run_id"), **result},
            commit=False,
        )

    # Commits here (this call has no commit=False), so this pair's audit
    # trail and webhook records land in the database together, in one
    # transaction, before diff_node ever moves on to the next pair.
    audit.record(
        db,
        actor=audit.node_actor("diff"),
        event="diff_pair_completed",
        ref_type="regulation_version",
        ref_id=pair["to_version_id"],
        payload={"run_id": state.get("run_id"), **pair},
    )


def diff_node(state: AgentState) -> dict[str, Any]:
    with Session(get_engine()) as db:
        pairs = pending_diff_pairs(db)

    diffed: list[dict[str, Any]] = []
    if pairs:
        run_diff = _load_run_diff()
        for pair in pairs:
            print(f"[diff] {pair['regulator']}/{pair['regulation']}: {pair['from_label']} -> {pair['to_label']}")
            # Calls the LLM (classification) — an unreachable model raises
            # here and aborts the run. That is the intended behaviour: a
            # diff with unclassified changes is not a partial success.
            run_diff(
                pair["regulator"],
                pair["regulation"],
                pair["from_label"],
                pair["to_label"],
                dry_run=False,
                replace=False,
            )
            diffed.append(pair)

            with Session(get_engine()) as db:
                _record_pair_diffed(db, state, pair)

    with Session(get_engine()) as db:
        audit.record(
            db,
            actor=audit.node_actor("diff"),
            event="diff_completed",
            payload={"run_id": state.get("run_id"), "pairs_diffed": len(diffed), "pairs": diffed},
        )

    print(f"[diff] diffed {len(diffed)} version pair(s)")
    return {"diffed_pairs": diffed}


# ── impact ────────────────────────────────────────────────────────────────

def changes_needing_action(db: Session) -> list[Change]:
    """Material changes that have no Action rows yet — the work queue for
    the impact/prioritize/apply_policy leg of the loop.

    Keyed on "has no actions" rather than "was diffed in this run" so the
    loop is self-healing: a run that died between diff and apply_policy
    leaves changes that the next run picks up, instead of changes that are
    silently never acted on. Editorial/renumbered changes (material=False)
    are excluded here, which is the takeoff prompt's rule that they never
    generate an alert."""
    acted_on = select(Action.change_id).distinct().scalar_subquery()
    return list(
        db.scalars(
            select(Change)
            .where(Change.material.is_(True), Change.id.notin_(acted_on))
            .order_by(Change.id)
        )
    )


def impact_node(state: AgentState) -> dict[str, Any]:
    with Session(get_engine()) as db:
        changes = changes_needing_action(db)
        change_ids = [c.id for c in changes]
        impacted: list[dict[str, Any]] = []

        compute_impact_for_change = _load_compute_impact() if changes else None
        progress.emit("impact.started", total=len(changes))
        for change_index, change in enumerate(changes, 1):
            existing = list(db.scalars(select(Impact).where(Impact.change_id == change.id)))
            if existing:
                # Already traversed on an earlier run — reuse it rather
                # than paying for M4's impact-note LLM call twice and
                # writing a second set of Impact rows for the same change.
                impacts = existing
                recomputed = False
            else:
                impacts = compute_impact_for_change(db, change)
                recomputed = True

            row = {
                "change_id": change.id,
                "clause_id": _clause_ref(change),
                "impact_count": len(impacts),
                "node_ids": [i.node_id for i in impacts],
                "recomputed": recomputed,
            }
            impacted.append(row)
            progress.emit(
                "impact.change_done", index=change_index, total=len(changes), change_id=change.id,
                impact_count=row["impact_count"], recomputed=recomputed,
            )
            audit.record(
                db,
                actor=audit.node_actor("impact"),
                event="impact_computed" if recomputed else "impact_reused",
                ref_type="change",
                ref_id=change.id,
                payload={"run_id": state.get("run_id"), **row},
                commit=False,
            )

            # M8: only for freshly-computed impacts, matching the same
            # "don't double up on a reused result" reasoning already
            # applied above to the LLM call itself.
            if recomputed and row["impact_count"] > 0:
                result = webhooks.send_webhook("impact.computed", row)
                audit.record(
                    db,
                    actor=audit.node_actor("impact"),
                    event="webhook_impact_computed",
                    ref_type="change",
                    ref_id=change.id,
                    payload={"run_id": state.get("run_id"), **result},
                    commit=False,
                )

        audit.record(
            db,
            actor=audit.node_actor("impact"),
            event="impact_node_completed",
            payload={
                "run_id": state.get("run_id"),
                "changes_considered": len(changes),
                "impact_rows": sum(r["impact_count"] for r in impacted),
            },
        )

    print(f"[impact] {len(change_ids)} material change(s) needing action; {sum(r['impact_count'] for r in impacted)} impacted node(s)")
    return {"change_ids": change_ids, "impacted": impacted}


# ── prioritize ────────────────────────────────────────────────────────────

def prioritize_node(state: AgentState) -> dict[str, Any]:
    change_ids = state.get("change_ids") or []
    priorities: dict[str, dict[str, Any]] = {}

    with Session(get_engine()) as db:
        explain_priority = _load_explain_priority() if change_ids else None
        today = date.today()
        weights: dict[int, float] = {}
        for change_id in change_ids:
            change = db.get(Change, change_id)
            impacted_node_count = db.scalar(
                select(func.count()).select_from(Impact).where(Impact.change_id == change_id)
            )
            days_to_effective = (
                (change.effective_date - today).days if change.effective_date else None
            )
            breakdown = explain_priority(
                change,
                impacted_node_count,
                days_to_effective,
                # explain_priority() stays a pure function by taking the
                # regulator weight as an argument rather than lazy-loading
                # it off the relationship; resolving it is the caller's
                # job, and the caller (this node) is the one holding a
                # session. Cached per regulation: one run diffs at most a
                # handful of regulations, each with one regulator.
                regulator_weight=_regulator_weight(db, change, weights),
            )
            score, band = breakdown["score"], breakdown["band"]
            if not isinstance(score, int) or not (0 <= score <= 100):
                raise ValueError(
                    f"priority.explain_priority returned an out-of-range score {score!r} "
                    f"for change {change_id}: priority must be a deterministic 0-100 integer."
                )
            priorities[str(change_id)] = {
                "score": score,
                "band": band,
                "impacted_node_count": impacted_node_count,
                "days_to_effective": days_to_effective,
                # The full factor breakdown, so the Changes UI's "why this
                # priority" panel and the audit trail below read the same
                # numbers without recomputing them.
                "breakdown": breakdown,
            }
            audit.record(
                db,
                actor=audit.node_actor("prioritize"),
                event="change_prioritized",
                ref_type="change",
                ref_id=change_id,
                payload={"run_id": state.get("run_id"), **breakdown},
                commit=False,
            )

        audit.record(
            db,
            actor=audit.node_actor("prioritize"),
            event="prioritize_completed",
            payload={
                "run_id": state.get("run_id"),
                "changes_prioritized": len(priorities),
                "bands": _count_by(list(priorities.values()), "band"),
            },
        )

    print(f"[prioritize] scored {len(priorities)} change(s): {_count_by(list(priorities.values()), 'band')}")
    return {"priorities": priorities}


# ── apply_policy ──────────────────────────────────────────────────────────

def apply_policy_node(state: AgentState) -> dict[str, Any]:
    """Turn each Impact's recommended actions into persisted Action rows,
    with M5's policy deciding the automation level of each.

    The (change, impacted node, action type) triple is the unit of
    de-duplication. `action` has no impact_id column (see db/models.py), so
    the impacted node id lives in payload_json and is read back from there
    — which also means the UI can show which node an action came from."""
    change_ids = state.get("change_ids") or []
    priorities = state.get("priorities") or {}
    created: list[dict[str, Any]] = []

    with Session(get_engine()) as db:
        explain_automation = _load_explain_automation() if change_ids else None
        for change_id in change_ids:
            change = db.get(Change, change_id)
            existing_keys = {
                (a.type, (a.payload_json or {}).get("impact_node_id"))
                for a in db.scalars(select(Action).where(Action.change_id == change_id))
            }

            for impact in db.scalars(select(Impact).where(Impact.change_id == change_id)):
                for action_type in impact.recommended_actions_json or []:
                    if action_type not in ACTION_VOCABULARY:
                        raise ValueError(
                            f"Impact {impact.id} (change {change_id}) recommends action type "
                            f"{action_type!r}, which is not in the fixed action vocabulary "
                            f"{sorted(ACTION_VOCABULARY)}. Refusing to persist it."
                        )
                    if (action_type, impact.node_id) in existing_keys:
                        continue

                    automation = explain_automation(
                        action_type, change.change_type, change.confidence
                    )
                    level = automation["level"]
                    if level not in AUTOMATION_LEVELS:
                        raise ValueError(
                            f"policy.explain_automation returned an unknown automation level "
                            f"{level!r} for ({action_type}, {change.change_type}). "
                            f"Expected one of {sorted(AUTOMATION_LEVELS)}."
                        )

                    node = db.get(OrgNode, impact.node_id)
                    action = Action(
                        change_id=change_id,
                        type=action_type,
                        level=level,
                        status="pending",
                        # Only set when the impacted node IS an owner.
                        # Resolving "who owns this product/process" is a
                        # graph question that belongs to M4's edge
                        # semantics, and a guessed owner is worse than a
                        # null one: it puts a real person's name on an
                        # obligation that was never theirs.
                        owner_node_id=impact.node_id if node is not None and node.type == "owner" else None,
                        due_date=_due_date(change),
                        payload_json={
                            "run_id": state.get("run_id"),
                            "impact_id": impact.id,
                            "impact_node_id": impact.node_id,
                            "impact_node_type": node.type if node else None,
                            "impact_node_name": node.name if node else None,
                            "clause_id": _clause_ref(change),
                            "change_type": change.change_type,
                            "confidence": change.confidence,
                            # priority has no column on `change` in the
                            # shared schema, so the score travels with the
                            # action (and the audit trail) instead — see
                            # this file's report notes on that gap.
                            "priority_score": priorities.get(str(change_id), {}).get("score"),
                            "priority_band": priorities.get(str(change_id), {}).get("band"),
                            "priority_breakdown": priorities.get(str(change_id), {}).get("breakdown"),
                            "decided_by": "policy.explain_automation",
                            # Which gates moved the automation level away from what the
                            # policy YAML requested, and why (empty list = granted as written).
                            "automation_requested": automation["requested"],
                            "automation_gates": automation["gates"],
                        },
                    )
                    db.add(action)
                    db.flush()
                    existing_keys.add((action_type, impact.node_id))
                    created.append(
                        {
                            "action_id": action.id,
                            "change_id": change_id,
                            "type": action_type,
                            "level": level,
                            "impact_node_id": impact.node_id,
                        }
                    )
                    audit.record(
                        db,
                        actor=audit.node_actor("apply_policy"),
                        event="action_created",
                        ref_type="action",
                        ref_id=action.id,
                        payload={"run_id": state.get("run_id"), **created[-1]},
                        commit=False,
                    )

        by_level = _count_by(created, "level")
        audit.record(
            db,
            actor=audit.node_actor("apply_policy"),
            event="apply_policy_completed",
            payload={
                "run_id": state.get("run_id"),
                "actions_created": len(created),
                "by_level": by_level,
            },
        )

    auto_ids = [c["action_id"] for c in created if c["level"] == "auto_execute"]
    review_ids = [c["action_id"] for c in created if c["level"] != "auto_execute"]
    print(f"[apply_policy] created {len(created)} action(s): {by_level}")
    return {
        "action_ids": [c["action_id"] for c in created],
        "auto_executable_action_ids": auto_ids,
        "review_action_ids": review_ids,
    }


# ── auto_execute ──────────────────────────────────────────────────────────

def auto_execute_node(state: AgentState) -> dict[str, Any]:
    """Close out the actions M5's policy cleared for automation.

    "Executed" here means exactly one thing: the action is recorded as
    done in this database. No GRC or ERP system is connected from this
    step (the outbound webhook/export integrations are M8), so the
    action's payload and its audit row both say so explicitly. An agent
    that logged "executed" while nothing left the process would be lying
    to the compliance officer who reads the trail later."""
    action_ids = state.get("auto_executable_action_ids") or []
    executed: list[int] = []

    with Session(get_engine()) as db:
        for action_id in action_ids:
            action = db.get(Action, action_id)
            if action is None or action.status != "pending":
                continue
            previous = action.status
            action.status = "done"
            # payload_json is a plain JSON column, not a MutableDict:
            # reassigning is what marks it dirty. Mutating in place would
            # silently not persist.
            action.payload_json = {
                **(action.payload_json or {}),
                "auto_executed_at": _utc_now_iso(),
                "executed_by": audit.node_actor("auto_execute"),
                "external_effect": "none: no downstream GRC/ERP system is connected from this step",
            }
            executed.append(action_id)
            audit.record(
                db,
                actor=audit.node_actor("auto_execute"),
                event="action_auto_executed",
                ref_type="action",
                ref_id=action_id,
                payload={
                    "run_id": state.get("run_id"),
                    "change_id": action.change_id,
                    "type": action.type,
                    "level": action.level,
                    "previous_status": previous,
                    "via": "auto_execute",
                    # No external system was ever called (see this node's
                    # own docstring) — an auto-executed action is therefore
                    # always 100% safely undoable, unlike an approve that
                    # already fired a webhook. Undo/UI can rely on this.
                    "external_effect": "none: recorded in this database only",
                },
                commit=False,
            )

        audit.record(
            db,
            actor=audit.node_actor("auto_execute"),
            event="auto_execute_completed",
            payload={
                "run_id": state.get("run_id"),
                "executed_count": len(executed),
                "action_ids": executed,
            },
        )

    print(f"[auto_execute] closed {len(executed)} action(s) (recorded in the database only: no external system)")
    return {"auto_executed_action_ids": executed}


# ── human_review (the real interrupt) ─────────────────────────────────────

def human_review_node(state: AgentState) -> dict[str, Any]:
    """Pause the run until a human approves or dismisses the pending
    actions.

    LangGraph re-executes this node's body from the top when the run is
    resumed, so everything BEFORE interrupt() is read-only by design: it
    rebuilds the same payload from the database, then interrupt() returns
    the decision instead of pausing again. Everything after the call runs
    exactly once, on resume.

    Scope is the actions created by THIS run. Actions left pending by an
    earlier run are reported in `deliver`'s summary but do not block —
    the interrupt is a gate on the work this pass produced, not a global
    inbox. The global inbox is M7's UI, which approves/dismisses through
    the API rather than by resuming a graph thread."""
    candidate_ids = state.get("review_action_ids") or []

    with Session(get_engine()) as db:
        pending = [
            a
            for a in db.scalars(select(Action).where(Action.id.in_(candidate_ids)))
            if a.status == "pending"
        ] if candidate_ids else []
        awaiting = [
            {
                "action_id": a.id,
                "change_id": a.change_id,
                "type": a.type,
                "level": a.level,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "priority_band": (a.payload_json or {}).get("priority_band"),
                "priority_score": (a.payload_json or {}).get("priority_score"),
                "clause_id": (a.payload_json or {}).get("clause_id"),
                "impact_node_name": (a.payload_json or {}).get("impact_node_name"),
            }
            for a in sorted(pending, key=lambda a: a.id)
        ]

    if not awaiting:
        with Session(get_engine()) as db:
            audit.record(
                db,
                actor=audit.node_actor("human_review"),
                event="human_review_skipped",
                payload={"run_id": state.get("run_id"), "reason": "no pending actions in this run"},
            )
        print("[human_review] nothing pending: not pausing")
        return {"review_decision": {"approved": [], "dismissed": []}}

    decision = interrupt(
        {
            "kind": "human_review",
            "run_id": state.get("run_id"),
            "awaiting": awaiting,
            "resume_with": {
                "approved": "[action_id, ...]",
                "dismissed": "[action_id, ...]",
            },
        }
    )

    # ---- only reached after the run is resumed ----
    approved, dismissed = _validate_decision(decision, {a["action_id"] for a in awaiting})

    with Session(get_engine()) as db:
        for action_id, status in [(i, "approved") for i in approved] + [(i, "dismissed") for i in dismissed]:
            action = db.get(Action, action_id)
            previous = action.status
            action.status = status
            audit.record(
                db,
                actor="user:cli",  # M7 replaces this with the authenticated reviewer
                event=f"action_{status}",
                ref_type="action",
                ref_id=action_id,
                payload={
                    "run_id": state.get("run_id"), "change_id": action.change_id, "type": action.type,
                    "previous_status": previous, "via": "cli_resume",
                },
                commit=False,
            )

        still_pending = [a["action_id"] for a in awaiting if a["action_id"] not in set(approved) | set(dismissed)]
        audit.record(
            db,
            actor=audit.node_actor("human_review"),
            event="human_review_applied",
            payload={
                "run_id": state.get("run_id"),
                "approved": approved,
                "dismissed": dismissed,
                "left_pending": still_pending,
            },
        )

    print(f"[human_review] approved {len(approved)}, dismissed {len(dismissed)}, left pending {len(still_pending)}")
    return {
        "review_decision": {"approved": approved, "dismissed": dismissed, "left_pending": still_pending}
    }


def _validate_decision(decision: Any, valid_ids: set[int]) -> tuple[list[int], list[int]]:
    """A resume value is operator input, and a typo'd action id must not
    quietly do nothing — it raises, the same way a malformed LLM response
    raises in llm.py."""
    if not isinstance(decision, dict):
        raise ValueError(
            f"Resume value must be a dict like {{'approved': [...], 'dismissed': [...]}}, got {type(decision).__name__}."
        )
    approved = list(decision.get("approved") or [])
    dismissed = list(decision.get("dismissed") or [])
    unknown = [i for i in approved + dismissed if i not in valid_ids]
    if unknown:
        raise ValueError(
            f"Resume decision refers to action id(s) {unknown} that are not awaiting review in this run "
            f"(awaiting: {sorted(valid_ids)})."
        )
    both = set(approved) & set(dismissed)
    if both:
        raise ValueError(f"Action id(s) {sorted(both)} were both approved and dismissed.")
    return approved, dismissed


# ── deliver ───────────────────────────────────────────────────────────────

def deliver_node(state: AgentState) -> dict[str, Any]:
    """Delivery from the graph is a summary written to the audit trail and
    the console. It is deliberately NOT a notification: signed webhooks, PDF
    and Excel exports are M8, and emitting a "delivered" event for a
    delivery that never left the process would be a fabrication of exactly
    the kind section 7's guardrails forbid."""
    with Session(get_engine()) as db:
        pending_elsewhere = db.scalar(
            select(func.count())
            .select_from(Action)
            .where(
                Action.status == "pending",
                Action.id.notin_(state.get("action_ids") or [-1]),
            )
        )
        summary = {
            "run_id": state.get("run_id"),
            "started_at": state.get("started_at"),
            "finished_at": _utc_now_iso(),
            "sources_seen": len(state.get("sources") or []),
            "sources_needing_attention": [
                s["path"] for s in (state.get("sources") or []) if s["status"] in ("conflict", "unrecognized")
            ],
            "versions_ingested": len(state.get("ingested") or []),
            "version_pairs_diffed": len(state.get("diffed_pairs") or []),
            "changes_processed": len(state.get("change_ids") or []),
            "impact_rows": sum(r["impact_count"] for r in (state.get("impacted") or [])),
            "priority_bands": _count_by(list((state.get("priorities") or {}).values()), "band"),
            "actions_created": len(state.get("action_ids") or []),
            "actions_auto_executed": len(state.get("auto_executed_action_ids") or []),
            "review_decision": state.get("review_decision") or {},
            "actions_pending_from_other_runs": pending_elsewhere,
            "delivery_channel": "audit_log + console: no webhook/PDF/Excel is sent from here",
        }
        audit.record(
            db,
            actor=audit.node_actor("deliver"),
            event="run_delivered",
            payload=summary,
        )

    print("\n" + "=" * 60)
    print("Xposure agent run summary")
    print("=" * 60)
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("=" * 60 + "\n")
    return {"summary": summary}


# ── Routing ───────────────────────────────────────────────────────────────

def route_after_policy(state: AgentState) -> str:
    """auto_execute first when there is anything to auto-execute, then
    human review for whatever is left, then deliver. Both branches can
    apply in the same run (some action types clear the policy gates, some
    do not), which is why auto_execute has its own edge into human_review
    rather than going straight to deliver."""
    if state.get("auto_executable_action_ids"):
        return "auto_execute"
    if state.get("review_action_ids"):
        return "human_review"
    return "deliver"


def route_after_auto_execute(state: AgentState) -> str:
    return "human_review" if state.get("review_action_ids") else "deliver"


def build_graph(checkpointer: Any) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("check_sources", check_sources_node)
    graph.add_node("ingest_new", ingest_new_node)
    graph.add_node("diff", diff_node)
    graph.add_node("impact", impact_node)
    graph.add_node("prioritize", prioritize_node)
    graph.add_node("apply_policy", apply_policy_node)
    graph.add_node("auto_execute", auto_execute_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("deliver", deliver_node)

    graph.add_edge(START, "check_sources")
    graph.add_edge("check_sources", "ingest_new")
    graph.add_edge("ingest_new", "diff")
    graph.add_edge("diff", "impact")
    graph.add_edge("impact", "prioritize")
    graph.add_edge("prioritize", "apply_policy")
    graph.add_conditional_edges(
        "apply_policy", route_after_policy, ["auto_execute", "human_review", "deliver"]
    )
    graph.add_conditional_edges(
        "auto_execute", route_after_auto_execute, ["human_review", "deliver"]
    )
    graph.add_edge("human_review", "deliver")
    graph.add_edge("deliver", END)
    return graph.compile(checkpointer=checkpointer)


# ── Checkpointer ──────────────────────────────────────────────────────────

def checkpoint_dsn() -> str:
    """langgraph-checkpoint-postgres talks to psycopg directly, so it wants
    a plain libpq DSN — SQLAlchemy's "postgresql+psycopg://" dialect prefix
    is not one. Same database, same credentials; only the URL scheme
    differs."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", settings.database_url)


@contextmanager
def checkpointer() -> Iterator[PostgresSaver]:
    """Postgres-backed LangGraph checkpointer.

    `.setup()` is LangGraph's own migration for its own checkpoint tables
    (checkpoints, checkpoint_writes, checkpoint_blobs, ...) — it is
    idempotent and is deliberately called on every run rather than hand-
    modelled in db/models.py or an Alembic revision. Those tables are
    LangGraph's schema, not ours; owning a copy of them would mean
    maintaining it against every LangGraph upgrade."""
    with PostgresSaver.from_conn_string(checkpoint_dsn()) as saver:
        saver.setup()
        yield saver


# A fixed, arbitrary key for the one Postgres session-level advisory lock
# this process ever takes. One key is enough: there is exactly one kind of
# thing being serialized (a full pipeline pass), not several.
_PIPELINE_LOCK_KEY = 0x58504F5355524521  # "XPOSURE!" packed into 64 bits, truncated to fit bigint


@contextmanager
def pipeline_lock(timeout_seconds: float = 0.0) -> Iterator[bool]:
    """Serializes every full pipeline pass (run_once, resume_run, and the
    demo runner's own stream() call in app/demo/runner.py) against every
    OTHER pipeline pass, across processes, not just within one.

    docs/DESIGN.md names this gap directly: apply_policy_node's duplicate-
    action check (the (change, impacted node, action type) triple) is an
    application-level SELECT-then-INSERT with no lock behind it, so two
    genuinely concurrent runs could both pass that check for the same
    action before either commits. Nothing in the first version scheduled
    overlapping runs, so this was correctly deferred rather than guessed
    at; now that
    the product is meant to run unattended (a scheduler, a second worker,
    an operator running the CLI while a web-triggered scan is mid-flight),
    it is a real risk, not a hypothetical one.

    A Postgres advisory lock, not a Python threading.Lock (app/demo/
    tracker.py's TRACKER already has one of those, and it is NOT enough:
    it only ever protects against a second thread in the SAME process).
    `pg_try_advisory_lock` is non-blocking by design: a pipeline run that
    cannot get the lock should fail fast and say why, never queue up
    silently behind another run on a 15-minute cold path. `timeout_seconds`
    exists for tests only (poll briefly instead of racing).

    Yields True if the lock was acquired (the caller should proceed) or
    False if not (the caller should refuse to run). Always releases on the
    way out when it acquired. On SQLite (unit tests: no Postgres, no
    advisory locks) this is a no-op that always yields True — the in-
    process TRACKER lock still applies there, and no test exercises real
    multi-process concurrency."""
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        yield True
        return

    deadline = time.monotonic() + timeout_seconds
    conn = engine.raw_connection()
    try:
        acquired = False
        while True:
            cursor = conn.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (_PIPELINE_LOCK_KEY,))
            acquired = bool(cursor.fetchone()[0])
            cursor.close()
            # pg_try_advisory_lock is session-level, not transaction-level, so this
            # commit does not release it — it only ends the open transaction, which
            # would otherwise sit idle-in-transaction for the run's full duration and
            # block any concurrent CREATE INDEX CONCURRENTLY (e.g. LangGraph's own
            # checkpointer setup) that has to wait for its xmin horizon to clear.
            conn.commit()
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        try:
            yield acquired
        finally:
            if acquired:
                cursor = conn.cursor()
                cursor.execute("SELECT pg_advisory_unlock(%s)", (_PIPELINE_LOCK_KEY,))
                cursor.close()
    finally:
        conn.close()


class PipelineBusy(RuntimeError):
    """Raised when another pipeline pass already holds the advisory lock."""


# ── Runner ────────────────────────────────────────────────────────────────

def _new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get(key))] = counts.get(str(row.get(key)), 0) + 1
    return counts


def _report_interrupt(result: dict[str, Any], thread_id: str) -> bool:
    """Returns True if the run paused. The 'paused' audit row is written
    here rather than inside human_review_node on purpose: that node's body
    re-runs on resume, so a row written there would claim the run paused
    twice. The runner sees the pause exactly once."""
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return False
    payload = interrupts[0].value
    audit.record_in_new_session(
        actor=audit.node_actor("human_review"),
        event="run_paused_for_human_review",
        payload={
            "run_id": payload.get("run_id"),
            "thread_id": thread_id,
            "awaiting_action_ids": [a["action_id"] for a in payload.get("awaiting", [])],
        },
    )
    print("\n" + "=" * 60)
    print("PAUSED for human review: the run is checkpointed and can be resumed later.")
    print("=" * 60)
    for item in payload.get("awaiting", []):
        print(
            f"  action {item['action_id']}: {item['type']} ({item['level']}) "
            f"change={item['change_id']} clause={item['clause_id']} "
            f"priority={item['priority_band']}/{item['priority_score']} node={item['impact_node_name']}"
        )
    ids = ",".join(str(a["action_id"]) for a in payload.get("awaiting", []))
    print(f"\nResume with:\n  python -m app.agent.graph --resume {thread_id} --approve {ids}")
    print("=" * 60 + "\n")
    return True


def run_once(thread_id: str | None = None) -> dict[str, Any]:
    """One full pass of the loop. Returns the final state; if the run
    paused for human review the returned state carries "__interrupt__" and
    the thread can be resumed with resume_run()."""
    run_id = _new_run_id()
    thread_id = thread_id or run_id
    initial: AgentState = {"run_id": run_id, "started_at": _utc_now_iso()}

    print(f"\nXposure agent, run_id={run_id} thread_id={thread_id}\n")
    try:
        with pipeline_lock() as acquired:
            if not acquired:
                raise PipelineBusy(
                    "Another pipeline run is already in progress (held the Postgres advisory lock). "
                    "Wait for it to finish, or check for a stuck process, before starting a new one."
                )
            with checkpointer() as saver:
                app = build_graph(saver)
                result = app.invoke(initial, {"configurable": {"thread_id": thread_id}})
    except (Exception, SystemExit) as exc:
        # Visible failure, recorded from a fresh session (the node's own
        # session is likely in a failed transaction) — then re-raised.
        # Never swallowed, never turned into a partial "success".
        # SystemExit is caught alongside Exception on purpose: it is this
        # project's established fail-loud signal for an operator-visible
        # problem (ingest.py raises it for a missing source file, diff.py
        # for an un-ingested version), and those are exactly the failures
        # the audit trail should be able to account for. KeyboardInterrupt
        # is deliberately still not caught.
        audit.record_in_new_session(
            actor="agent:runner",
            event="run_failed",
            payload={"run_id": run_id, "thread_id": thread_id, "error": f"{type(exc).__name__}: {exc}"},
        )
        raise

    _report_interrupt(result, thread_id)
    return result


def resume_run(thread_id: str, approved: list[int], dismissed: list[int]) -> dict[str, Any]:
    """Resume a run that paused in human_review, with the reviewer's
    decision. Actions named in neither list stay pending.

    The thread is checked before resuming because LangGraph's own
    behaviour here is a silent fallback: invoking Command(resume=...) on a
    thread_id with no checkpoint does not fail, it quietly STARTS A NEW RUN
    from the beginning — so a mistyped thread id would look like it
    worked, re-scan sources, re-diff and produce a second set of actions.
    Found by testing the resume path, not by reading the docs.

    The action ids named in `approved`/`dismissed` are checked the same
    way, for the same reason, and this one was found the same way too:
    human_review_node's docstring already documents that M7's UI can
    approve/dismiss any pending action directly through the API,
    independently of a paused CLI thread — genuinely a race, not a
    hypothetical one, once both paths exist. Reproducing it directly
    (approve an action via the DB, exactly as the API would, while a CLI
    thread is still paused on it, then resume that stale thread) showed
    LangGraph's real behaviour is not an error: human_review_node
    re-queries Action.status == "pending" on resume, finds the action no
    longer pending, sees an empty "awaiting" set, and takes its own
    documented early-return path ("nothing pending — not pausing") —
    WITHOUT ever calling interrupt() again, which means the stale
    decision's approved/dismissed ids are never even handed to
    _validate_decision. The whole run then reports success. An operator
    running a stale `--resume ... --approve N` would see "run complete"
    with no indication their decision was silently discarded, not
    applied — exactly the kind of quiet-looking-but-wrong outcome this
    project's guardrails exist to prevent. Checking first, here, the same
    way the thread-existence check already does, closes it."""
    print(f"\nXposure agent, resuming thread_id={thread_id}\n")
    try:
        with pipeline_lock() as acquired:
            if not acquired:
                raise PipelineBusy(
                    "Another pipeline run is already in progress (held the Postgres advisory lock). "
                    "Wait for it to finish before resuming this thread."
                )
            with checkpointer() as saver:
                app = build_graph(saver)
                config = {"configurable": {"thread_id": thread_id}}
                snapshot = app.get_state(config)
                if not snapshot.next:
                    raise SystemExit(
                        f"No paused run found for thread_id '{thread_id}': it has either never run, "
                        f"or already finished. Refusing to resume (that would silently start a new run). "
                        f"Start a fresh pass with: python -m app.agent.graph"
                    )
                if not any(task.interrupts for task in snapshot.tasks):
                    raise SystemExit(
                        f"Thread '{thread_id}' is checkpointed at {snapshot.next} but is not waiting on a "
                        f"human-review interrupt, so there is nothing to approve or dismiss."
                    )

                named_ids = [*approved, *dismissed]
                if named_ids:
                    with Session(get_engine()) as db:
                        current_status = {
                            a.id: a.status
                            for a in db.scalars(select(Action).where(Action.id.in_(named_ids)))
                        }
                    stale = {
                        action_id: current_status.get(action_id, "no longer exists")
                        for action_id in named_ids
                        if current_status.get(action_id) != "pending"
                    }
                    if stale:
                        raise SystemExit(
                            f"Refusing to resume thread '{thread_id}': action id(s) {stale} are no longer "
                            f"pending (resolved, delegated, or otherwise changed, likely through the web UI, "
                            f"since this thread paused). Re-check the current state before resuming: a stale "
                            f"decision must not be silently dropped or reapplied."
                        )

                result = app.invoke(
                    Command(resume={"approved": approved, "dismissed": dismissed}), config
                )
    except (Exception, SystemExit) as exc:  # see run_once() on why SystemExit too
        audit.record_in_new_session(
            actor="agent:runner",
            event="resume_failed",
            payload={"thread_id": thread_id, "error": f"{type(exc).__name__}: {exc}"},
        )
        raise

    _report_interrupt(result, thread_id)
    return result


def plan_run() -> dict[str, Any]:
    """--dry-run: everything a pass would do next, computed with reads
    only. No ingestion, no LLM call, no rows written (not even audit rows
    — a dry run did not do anything worth auditing). The same spirit as
    diff.py's --dry-run: make the expensive step inspectable before paying
    for it."""
    with Session(get_engine()) as db:
        sources = detect_new_sources(db)
        pairs = pending_diff_pairs(db)
        changes = changes_needing_action(db)
        needing_impact = [
            c.id
            for c in changes
            if not db.scalar(select(func.count()).select_from(Impact).where(Impact.change_id == c.id))
        ]
        pending_actions = db.scalar(
            select(func.count()).select_from(Action).where(Action.status == "pending")
        )

    print(f"\n[dry-run] sources under {SOURCES_DIR}: {_count_by(sources, 'status')}")
    for s in sources:
        print(f"  {s['status']:17s} {s['path']}  sha256={s['sha256'][:12]}...")
    print(f"\n[dry-run] version pairs that would be diffed: {len(pairs)}")
    for p in pairs:
        print(f"  {p['regulator']}/{p['regulation']}: {p['from_label']} -> {p['to_label']}")
    print(f"\n[dry-run] material changes needing action: {len(changes)} ({len(needing_impact)} still need impact analysis)")
    print(f"[dry-run] actions already pending human review: {pending_actions}")
    print("\n[dry-run] nothing was written and no model was called.\n")

    return {
        "sources": sources,
        "pending_diff_pairs": pairs,
        "changes_needing_action": [c.id for c in changes],
        "changes_needing_impact": needing_impact,
        "actions_pending": pending_actions,
    }


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part) for part in raw.split(",") if part.strip()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one pass of the Xposure agent loop")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read-only: report what a pass would ingest/diff/act on, then stop. No LLM call, no writes.",
    )
    parser.add_argument(
        "--thread-id",
        help="LangGraph thread id for the checkpoint (default: the generated run id). Reuse one to resume.",
    )
    parser.add_argument("--resume", dest="resume_thread", help="resume a run that paused for human review")
    parser.add_argument("--approve", help="comma-separated action ids to approve (with --resume)")
    parser.add_argument("--dismiss", help="comma-separated action ids to dismiss (with --resume)")
    args = parser.parse_args()

    if args.dry_run:
        if args.resume_thread:
            parser.error("--dry-run and --resume are mutually exclusive")
        plan_run()
        sys.exit(0)

    if args.resume_thread:
        resume_run(args.resume_thread, _parse_ids(args.approve), _parse_ids(args.dismiss))
    else:
        if args.approve or args.dismiss:
            parser.error("--approve/--dismiss only apply to --resume")
        run_once(thread_id=args.thread_id)

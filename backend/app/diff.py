"""
Clause-level diff engine: aligns two versions of the same regulation's
clauses, computes a deterministic sentence-level delta for each aligned
pair, and (optionally — see --dry-run) classifies each delta with the LLM.

Run as:
  python -m app.diff --regulator nca --regulation ecc --from 1-2018 --to 2-2024 [--dry-run] [--replace]

Alignment (see align_clauses()):
  1. Exact clause_id match between the two versions.
  2. For everything left unmatched on both sides, one-to-one embedding
     similarity matching (Hungarian algorithm via scipy, reusing the
     vectors already computed at ingestion time — no re-embedding) above
     a similarity threshold, flagged "renumbered_candidate".
  3. Whatever still has no counterpart on the other side is "new"
     (to-only) or "withdrawn" (from-only).
This matches the takeoff prompt's guardrail that deltas are computed by
code, not by the LLM (docs/PLAN.md section 7 / M3): alignment and the
sentence-level delta (sentence_delta()) are both pure, deterministic
functions with no model call. classify_change() (app/llm.py) only LABELS
a pair code has already aligned and diffed — it never decides what
changed, only what kind of change it is and how to summarize it.

--dry-run runs alignment + delta only, with no LLM call at all: useful to
verify alignment quality (and, as of M3, to verify the pipeline at all —
see app/llm.py's module docstring for why classification itself hasn't
been exercised against a real model yet).
"""

import argparse
import difflib
import re
from datetime import date
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import llm, progress
from .db.models import Change, Clause, Regulation, RegulationVersion, Regulator
from .db.session import get_engine
from .retriever import get_vectors_for_version

# Known downstream effect of ingest.py's documented merged-parent-cell
# limitation: a handful of "new" clauses in the real ECC-1:2018 -> ECC-2:2024
# diff (e.g. "1-5-3") are parent-group codes whose ECC-1 counterpart was
# never stored (its own intro text landed on its first child instead), not
# genuinely new regulatory content. Low blast radius (confidence gating in
# M5 routes these to human review regardless) — noted here rather than
# fixed, since fixing it means fixing the ingest-time limitation, not this
# module. Good candidate for the post-M3 optimization pass.
#
# Calibrated against the real ECC-1:2018 -> ECC-2:2024 diff, not guessed:
# dumping the actual score distribution showed genuine renumbered matches
# reaching up to 1.000 (median 0.95) but false positives (ECC-1's Domain 5
# "ICS Cybersecurity" content, dropped in ECC-2 and left with nothing real
# to match, e.g. "Security patch management." force-matched to
# "Cybersecurity department personnel.") scoring as high as 0.85-0.93 —
# there is no clean separating line in the data, so this threshold trades
# off precision/recall rather than eliminating false positives outright.
# multilingual-e5-large embeddings on short, template-heavy regulatory
# clauses ("...shall be documented and approved.") apparently cluster on
# boilerplate phrasing almost as strongly as on actual topic. The
# project's own downstream safety nets are the intended backstop, not a
# perfect threshold: M5 gates confidence < 0.7 to human review regardless,
# and M9's labeled-eval harness is exactly the tool to measure/retune
# this properly once real LLM classification output exists. Worth
# revisiting in the post-M3 optimization pass.
SIMILARITY_THRESHOLD = 0.90


# ── Alignment ─────────────────────────────────────────────────────────────

def _cosine_sim_matrix(vecs_a: list[list[float]], vecs_b: list[list[float]]) -> np.ndarray:
    # embeddings.py normalizes every vector (normalize_embeddings=True), so
    # a plain dot product already equals cosine similarity.
    return np.array(vecs_a) @ np.array(vecs_b).T


def _normalized_segments(clause_id: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.split(r"[-.]", clause_id))


def align_clauses(
    from_clauses: list[Clause],
    to_clauses: list[Clause],
    from_vectors: dict[str, list[float]],
    to_vectors: dict[str, list[float]],
) -> list[dict]:
    """Returns [{"old": Clause|None, "new": Clause|None, "match_kind": str,
    "match_score": float|None}, ...]. match_kind: "exact_id" |
    "renumbered_candidate" | "new" | "withdrawn"."""
    from_by_id = {c.clause_id: c for c in from_clauses}
    to_by_id = {c.clause_id: c for c in to_clauses}

    pairs: list[dict] = []
    matched_from: set[str] = set()
    matched_to: set[str] = set()

    # "Exact" match compares NORMALIZED segment tuples, not raw strings:
    # ECC-1:2018 writes every level hyphen-separated ("2-5-3-4") while
    # ECC-2:2024's subcontrols are dot-separated ("2.5.3.4") — same
    # logical control, different formatting. Confirmed against the real
    # data, not assumed: several same-ID pairs were falling through to
    # the embedding-similarity fallback and getting flagged
    # "renumbered_candidate" despite not having moved at all.
    from_by_segments: dict[tuple[int, ...], str] = {}
    for cid in from_by_id:
        from_by_segments.setdefault(_normalized_segments(cid), cid)
    to_by_segments: dict[tuple[int, ...], str] = {}
    for cid in to_by_id:
        to_by_segments.setdefault(_normalized_segments(cid), cid)

    for segments in sorted(from_by_segments.keys() & to_by_segments.keys()):
        old_cid, new_cid = from_by_segments[segments], to_by_segments[segments]
        pairs.append({"old": from_by_id[old_cid], "new": to_by_id[new_cid], "match_kind": "exact_id", "match_score": None})
        matched_from.add(old_cid)
        matched_to.add(new_cid)

    unmatched_from = [c for c in from_clauses if c.clause_id not in matched_from and c.clause_id in from_vectors]
    unmatched_to = [c for c in to_clauses if c.clause_id not in matched_to and c.clause_id in to_vectors]

    if unmatched_from and unmatched_to:
        sim = _cosine_sim_matrix(
            [from_vectors[c.clause_id] for c in unmatched_from],
            [to_vectors[c.clause_id] for c in unmatched_to],
        )
        row_ind, col_ind = linear_sum_assignment(1.0 - sim)  # Hungarian minimizes cost, so cost = 1 - similarity
        for i, j in zip(row_ind, col_ind):
            score = float(sim[i, j])
            if score >= SIMILARITY_THRESHOLD:
                old_c, new_c = unmatched_from[i], unmatched_to[j]
                pairs.append({"old": old_c, "new": new_c, "match_kind": "renumbered_candidate", "match_score": score})
                matched_from.add(old_c.clause_id)
                matched_to.add(new_c.clause_id)

    for c in from_clauses:
        if c.clause_id not in matched_from:
            pairs.append({"old": c, "new": None, "match_kind": "withdrawn", "match_score": None})
    for c in to_clauses:
        if c.clause_id not in matched_to:
            pairs.append({"old": None, "new": c, "match_kind": "new", "match_score": None})

    return pairs


# ── Delta ─────────────────────────────────────────────────────────────────

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(text) if s.strip()]


def sentence_delta(old_text: str, new_text: str) -> dict:
    """Sentence-level diff (difflib), JSON-serializable for
    change.diff_spans_json — the "diff receipt" data for M7's UI. Equal
    spans are omitted (not interesting for a diff view); only what
    changed is kept."""
    old_sentences = _split_sentences(old_text)
    new_sentences = _split_sentences(new_text)
    matcher = difflib.SequenceMatcher(None, old_sentences, new_sentences, autojunk=False)
    ops = [
        {"op": tag, "old": old_sentences[i1:i2], "new": new_sentences[j1:j2]}
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]
    return {"ops": ops}


# ── Orchestration ─────────────────────────────────────────────────────────

def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        print(f"  [warn] model returned an unparseable effective_date {value!r}; storing as null")
        return None


def run_diff(
    regulator_code: str,
    regulation_code: str,
    from_label: str,
    to_label: str,
    dry_run: bool = False,
    replace: bool = False,
) -> None:
    engine = get_engine()
    with Session(engine) as db:
        regulation = db.scalar(
            select(Regulation).join(Regulator).where(
                Regulator.code == regulator_code, Regulation.code == regulation_code
            )
        )
        if regulation is None:
            raise SystemExit(f"Unknown regulation '{regulator_code}/{regulation_code}': has it been ingested?")

        from_version = db.scalar(select(RegulationVersion).where(
            RegulationVersion.regulation_id == regulation.id, RegulationVersion.version_label == from_label,
        ))
        to_version = db.scalar(select(RegulationVersion).where(
            RegulationVersion.regulation_id == regulation.id, RegulationVersion.version_label == to_label,
        ))
        if from_version is None:
            raise SystemExit(f"Version '{from_label}' of {regulator_code}/{regulation_code} is not ingested.")
        if to_version is None:
            raise SystemExit(f"Version '{to_label}' of {regulator_code}/{regulation_code} is not ingested.")

        if not dry_run:
            existing = db.scalars(select(Change).where(
                Change.from_version_id == from_version.id, Change.to_version_id == to_version.id,
            )).all()
            if existing:
                if not replace:
                    raise SystemExit(
                        f"A diff from {from_label} to {to_label} already exists ({len(existing)} change rows). "
                        f"change rows are append-only: pass --replace to delete and redo (dev only)."
                    )
                print(f"[replace] Deleting {len(existing)} existing change rows...")
                for row in existing:
                    db.delete(row)
                db.flush()

        from_clauses = list(db.scalars(select(Clause).where(Clause.version_id == from_version.id)))
        to_clauses = list(db.scalars(select(Clause).where(Clause.version_id == to_version.id)))
        print(f"{from_label}: {len(from_clauses)} clauses. {to_label}: {len(to_clauses)} clauses.")

        print("Fetching embeddings for alignment...")
        from_vectors = get_vectors_for_version(regulator_code, regulation_code, from_label)
        to_vectors = get_vectors_for_version(regulator_code, regulation_code, to_label)

        print("Aligning clauses...")
        pairs = align_clauses(from_clauses, to_clauses, from_vectors, to_vectors)
        counts = {k: sum(1 for p in pairs if p["match_kind"] == k) for k in ("exact_id", "renumbered_candidate", "new", "withdrawn")}
        print(f"  {len(pairs)} pairs: {counts}")

        identical = sum(
            1 for p in pairs
            if p["old"] and p["new"] and p["old"].text_en == p["new"].text_en
        )
        to_classify = [
            p for p in pairs
            if not (p["old"] and p["new"] and p["old"].text_en == p["new"].text_en)
        ]
        print(f"  {identical} pairs are byte-identical (skipped: nothing to classify or alert on)")
        progress.emit(
            "diff.aligned",
            from_label=from_label, to_label=to_label,
            from_clauses=len(from_clauses), to_clauses=len(to_clauses),
            pairs=len(pairs), match_counts=counts, identical=identical, to_classify=len(to_classify),
            dry_run=dry_run,
        )

        if dry_run:
            print(f"\n--dry-run: stopping before classification. {len(to_classify)} pairs would be classified.\n")
            for p in to_classify[:20]:
                old_id = p["old"].clause_id if p["old"] else "-"
                new_id = p["new"].clause_id if p["new"] else "-"
                score = f" ({p['match_score']:.2f})" if p["match_score"] is not None else ""
                print(f"  {p['match_kind']:20s}{score:8s} {old_id:14s} -> {new_id}")
            if len(to_classify) > 20:
                print(f"  ... and {len(to_classify) - 20} more")
            return

        print(f"Classifying {len(to_classify)} changes (calls the LLM: see app/llm.py if this fails)...")
        change_rows = []
        for i, p in enumerate(to_classify, 1):
            old_c, new_c = p["old"], p["new"]
            old_text = old_c.text_en if old_c else ""
            new_text = new_c.text_en if new_c else ""
            delta = sentence_delta(old_text, new_text)
            result = llm.classify_change(old_text, new_text, p["match_kind"])
            change_rows.append(Change(
                regulation_id=regulation.id,
                from_version_id=from_version.id,
                to_version_id=to_version.id,
                old_clause_id=old_c.clause_id if old_c else None,
                new_clause_id=new_c.clause_id if new_c else None,
                match_kind=p["match_kind"],
                match_score=p["match_score"],
                change_type=result["change_type"],
                material=result["change_type"] not in ("editorial", "renumbered"),
                confidence=result["confidence"],
                summary_en=result["summary_en"],
                summary_ar=result["summary_ar"],
                effective_date=_parse_date(result["effective_date"]),
                grace_days=result["grace_days"],
                diff_spans_json=delta,
            ))
            print(f"  [{i}/{len(to_classify)}] {old_c.clause_id if old_c else '-':14s} -> {new_c.clause_id if new_c else '-':14s}  {result['change_type']}")
            progress.emit(
                "diff.classified", done=i, total=len(to_classify), change_type=result["change_type"],
                old_clause_id=old_c.clause_id if old_c else None, new_clause_id=new_c.clause_id if new_c else None,
            )

        db.add_all(change_rows)
        db.commit()
        print(f"\nStored {len(change_rows)} change rows.\n")
        progress.emit(
            "diff.stored", changes=len(change_rows),
            material=sum(1 for c in change_rows if c.material),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diff two ingested versions of a regulation")
    parser.add_argument("--regulator", default="nca")
    parser.add_argument("--regulation", required=True, help="e.g. ecc")
    parser.add_argument("--from", required=True, dest="from_label", help="e.g. 1-2018")
    parser.add_argument("--to", required=True, dest="to_label", help="e.g. 2-2024")
    parser.add_argument("--dry-run", action="store_true", help="align + delta only, no LLM call, no rows written")
    parser.add_argument("--replace", action="store_true", help="delete and redo if this from/to pair was already diffed (dev only)")
    args = parser.parse_args()
    run_diff(args.regulator, args.regulation, args.from_label, args.to_label, dry_run=args.dry_run, replace=args.replace)

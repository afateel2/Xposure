"""
Deterministic priority scoring for a classified regulatory change (M5).

The LLM classifies a change (app/llm.py) and writes a summary; arithmetic
here decides how urgent it is. The model never emits a number, so the same
change always produces the same score and every band has a stated rule a
compliance officer can audit and argue with. This is the takeoff prompt's
guardrail "scores and priority are deterministic; the same inputs always
give the same number" (docs/PLAN.md section 7), and it follows ComplyX's
scoring.py discipline: constants in one block with their rationale,
non-compensatory gates, verbal band definitions before numeric ones.

Stated meaning of the score:
  "Priority is a triage index for one regulatory change against one
  organization. It answers 'how soon must a human look at this, relative
  to everything else in the queue', not 'how non-compliant are we'. It
  combines how much new duty the change creates, how much of this
  organization it reaches, how close its deadline is, and how heavily
  this regulator weighs — nothing else."

Formula (the shape is fixed by the takeoff prompt section 3 / M5):

    raw   = severity_weight(change_type)
          * impact_factor(impacted_node_count)
          * deadline_factor(days_to_effective)
          * regulator_weight
    score = round(100 * raw / REFERENCE_RAW), clamped to 0-100, then gated

Methodology principles (each maps to a norm, not to taste):

1. Severity is the base, the rest are multipliers. What kind of change it
   is dominates: a new obligation with no deadline still outranks an
   editorial fix that touches the whole org. Multipliers can amplify a
   serious change into "drop everything" but cannot manufacture urgency
   out of a cosmetic one — see principle 5.

2. Impact grows sublinearly (log2). The second impacted node tells you a
   great deal (the change is not isolated); the twenty-second tells you
   almost nothing new. Linear growth would let a single broadly-mapped
   control swamp every other signal, which is how noisy GRC dashboards
   get ignored. Ceiling at 2.0x: the broadest possible change is worth at
   most twice one that touches nothing, all else equal.

3. Urgency is stepped, not continuous. "Inside 30 days" is a sentence a
   compliance officer can act on and audit; "1.4271x because it is 47
   days away" is not. Steps are also robust to the real input quality
   here — effective dates are extracted from PDFs by an LLM and are often
   absent (see app/llm.py: the model is instructed never to guess one).

4. A missing deadline is neutral, never a penalty and never a bonus.
   days_to_effective=None scores exactly as a deadline more than a year
   out (factor 1.00, the floor). We do not know of urgency; that is not
   the same as knowing there is none, so it must not push the score down
   below where the change's own severity puts it.

5. Non-compensatory materiality gate: a change marked immaterial is
   capped into the low band no matter how many nodes it touches or how
   near its deadline is. The takeoff prompt fixes editorial/renumbered as
   material=false and says they never generate alerts; breadth of impact
   must not be able to talk a cosmetic change back into someone's queue.
   This mirrors ComplyX's severity gates (worst-of logic, as in
   supervisory SREP ratings and audit RAG statuses).

6. Monotonicity: with everything else held fixed, a more severe change
   type, one more impacted node, a nearer deadline, or a heavier
   regulator can only raise the score, never lower it. Tested directly
   (tests/unit/test_priority.py) rather than asserted, since this is the
   property that makes a ranked queue trustworthy.

7. Confidence is deliberately NOT in the formula. A change the classifier
   is only 55% sure is a new obligation is exactly the one a human should
   look at soonest — discounting its priority by uncertainty would bury
   the cases most in need of review. Confidence gates AUTOMATION instead
   (app/policy.py: below 0.7 a human always decides), which is the right
   lever: uncertainty should restrain what the agent does unsupervised,
   not how loudly it raises its hand.

Properties this parameterization guarantees at regulator_weight=1.0
(each is a test, not a claim):
  - new_obligation never scores below 38 (medium), even with zero
    impacted nodes and no deadline.
  - Only new_obligation and tightened can ever reach critical. A pure
    withdrawal tops out at 53 (high), a clarification at 44 (medium), a
    relaxation at 32 (medium).
  - editorial tops out at 4 and renumbered at 9 — both firmly low before
    the materiality gate even applies.

Changing any weight, step or threshold means updating this docstring's
rationale and re-checking those properties. Do not hand-tune a single
change's score.
"""

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported for the annotation only: this module reads exactly two
    # attributes off the object (.change_type and .material) and touches
    # no session, so it stays importable with no SQLAlchemy/DB cost and
    # unit tests can pass a plain SimpleNamespace stand-in (the same
    # duck-typing tests/unit/test_diff.py uses for Clause).
    from .db.models import Change


# ── Severity: what kind of change it is ───────────────────────────────────
# Base points on the 0-100 scale before any multiplier. Keys are exactly
# the vocabulary app/llm.py's classifier is constrained to (CHANGE_TYPES);
# deliberately restated here rather than imported so this pure module does
# not pull in the OpenAI client and .env at import time. A test asserts
# the two lists still match, so drift fails the suite instead of rotting.
#
# The ordering argument, top to bottom:
#   new_obligation  A duty that did not exist. Someone has to build a
#                   control, own it, and evidence it from nothing, and
#                   until they do the organization is plainly
#                   non-compliant. Nothing else in the vocabulary carries
#                   that combination of new work and new exposure.
#   tightened       The control exists and has an owner; the bar moved.
#                   Real work, but it starts from something, so ~80% of a
#                   new obligation.
#   withdrawn       A duty disappeared. Nothing becomes non-compliant by
#                   ignoring it, but it is not free either: evidence
#                   collection, control mappings and audit scope should
#                   stop, and in this corpus "withdrawn" has also meant
#                   "moved to another authority's document" (ECC-1:2018's
#                   Domain 5 -> OTCC, see docs/PLAN.md), which is a real
#                   compliance question, not a deletion.
#   clarification   The obligation is substantively unchanged, but the
#                   rewording can move how an auditor reads it, so
#                   procedures and evidence may still need a look.
#   relaxed         Strictly good news. Worth surfacing only so the
#                   organization can stop over-spending on a control it
#                   no longer needs at that level.
#   renumbered      Clerical, but not zero: control IDs are what the org
#                   graph maps against, so cross-references have to be
#                   repointed or impact analysis silently misses things.
#   editorial       Cosmetic. Recorded for the audit trail, nothing else.
SEVERITY_WEIGHT: dict[str, float] = {
    "new_obligation": 70.0,
    "tightened": 55.0,
    "withdrawn": 30.0,
    "clarification": 25.0,
    "relaxed": 18.0,
    "renumbered": 5.0,
    "editorial": 2.0,
}

CHANGE_TYPES: tuple[str, ...] = tuple(SEVERITY_WEIGHT)

# Change types the takeoff prompt fixes as material=false: they never
# generate an alert, and the gate below keeps them out of every band but
# low regardless of the other factors.
IMMATERIAL_CHANGE_TYPES: frozenset[str] = frozenset({"editorial", "renumbered"})


# ── Impact: how much of this organization the change reaches ──────────────
# impact_factor(n) = 1 + IMPACT_GAIN * log2(1 + n), capped.
#   n=0  -> 1.00   the change maps to no node we own
#   n=1  -> 1.25   first impacted node: the largest single jump, correctly
#   n=3  -> 1.50
#   n=7  -> 1.75
#   n>=15-> 2.00   ceiling
# IMPACT_GAIN=0.25 with the 2.0 ceiling makes the ceiling land exactly at
# 15 nodes, which is deliberate: the demo organization is ~15-20 nodes
# (takeoff prompt section 3 / M4), so "touches 15 of them" already means
# "touches effectively everything" and further growth carries no
# information. On a real customer graph of thousands of nodes the ceiling
# would be re-derived from that graph's size, not kept at 15 — noted here
# because it is the one constant in this module that is tied to a
# property of the data rather than to a judgment about regulation.
IMPACT_GAIN = 0.25
IMPACT_FACTOR_CEILING = 2.0


# ── Urgency: how close the effective date is ──────────────────────────────
# (max_days_to_effective, factor), first match wins, evaluated in order.
# Anything past the last step — and a change with no known effective date
# at all — gets DEADLINE_FACTOR_FLOOR (principle 4).
#
# The steps are the horizons a compliance function actually plans on:
#   <= 0    already in force (or overdue): the organization is exposed now
#   <= 30   inside the month: no time for a procurement or a project
#   <= 90   inside the quarter: fits one planning cycle, just
#   <= 180  half a year: plannable
#   <= 365  inside the year: on the roadmap
# The spread is intentionally narrow (1.00-1.60). Urgency should reorder a
# queue, not rewrite it: a deadline must never let an editorial fix
# outrank a new obligation, and at these values it cannot (editorial's
# ceiling is 4 points, new_obligation's floor is 38).
DEADLINE_FACTOR_STEPS: tuple[tuple[int, float], ...] = (
    (0, 1.60),
    (30, 1.50),
    (90, 1.30),
    (180, 1.15),
    (365, 1.05),
)
DEADLINE_FACTOR_FLOOR = 1.00


# ── Regulator weight ──────────────────────────────────────────────────────
# Comes from Regulator.weight (models.py), whose column default is 1.0.
# It is a relative dial between regulators — "GAMI matters more to us than
# SASO" — not an override of the severity model, so it is bounded: at most
# a doubling. A zero or negative weight is a data-entry bug, not a way to
# mute a regulator (mute it by not ingesting it), so it raises rather than
# silently scoring everything 0 — the project's no-silent-fallbacks rule.
DEFAULT_REGULATOR_WEIGHT = 1.0
REGULATOR_WEIGHT_CEILING = 2.0


# ── Bands: words first, numbers second ────────────────────────────────────
#   critical (75-100) "drop other work": a change that creates or raises a
#                     duty AND either reaches most of the organization or
#                     is close to its effective date. Act this week.
#   high     (50-74)  "this sprint": a material obligation change with real
#                     organizational reach, or a nearer deadline on a
#                     narrower one. Needs a named owner now.
#   medium   (25-49)  "this cycle": real but contained — few impacted
#                     nodes, no near deadline. Schedule it.
#   low      (0-24)   "log and monitor": immaterial changes, and material
#                     ones that touch nothing we own and carry no
#                     deadline. No action beyond the audit trail.
# The numeric thresholds order changes within a band; the words above are
# what the band means and what the UI should say.
BAND_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (75, "critical"),
    (50, "high"),
    (25, "medium"),
    (0, "low"),
)

# Materiality gate cap (principle 5). Sits one point below the medium
# threshold so a gated change always lands in low, mirroring ComplyX's
# "caps sit just below the band thresholds" rule.
IMMATERIAL_CAP = 24

SCORE_MIN = 0
SCORE_MAX = 100


# ── Factors ───────────────────────────────────────────────────────────────

def severity_weight(change_type: str) -> float:
    """Base points for a change type. Raises on anything outside the fixed
    vocabulary — including None, which means "not classified yet": an
    unclassified change has no priority, and inventing one (say, treating
    it as editorial) would silently bury it."""
    try:
        return SEVERITY_WEIGHT[change_type]
    except KeyError:
        raise ValueError(
            f"Unknown change_type {change_type!r}; expected one of {', '.join(CHANGE_TYPES)}"
        ) from None


def impact_factor(impacted_node_count: int) -> float:
    """Sublinear amplification by organizational reach (principle 2)."""
    if impacted_node_count < 0:
        raise ValueError(f"impacted_node_count must be >= 0, got {impacted_node_count}")
    return min(IMPACT_FACTOR_CEILING, 1.0 + IMPACT_GAIN * math.log2(1 + impacted_node_count))


def deadline_factor(days_to_effective: int | None) -> float:
    """Amplification by how near the effective date is (principles 3 and
    4). Non-increasing in days_to_effective; None == "further out than the
    last step"."""
    if days_to_effective is None:
        return DEADLINE_FACTOR_FLOOR
    for max_days, factor in DEADLINE_FACTOR_STEPS:
        if days_to_effective <= max_days:
            return factor
    return DEADLINE_FACTOR_FLOOR


def _effective_regulator_weight(regulator_weight: float) -> float:
    if regulator_weight <= 0:
        raise ValueError(
            f"regulator_weight must be > 0, got {regulator_weight} "
            f"(to exclude a regulator, do not ingest it; do not weight it to zero)"
        )
    return min(regulator_weight, REGULATOR_WEIGHT_CEILING)


def band_for_score(score: int) -> str:
    """Verbal band for a 0-100 score. See BAND_THRESHOLDS for what each
    band means."""
    for minimum, band in BAND_THRESHOLDS:
        if score >= minimum:
            return band
    return BAND_THRESHOLDS[-1][1]  # unreachable for a clamped score; belt and braces


# Normalization reference: the raw product of a maximally severe change
# that reaches the whole organization and is due inside the quarter. That
# case is defined to be exactly 100. Everything more urgent than it (a
# deadline inside 30 days, an already-effective change, a heavier
# regulator) clamps to 100 — deliberately, because ordering stops
# mattering once several changes are all "drop everything"; the ordering
# the score has to get right is the long tail below that line.
# Derived from the constants above rather than hard-coded, so a weight
# edit cannot silently rescale the bands under it.
REFERENCE_RAW = SEVERITY_WEIGHT["new_obligation"] * IMPACT_FACTOR_CEILING * deadline_factor(90)


# ── Scoring ───────────────────────────────────────────────────────────────

def explain_priority(
    change: "Change",
    impacted_node_count: int,
    days_to_effective: int | None,
    regulator_weight: float = DEFAULT_REGULATOR_WEIGHT,
) -> dict[str, Any]:
    """Full arithmetic behind compute_priority(), as a JSON-serializable
    dict: every factor, the ungated score, and the gate if one bound.

    Exists for the same reason ComplyX's ScoreBreakdown does — a score a
    compliance officer cannot take apart is a score they will not trust.
    M6 can drop this straight into an audit_log payload_json and M7 can
    render "why is this critical" without recomputing anything.
    """
    change_type = change.change_type
    weight = severity_weight(change_type)
    i_factor = impact_factor(impacted_node_count)
    d_factor = deadline_factor(days_to_effective)
    r_weight = _effective_regulator_weight(regulator_weight)

    raw = weight * i_factor * d_factor * r_weight
    ungated = max(SCORE_MIN, min(SCORE_MAX, int(round(100.0 * raw / REFERENCE_RAW))))

    # Materiality gate (principle 5). Honors both the change type and an
    # explicit material=False, so an analyst who marks an otherwise-heavy
    # change immaterial for this organization gets that respected — which
    # is the case where this gate actually binds, since editorial and
    # renumbered score well under the cap on arithmetic alone.
    immaterial = change_type in IMMATERIAL_CHANGE_TYPES or change.material is False
    gate: dict[str, Any] | None = None
    if immaterial and ungated > IMMATERIAL_CAP:
        gate = {"kind": "immaterial", "cap": IMMATERIAL_CAP}
    score = min(ungated, IMMATERIAL_CAP) if immaterial else ungated

    return {
        "score": score,
        "band": band_for_score(score),
        "severity_weight": weight,
        "impact_factor": round(i_factor, 4),
        "deadline_factor": d_factor,
        "regulator_weight": r_weight,
        "raw": round(raw, 4),
        "reference_raw": REFERENCE_RAW,
        "ungated_score": ungated,
        "gate": gate,
        "inputs": {
            "change_type": change_type,
            "material": change.material,
            "impacted_node_count": impacted_node_count,
            "days_to_effective": days_to_effective,
        },
    }


def compute_priority(
    change: "Change",
    impacted_node_count: int,
    days_to_effective: int | None,
    regulator_weight: float = DEFAULT_REGULATOR_WEIGHT,
) -> tuple[int, str]:
    """Returns (score 0-100, band) where band is one of "critical" |
    "high" | "medium" | "low".

    Pure function: same inputs always produce the same output. No DB, no
    I/O, no LLM call. Only `change.change_type` and `change.material` are
    read, so the caller controls every input to the number.

    regulator_weight defaults to 1.0, which is Regulator.weight's own
    column default and NCA's current value — so a caller with only a
    Change in hand can use the three-argument form and get the same answer
    it would get by looking the regulator up. Pass it explicitly (from
    change.regulation.regulator.weight, resolved by the caller, which
    already has the session) once more than one regulator is in scope.
    Threading it through as an argument rather than lazy-loading it off
    the relationship is what keeps this function pure and its determinism
    testable without a database.

    Raises ValueError on an unclassified/unknown change_type, a negative
    impacted_node_count, or a non-positive regulator_weight — never
    guesses a default (docs/PLAN.md section 7: no silent fallbacks).

    Use explain_priority() for the full arithmetic behind the number.
    """
    breakdown = explain_priority(change, impacted_node_count, days_to_effective, regulator_weight)
    return breakdown["score"], breakdown["band"]

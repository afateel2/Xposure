"""Unit tests for app/priority.py.

The formula is pure arithmetic, so these tests are not "does it roughly
work" — they pin every boundary, every documented property from the
module docstring, and monotonicity over a grid rather than at a couple of
sample points. If a constant is retuned, the properties are what should
fail first and force the docstring to be updated with it.
"""

import json
from types import SimpleNamespace

import pytest

from app import llm
from app.priority import (
    BAND_THRESHOLDS,
    CHANGE_TYPES,
    DEADLINE_FACTOR_FLOOR,
    IMMATERIAL_CAP,
    IMPACT_FACTOR_CEILING,
    REFERENCE_RAW,
    SEVERITY_WEIGHT,
    band_for_score,
    compute_priority,
    deadline_factor,
    explain_priority,
    impact_factor,
    severity_weight,
)


def _change(change_type: str | None, material: bool | None = None) -> SimpleNamespace:
    # compute_priority() reads exactly .change_type and .material, so a
    # duck-typed stand-in avoids needing a DB-backed Change/session here
    # (same approach tests/unit/test_diff.py takes for Clause).
    if material is None:
        material = change_type not in ("editorial", "renumbered")
    return SimpleNamespace(change_type=change_type, material=material)


# Every "what is the highest/lowest this type can score" search runs over
# this grid: it spans the whole domain of both multipliers (impact hits
# its ceiling at 15 nodes, the deadline steps top out at <= 0 days).
_NODE_COUNTS = (0, 1, 2, 3, 5, 7, 10, 15, 20, 50, 200)
_DAYS = (None, 1000, 366, 365, 200, 180, 100, 90, 45, 30, 7, 1, 0, -1, -400)


def _scores_for(change_type: str, regulator_weight: float = 1.0) -> list[int]:
    change = _change(change_type)
    return [
        compute_priority(change, n, d, regulator_weight)[0]
        for n in _NODE_COUNTS
        for d in _DAYS
    ]


# ── Vocabulary ────────────────────────────────────────────────────────────

def test_severity_weight_covers_exactly_the_classifier_vocabulary():
    # SEVERITY_WEIGHT's keys are deliberately a restatement of llm.py's
    # CHANGE_TYPES (priority.py stays free of the OpenAI client at import
    # time). This test is what keeps the restatement honest.
    assert set(CHANGE_TYPES) == set(llm.CHANGE_TYPES)
    assert set(SEVERITY_WEIGHT) == set(llm.CHANGE_TYPES)


def test_severity_ordering_matches_the_documented_reasoning():
    assert (
        SEVERITY_WEIGHT["new_obligation"]
        > SEVERITY_WEIGHT["tightened"]
        > SEVERITY_WEIGHT["withdrawn"]
        > SEVERITY_WEIGHT["clarification"]
        > SEVERITY_WEIGHT["relaxed"]
        > SEVERITY_WEIGHT["renumbered"]
        > SEVERITY_WEIGHT["editorial"]
    )


def test_unknown_change_type_raises_rather_than_defaulting():
    with pytest.raises(ValueError, match="Unknown change_type"):
        severity_weight("not_a_change_type")


def test_unclassified_change_raises():
    # change_type is nullable on the Change model (a row exists before
    # classification). An unclassified change has no priority; silently
    # treating it as the mildest type would bury it forever.
    with pytest.raises(ValueError, match="Unknown change_type"):
        compute_priority(_change(None), 3, None)


# ── impact_factor ─────────────────────────────────────────────────────────

def test_impact_factor_exact_values_at_the_documented_points():
    assert impact_factor(0) == pytest.approx(1.00)
    assert impact_factor(1) == pytest.approx(1.25)
    assert impact_factor(3) == pytest.approx(1.50)
    assert impact_factor(7) == pytest.approx(1.75)
    assert impact_factor(15) == pytest.approx(2.00)


def test_impact_factor_is_capped_at_the_ceiling():
    assert impact_factor(16) == IMPACT_FACTOR_CEILING
    assert impact_factor(10_000) == IMPACT_FACTOR_CEILING


def test_impact_factor_is_sublinear():
    # The jump from 0->1 node must be strictly larger than 10->11: one
    # more impacted node stops being news once there are already many.
    assert (impact_factor(1) - impact_factor(0)) > (impact_factor(11) - impact_factor(10))


def test_impact_factor_is_non_decreasing():
    values = [impact_factor(n) for n in range(0, 300)]
    assert all(b >= a for a, b in zip(values, values[1:]))


def test_negative_impacted_node_count_raises():
    with pytest.raises(ValueError, match="must be >= 0"):
        impact_factor(-1)
    with pytest.raises(ValueError, match="must be >= 0"):
        compute_priority(_change("tightened"), -1, None)


# ── deadline_factor ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "days, expected",
    [
        (-400, 1.60),  # long overdue
        (-1, 1.60),
        (0, 1.60),     # effective today
        (1, 1.50),
        (30, 1.50),    # boundary: still "inside the month"
        (31, 1.30),
        (90, 1.30),
        (91, 1.15),
        (180, 1.15),
        (181, 1.05),
        (365, 1.05),
        (366, 1.00),
        (10_000, 1.00),
    ],
)
def test_deadline_factor_step_boundaries(days: int, expected: float):
    assert deadline_factor(days) == pytest.approx(expected)


def test_no_known_deadline_is_neutral_not_a_penalty():
    # Principle 4: not knowing of a deadline must score exactly as a
    # far-future one, never below the floor.
    assert deadline_factor(None) == DEADLINE_FACTOR_FLOOR
    assert deadline_factor(None) == deadline_factor(10_000)


def test_deadline_factor_is_non_increasing_in_days():
    values = [deadline_factor(d) for d in range(-10, 500)]
    assert all(b <= a for a, b in zip(values, values[1:]))


# ── Bands ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "score, band",
    [
        (0, "low"), (1, "low"), (24, "low"),
        (25, "medium"), (49, "medium"),
        (50, "high"), (74, "high"),
        (75, "critical"), (100, "critical"),
    ],
)
def test_band_boundaries(score: int, band: str):
    assert band_for_score(score) == band


def test_band_thresholds_are_descending_and_cover_zero():
    minimums = [m for m, _ in BAND_THRESHOLDS]
    assert minimums == sorted(minimums, reverse=True)
    assert minimums[-1] == 0


def test_immaterial_cap_sits_just_below_the_medium_threshold():
    # A gated score must land in low, not on the medium boundary.
    medium_min = dict((b, m) for m, b in BAND_THRESHOLDS)["medium"]
    assert IMMATERIAL_CAP == medium_min - 1
    assert band_for_score(IMMATERIAL_CAP) == "low"


# ── Determinism ───────────────────────────────────────────────────────────

def test_same_inputs_always_give_the_same_number():
    change = _change("tightened")
    results = {compute_priority(change, 7, 45) for _ in range(50)}
    assert len(results) == 1


def test_two_distinct_objects_with_the_same_fields_score_identically():
    assert compute_priority(_change("relaxed"), 4, 200) == compute_priority(_change("relaxed"), 4, 200)


# ── Monotonicity (principle 6) ────────────────────────────────────────────

def test_more_impacted_nodes_never_lowers_the_score():
    for change_type in CHANGE_TYPES:
        for days in _DAYS:
            scores = [compute_priority(_change(change_type), n, days)[0] for n in range(0, 60)]
            assert all(b >= a for a, b in zip(scores, scores[1:])), (change_type, days)


def test_a_nearer_deadline_never_lowers_the_score():
    for change_type in CHANGE_TYPES:
        for nodes in _NODE_COUNTS:
            # range is descending in days => non-decreasing in urgency
            scores = [compute_priority(_change(change_type), nodes, d)[0] for d in range(400, -30, -1)]
            assert all(b >= a for a, b in zip(scores, scores[1:])), (change_type, nodes)


def test_a_more_severe_change_type_never_lowers_the_score():
    by_severity = sorted(CHANGE_TYPES, key=lambda ct: SEVERITY_WEIGHT[ct])
    for nodes in _NODE_COUNTS:
        for days in _DAYS:
            scores = [compute_priority(_change(ct), nodes, days)[0] for ct in by_severity]
            assert all(b >= a for a, b in zip(scores, scores[1:])), (nodes, days)


def test_a_heavier_regulator_never_lowers_the_score():
    for change_type in CHANGE_TYPES:
        scores = [
            compute_priority(_change(change_type), 5, 60, w)[0]
            for w in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 5.0)
        ]
        assert all(b >= a for a, b in zip(scores, scores[1:])), change_type


def test_no_known_deadline_never_outranks_a_known_one():
    for change_type in CHANGE_TYPES:
        for nodes in _NODE_COUNTS:
            unknown = compute_priority(_change(change_type), nodes, None)[0]
            for days in (-10, 0, 30, 90, 365, 10_000):
                assert compute_priority(_change(change_type), nodes, days)[0] >= unknown


# ── Documented properties (module docstring) ──────────────────────────────

def test_new_obligation_never_scores_below_medium_at_default_regulator_weight():
    floor = compute_priority(_change("new_obligation"), 0, None)
    assert floor == (38, "medium")
    assert min(_scores_for("new_obligation")) == 38


def test_only_new_obligation_and_tightened_can_reach_critical():
    reachable = {ct for ct in CHANGE_TYPES if max(_scores_for(ct)) >= 75}
    assert reachable == {"new_obligation", "tightened"}


@pytest.mark.parametrize(
    "change_type, ceiling, band",
    [
        ("withdrawn", 53, "high"),
        ("clarification", 44, "medium"),
        ("relaxed", 32, "medium"),
        ("renumbered", 9, "low"),
        ("editorial", 4, "low"),
    ],
)
def test_documented_score_ceilings_per_change_type(change_type: str, ceiling: int, band: str):
    highest = max(_scores_for(change_type))
    assert highest == ceiling
    assert band_for_score(highest) == band


def test_immaterial_types_are_always_low_even_at_maximum_impact_and_urgency():
    for change_type in ("editorial", "renumbered"):
        for n in _NODE_COUNTS:
            for d in _DAYS:
                score, band = compute_priority(_change(change_type), n, d)
                assert band == "low", (change_type, n, d, score)


def test_a_cosmetic_change_can_never_outrank_a_new_obligation():
    # The guarantee principle 1 claims: multipliers amplify, they do not
    # manufacture. The worst possible editorial change must stay below the
    # mildest possible new obligation.
    assert max(_scores_for("editorial")) < min(_scores_for("new_obligation"))
    assert max(_scores_for("renumbered")) < min(_scores_for("new_obligation"))


def test_reference_raw_is_derived_from_the_constants_not_hard_coded():
    assert REFERENCE_RAW == pytest.approx(SEVERITY_WEIGHT["new_obligation"] * IMPACT_FACTOR_CEILING * 1.30)
    # The reference case scores exactly 100 by construction.
    assert compute_priority(_change("new_obligation"), 15, 90)[0] == 100


def test_score_is_clamped_at_100():
    worst = compute_priority(_change("new_obligation"), 500, -100, 2.0)
    assert worst == (100, "critical")


# ── Materiality gate (principle 5) ────────────────────────────────────────

def test_explicit_material_false_caps_an_otherwise_high_change_into_low():
    ungated = compute_priority(_change("tightened", material=True), 15, 10)
    assert ungated[1] in ("high", "critical")  # otherwise this test proves nothing
    gated = compute_priority(_change("tightened", material=False), 15, 10)
    assert gated == (IMMATERIAL_CAP, "low")


def test_the_gate_is_reported_only_when_it_actually_binds():
    bound = explain_priority(_change("tightened", material=False), 15, 10)
    assert bound["gate"] == {"kind": "immaterial", "cap": IMMATERIAL_CAP}
    assert bound["ungated_score"] > bound["score"]

    # An editorial change scores under the cap on arithmetic alone, so
    # reporting a gate there would misleadingly suggest it was capped.
    not_bound = explain_priority(_change("editorial"), 15, 10)
    assert not_bound["gate"] is None
    assert not_bound["ungated_score"] == not_bound["score"]


def test_material_true_on_an_editorial_change_still_scores_low():
    # change_type wins over the flag: editorial is immaterial by
    # definition in this vocabulary.
    score, band = compute_priority(_change("editorial", material=True), 20, -5)
    assert band == "low"
    assert score <= IMMATERIAL_CAP


# ── Regulator weight ──────────────────────────────────────────────────────

def test_default_regulator_weight_matches_an_explicit_one():
    assert compute_priority(_change("tightened"), 5, 60) == compute_priority(_change("tightened"), 5, 60, 1.0)


def test_regulator_weight_is_clamped_at_the_ceiling():
    at_ceiling = compute_priority(_change("relaxed"), 2, 200, 2.0)
    way_over = compute_priority(_change("relaxed"), 2, 200, 99.0)
    assert at_ceiling == way_over


def test_non_positive_regulator_weight_raises():
    for weight in (0.0, -1.0):
        with pytest.raises(ValueError, match="regulator_weight must be > 0"):
            compute_priority(_change("tightened"), 3, None, weight)


def test_a_lighter_regulator_can_push_a_change_down_a_band():
    heavy = compute_priority(_change("tightened"), 7, 60, 1.0)
    light = compute_priority(_change("tightened"), 7, 60, 0.5)
    assert light[0] < heavy[0]


# ── explain_priority ──────────────────────────────────────────────────────

def test_breakdown_reports_every_factor_and_is_json_serializable():
    breakdown = explain_priority(_change("tightened"), 7, 45, 1.0)
    assert (breakdown["score"], breakdown["band"]) == compute_priority(_change("tightened"), 7, 45, 1.0)
    assert breakdown["severity_weight"] == SEVERITY_WEIGHT["tightened"]
    assert breakdown["impact_factor"] == pytest.approx(1.75)
    assert breakdown["deadline_factor"] == pytest.approx(1.30)
    assert breakdown["regulator_weight"] == 1.0
    assert breakdown["inputs"] == {
        "change_type": "tightened",
        "material": True,
        "impacted_node_count": 7,
        "days_to_effective": 45,
    }
    # M6 writes this into audit_log.payload_json / M7 renders it.
    json.dumps(breakdown)


def test_breakdown_arithmetic_reproduces_the_score():
    breakdown = explain_priority(_change("new_obligation"), 3, 20)
    raw = (
        breakdown["severity_weight"]
        * breakdown["impact_factor"]
        * breakdown["deadline_factor"]
        * breakdown["regulator_weight"]
    )
    assert raw == pytest.approx(breakdown["raw"], abs=0.01)
    assert round(100.0 * raw / breakdown["reference_raw"]) == breakdown["ungated_score"]


def test_compute_priority_agrees_with_the_breakdown_everywhere():
    for change_type in CHANGE_TYPES:
        for n in _NODE_COUNTS:
            for d in _DAYS:
                breakdown = explain_priority(_change(change_type), n, d)
                assert compute_priority(_change(change_type), n, d) == (breakdown["score"], breakdown["band"])


def test_works_on_a_real_change_orm_object_not_just_a_stand_in():
    # priority.py only type-hints Change under TYPE_CHECKING and reads two
    # attributes off it, so nothing in the unit tests above would notice
    # if the real model's field names drifted. Constructing a real ORM
    # instance (no session, no DB) is what actually pins that contract.
    from app.db.models import Change

    row = Change(
        regulation_id=1,
        from_version_id=1,
        to_version_id=2,
        old_clause_id="2-5-3",
        new_clause_id="2-5-3",
        match_kind="exact_id",
        change_type="tightened",
        material=True,
        confidence=0.88,
    )
    assert compute_priority(row, 7, 45) == (69, "high")

    row.material = False
    assert compute_priority(row, 7, 45) == (IMMATERIAL_CAP, "low")


# ── Worked examples (the numbers quoted in the module docstring / report) ──

@pytest.mark.parametrize(
    "change_type, nodes, days, expected_score, expected_band",
    [
        ("new_obligation", 0, None, 38, "medium"),    # new duty, nothing mapped, no date
        ("new_obligation", 3, None, 58, "high"),      # typical ECC-2 new control
        ("new_obligation", 3, 20, 87, "critical"),    # same, three weeks out
        ("new_obligation", 15, None, 77, "critical"), # org-wide, no date needed to be critical
        ("tightened", 3, None, 45, "medium"),
        ("tightened", 7, 100, 61, "high"),
        ("withdrawn", 3, None, 25, "medium"),
        ("clarification", 1, None, 17, "low"),
        ("relaxed", 8, None, 18, "low"),
        ("editorial", 15, 0, 4, "low"),
    ],
)
def test_worked_examples(change_type: str, nodes: int, days: int | None, expected_score: int, expected_band: str):
    assert compute_priority(_change(change_type), nodes, days) == (expected_score, expected_band)

"""Unit tests for app/policy.py.

The gates are the reason this module exists, so most of these tests are
property-style and exhaustive over the full vocabulary cross-product
rather than spot checks: "new_obligation never auto-executes" is only
worth anything if it is checked against every action type, every
confidence, and a policy file that asks for auto_execute everywhere.
"""

import json

import pytest
import yaml

from app import llm, priority
from app.policy import (
    ACTION_TYPES,
    AUTOMATION_LEVELS,
    AUTO_EXECUTABLE_ACTION_TYPES,
    AUTO_EXECUTABLE_CHANGE_TYPES,
    CHANGE_TYPES,
    DEFAULT_LEVEL,
    MIN_AUTO_EXECUTE_CONFIDENCE,
    POLICY_PATH,
    AutomationPolicy,
    decide_automation,
    explain_automation,
    load_policy,
    parse_policy,
)

# A policy that asks for the maximum automation everywhere. Every gate
# test runs against this: if a gate holds even when the configuration is
# begging for auto_execute, it holds.
PERMISSIVE = AutomationPolicy(default_level="auto_execute", action_levels={})

# The opposite: configuration asking for the minimum everywhere.
RESTRICTIVE = AutomationPolicy(default_level="notify_only", action_levels={})

_CONFIDENCES = (0.0, 0.1, 0.5, 0.69, 0.7, 0.71, 0.9, 0.99, 1.0)


# ── Vocabulary ────────────────────────────────────────────────────────────

def test_action_vocabulary_is_the_fixed_seven():
    assert set(ACTION_TYPES) == {
        "update_policy",
        "update_procedure",
        "technical_change",
        "collect_evidence",
        "reassess_control",
        "notify_owner",
        "request_license_review",
    }


def test_change_vocabulary_matches_the_classifier_and_priority_module():
    # policy.py restates the vocabulary instead of importing it from
    # llm.py (which would drag the OpenAI client and .env into a pure
    # module). This test is what keeps all three copies in step.
    assert set(CHANGE_TYPES) == set(llm.CHANGE_TYPES)
    assert set(CHANGE_TYPES) == set(priority.CHANGE_TYPES)


def test_levels_are_ordered_least_to_most_automation():
    assert AUTOMATION_LEVELS == ("notify_only", "draft_then_approve", "auto_execute")
    assert DEFAULT_LEVEL == "draft_then_approve"


# ── The shipped policy file ───────────────────────────────────────────────

def test_shipped_policy_file_loads_and_validates():
    policy = load_policy()
    assert policy.default_level in AUTOMATION_LEVELS
    assert set(policy.action_levels) <= set(ACTION_TYPES)


def test_shipped_policy_file_covers_every_action_type_explicitly():
    # Not strictly required (default_level catches the rest), but an
    # action type whose level nobody wrote down is an action type nobody
    # thought about.
    policy = load_policy()
    assert set(policy.action_levels) == set(ACTION_TYPES)


def test_shipped_policy_actually_exercises_auto_execute_somewhere():
    # If nothing ever auto-executes, the demo never shows the agent doing
    # anything unsupervised and the whole gate structure is untested in
    # practice. collect_evidence/notify_owner on a clarification is the
    # intended live path.
    policy = load_policy()
    assert "auto_execute" in policy.action_levels.values()
    assert decide_automation("collect_evidence", "clarification", 0.9, policy) == "auto_execute"


def test_shipped_policy_yaml_parses_to_the_same_thing_as_the_loader():
    with POLICY_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert parse_policy(data, source=str(POLICY_PATH)) == load_policy()


# ── G1: only clarification/editorial may ever auto-execute ────────────────

def test_no_other_change_type_ever_auto_executes():
    for change_type in CHANGE_TYPES:
        if change_type in AUTO_EXECUTABLE_CHANGE_TYPES:
            continue
        for action_type in ACTION_TYPES:
            for confidence in _CONFIDENCES:
                level = decide_automation(action_type, change_type, confidence, PERMISSIVE)
                assert level != "auto_execute", (change_type, action_type, confidence)


def test_clarification_and_editorial_can_auto_execute_when_everything_else_allows():
    for change_type in ("clarification", "editorial"):
        for action_type in sorted(AUTO_EXECUTABLE_ACTION_TYPES):
            assert decide_automation(action_type, change_type, 1.0, PERMISSIVE) == "auto_execute"


# ── G2: new_obligation always ends up as a tracked human decision ─────────

def test_new_obligation_never_auto_executes_for_any_action_type_or_confidence():
    for action_type in ACTION_TYPES:
        for confidence in _CONFIDENCES:
            level = decide_automation(action_type, "new_obligation", confidence, PERMISSIVE)
            assert level != "auto_execute", (action_type, confidence)


def test_new_obligation_is_never_merely_notify_only_even_when_configured_that_way():
    # The documented decision (module docstring G2): a bare notification
    # leaves no record of a decision, and a brand new duty is exactly the
    # case that must end in an owned approve/dismiss.
    for action_type in ACTION_TYPES:
        for confidence in _CONFIDENCES:
            level = decide_automation(action_type, "new_obligation", confidence, RESTRICTIVE)
            assert level == "draft_then_approve", (action_type, confidence)


def test_new_obligation_is_pinned_to_draft_then_approve_under_any_policy():
    for policy in (PERMISSIVE, RESTRICTIVE, load_policy()):
        for action_type in ACTION_TYPES:
            for confidence in _CONFIDENCES:
                assert decide_automation(action_type, "new_obligation", confidence, policy) == "draft_then_approve"


def test_the_floor_is_only_applied_to_new_obligation():
    # Every other change type must still be able to sit at notify_only if
    # that is what the organization asked for.
    for change_type in CHANGE_TYPES:
        if change_type == "new_obligation":
            continue
        assert decide_automation("technical_change", change_type, 1.0, RESTRICTIVE) == "notify_only"


# ── G3: only collect_evidence/notify_owner are auto-executable actions ────

def test_no_other_action_type_ever_auto_executes():
    for action_type in ACTION_TYPES:
        if action_type in AUTO_EXECUTABLE_ACTION_TYPES:
            continue
        for change_type in CHANGE_TYPES:
            for confidence in _CONFIDENCES:
                level = decide_automation(action_type, change_type, confidence, PERMISSIVE)
                assert level != "auto_execute", (action_type, change_type, confidence)


def test_a_clarification_can_never_auto_apply_a_technical_change():
    # The specific combination G3 exists for: G1 alone would let this
    # through, and "the regulator clarified something, so we reconfigured
    # a production system by ourselves" is not an acceptable outcome.
    assert decide_automation("technical_change", "clarification", 1.0, PERMISSIVE) == "draft_then_approve"


# ── G4: confidence boundary ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "confidence, expected",
    [
        (0.0, "draft_then_approve"),
        (0.69, "draft_then_approve"),
        (0.6999999, "draft_then_approve"),
        (0.7, "auto_execute"),     # "below 0.7" is exclusive: 0.7 itself passes
        (0.71, "auto_execute"),
        (1.0, "auto_execute"),
    ],
)
def test_confidence_boundary_is_exactly_at_the_threshold(confidence: float, expected: str):
    assert decide_automation("collect_evidence", "clarification", confidence, PERMISSIVE) == expected


def test_the_threshold_constant_and_the_comparison_agree():
    assert MIN_AUTO_EXECUTE_CONFIDENCE == 0.7
    assert decide_automation("collect_evidence", "clarification", MIN_AUTO_EXECUTE_CONFIDENCE, PERMISSIVE) == "auto_execute"


def test_low_confidence_caps_every_combination_at_human_review():
    for action_type in ACTION_TYPES:
        for change_type in CHANGE_TYPES:
            for confidence in (0.0, 0.3, 0.5, 0.69):
                assert decide_automation(action_type, change_type, confidence, PERMISSIVE) != "auto_execute"


def test_low_confidence_does_not_downgrade_below_the_configured_level():
    # The confidence gate caps automation; it must not silently turn a
    # configured draft_then_approve into a notification nobody tracks.
    policy = AutomationPolicy(default_level="draft_then_approve", action_levels={})
    assert decide_automation("collect_evidence", "clarification", 0.1, policy) == "draft_then_approve"


# ── The full cross-product ────────────────────────────────────────────────

def test_auto_execute_happens_exactly_where_all_four_gates_agree():
    # An independent restatement of the gate conditions, checked against
    # the implementation over every combination: 7 action types x 7 change
    # types x 9 confidences.
    for action_type in ACTION_TYPES:
        for change_type in CHANGE_TYPES:
            for confidence in _CONFIDENCES:
                expected_auto = (
                    change_type in ("clarification", "editorial")
                    and action_type in ("collect_evidence", "notify_owner")
                    and confidence >= 0.7
                )
                level = decide_automation(action_type, change_type, confidence, PERMISSIVE)
                assert (level == "auto_execute") == expected_auto, (action_type, change_type, confidence)


def test_configuration_can_always_ask_for_less_automation():
    # The asymmetry the module is built around: notify_only is honored
    # everywhere except where G2's floor applies (new_obligation).
    for action_type in ACTION_TYPES:
        for change_type in CHANGE_TYPES:
            for confidence in _CONFIDENCES:
                level = decide_automation(action_type, change_type, confidence, RESTRICTIVE)
                expected = "draft_then_approve" if change_type == "new_obligation" else "notify_only"
                assert level == expected, (action_type, change_type, confidence)


def test_every_decision_is_a_valid_level():
    for action_type in ACTION_TYPES:
        for change_type in CHANGE_TYPES:
            for confidence in _CONFIDENCES:
                assert decide_automation(action_type, change_type, confidence, PERMISSIVE) in AUTOMATION_LEVELS


def test_decisions_are_deterministic():
    results = {decide_automation("collect_evidence", "clarification", 0.8, PERMISSIVE) for _ in range(50)}
    assert len(results) == 1


# ── explain_automation ────────────────────────────────────────────────────

def test_explain_reports_no_gates_when_the_request_is_granted_as_written():
    detail = explain_automation("collect_evidence", "clarification", 0.95, PERMISSIVE)
    assert detail["level"] == "auto_execute"
    assert detail["requested"] == "auto_execute"
    assert detail["gates"] == []


def test_explain_names_each_gate_that_moved_the_level():
    detail = explain_automation("technical_change", "new_obligation", 0.2, PERMISSIVE)
    assert detail["level"] == "draft_then_approve"
    # The floor does not bind here (the request was already above it); the
    # first cap does, and the later caps are then no-ops.
    assert detail["gates"] == ["change_type_not_auto_executable"]

    raised = explain_automation("notify_owner", "new_obligation", 0.9, RESTRICTIVE)
    assert raised["gates"] == ["tracked_decision_change_type"]
    assert raised["level"] == "draft_then_approve"

    confidence_only = explain_automation("collect_evidence", "editorial", 0.4, PERMISSIVE)
    assert confidence_only["gates"] == ["confidence_below_threshold"]

    action_only = explain_automation("update_policy", "editorial", 0.9, PERMISSIVE)
    assert action_only["gates"] == ["action_type_not_auto_executable"]


def test_explain_output_is_json_serializable_for_the_audit_log():
    detail = explain_automation("reassess_control", "tightened", 0.55, PERMISSIVE)
    json.dumps(detail)
    assert detail["inputs"] == {
        "action_type": "reassess_control",
        "change_type": "tightened",
        "confidence": 0.55,
    }


def test_explain_and_decide_always_agree():
    for action_type in ACTION_TYPES:
        for change_type in CHANGE_TYPES:
            for confidence in _CONFIDENCES:
                detail = explain_automation(action_type, change_type, confidence, PERMISSIVE)
                assert detail["level"] == decide_automation(action_type, change_type, confidence, PERMISSIVE)


# ── Input validation (no silent fallbacks) ────────────────────────────────

def test_unknown_action_type_raises():
    with pytest.raises(ValueError, match="Unknown action_type"):
        decide_automation("delete_everything", "clarification", 0.9, PERMISSIVE)


def test_unknown_change_type_raises():
    with pytest.raises(ValueError, match="Unknown change_type"):
        decide_automation("notify_owner", "brand_new_category", 0.9, PERMISSIVE)


def test_unclassified_change_type_raises():
    with pytest.raises(ValueError, match="Unknown change_type"):
        decide_automation("notify_owner", None, 0.9, PERMISSIVE)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, "0.9", None, True])
def test_invalid_confidence_raises(confidence):
    with pytest.raises(ValueError, match="confidence must be"):
        decide_automation("notify_owner", "clarification", confidence, PERMISSIVE)


# ── Policy loading and validation ─────────────────────────────────────────

def test_parse_policy_accepts_a_minimal_document():
    policy = parse_policy({})
    assert policy.default_level == DEFAULT_LEVEL
    assert policy.action_levels == {}
    assert policy.requested_level("update_policy") == DEFAULT_LEVEL


def test_parse_policy_rejects_an_invalid_level():
    with pytest.raises(ValueError, match="invalid automation level"):
        parse_policy({"action_levels": {"notify_owner": "just_do_it"}})
    with pytest.raises(ValueError, match="invalid automation level"):
        parse_policy({"default_level": "yolo"})


def test_parse_policy_rejects_an_unknown_action_type():
    # A typo'd key would otherwise silently fall back to default_level —
    # a level nobody chose, with nothing to show it happened.
    with pytest.raises(ValueError, match="unknown action type"):
        parse_policy({"action_levels": {"notify_ownr": "auto_execute"}})


def test_parse_policy_rejects_a_non_mapping():
    with pytest.raises(ValueError, match="expected a YAML mapping"):
        parse_policy(["notify_only"])
    with pytest.raises(ValueError, match="must be a mapping"):
        parse_policy({"action_levels": ["notify_only"]})


def test_missing_policy_file_fails_loudly_and_names_the_path(tmp_path):
    missing = tmp_path / "no_such_policy.yaml"
    with pytest.raises(FileNotFoundError, match="no_such_policy.yaml"):
        load_policy(missing)


def test_load_policy_reads_a_real_file(tmp_path):
    path = tmp_path / "automation_policy.yaml"
    path.write_text(
        "default_level: notify_only\naction_levels:\n  collect_evidence: auto_execute\n",
        encoding="utf-8",
    )
    policy = load_policy(path)
    assert policy.default_level == "notify_only"
    assert policy.requested_level("collect_evidence") == "auto_execute"
    assert policy.requested_level("update_policy") == "notify_only"
    # Cached: a second call must not re-read the file.
    assert load_policy(path) is policy


def test_policy_objects_are_immutable():
    with pytest.raises(Exception):
        PERMISSIVE.default_level = "notify_only"  # type: ignore[misc]


# ── End-to-end against the shipped configuration ──────────────────────────

@pytest.mark.parametrize(
    "action_type, change_type, confidence, expected",
    [
        # The live auto-execute paths in the demo.
        ("collect_evidence", "clarification", 0.9, "auto_execute"),
        ("notify_owner", "editorial", 0.85, "auto_execute"),
        # Same action, but the classifier is not sure enough.
        ("collect_evidence", "clarification", 0.65, "draft_then_approve"),
        # A real ECC-2:2024 shape: a tightened control needing a policy edit.
        ("update_policy", "tightened", 0.92, "draft_then_approve"),
        # A brand new obligation: tracked decision, never a bare notification.
        ("request_license_review", "new_obligation", 0.95, "draft_then_approve"),
        ("technical_change", "new_obligation", 0.95, "draft_then_approve"),
        # Configuration asking for less is honored.
        ("technical_change", "tightened", 0.95, "notify_only"),
        ("request_license_review", "withdrawn", 0.95, "notify_only"),
    ],
)
def test_shipped_policy_end_to_end(action_type: str, change_type: str, confidence: float, expected: str):
    assert decide_automation(action_type, change_type, confidence) == expected

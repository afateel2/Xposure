"""
Automation policy (M5): how much of a recommended action Xposure may do
without a human, for one (action_type, change_type, confidence) triple.

The organization configures what it WANTS in
backend/data/org/automation_policy.yaml. This module decides what it
GETS, by intersecting that request with hard gates written as `if`
statements below. The asymmetry is the whole point and is stated in the
takeoff prompt's guardrails: configuration may only ever ask for less
automation than the gates allow, never more. A YAML file is an artifact a
tired person edits at 2am the night before an audit; the rule "a brand
new regulatory obligation is never actioned without a human" is not
something that should be one typo away from being off.

Levels, ordered least to most automation (AUTOMATION_LEVELS):
  notify_only        Tell the owner. Xposure takes no further action and
                     opens nothing to chase.
  draft_then_approve Xposure prepares the action; a human approves or
                     dismisses it. Nothing takes effect unapproved. The
                     project default (takeoff prompt section 3 / M5).
  auto_execute       Xposure performs it and records it in the audit log.

The gates, and why each one is code and not configuration:

  G1. AUTO_EXECUTABLE_CHANGE_TYPES — only `clarification` and `editorial`
      may ever auto-execute. Verbatim from the takeoff prompt. Everything
      else caps at draft_then_approve. These two are exactly the types
      where the obligation itself did not move, so acting on them cannot
      change what the organization is committed to.

  G2. TRACKED_DECISION_CHANGE_TYPES — a `new_obligation` is pinned to
      draft_then_approve from BOTH directions. Never auto_execute (the
      takeoff prompt says so outright) and never notify_only either. The
      takeoff prompt left that second half open; the decision, and the
      reasoning: notify_only produces a message and no record of a
      decision, so the failure mode is an unread notification and an
      organization that is quietly non-compliant with a duty nobody
      accepted or rejected. A new obligation is precisely the case that
      must end in a recorded approve-or-dismiss with an owner's name on
      it. Raising notify_only to draft_then_approve is safe by
      construction: draft_then_approve still executes nothing without a
      human, so this floor adds accountability, never autonomy.

  G3. AUTO_EXECUTABLE_ACTION_TYPES — only `collect_evidence` and
      `notify_owner` are auto-executable action types at all. Both are
      additive and reversible: one gathers an artifact, the other sends a
      message. Every other action type either edits a governed document
      (update_policy, update_procedure), touches a production system in a
      defense manufacturing environment (technical_change), changes a
      compliance assertion of record (reassess_control), or opens an
      interaction with an authority (request_license_review). G1 alone
      would already stop most of these, but "a clarification may
      auto-execute" plus "this action type happens to be a firewall rule
      change" is a combination that should not depend on both halves of
      the policy staying sane independently.

  G4. MIN_AUTO_EXECUTE_CONFIDENCE = 0.7 — below it, a human always
      decides. Verbatim from the takeoff prompt. The comparison is
      `confidence < 0.7`, so exactly 0.7 is allowed and 0.69 is not; the
      boundary is pinned by tests rather than left to a reader's guess.
      This is the backstop diff.py's module docstring explicitly relies on
      for its embedding-similarity false positives (docs/PLAN.md M3), so
      it is load-bearing well beyond this module.

Precedence: the floor (G2) is applied first, then every cap (G1, G3, G4).
Caps therefore win any disagreement. Floors exist so real work does not go
untracked; caps exist so the agent does not act unsupervised. If the two
ever conflict, not acting is the failure we can live with. With today's
gates there is no conflict to resolve — G2's floor and every cap both sit
at draft_then_approve — but the order is fixed in code so that adding a
stricter cap later cannot accidentally be overridden by a floor.

Determinism (takeoff prompt section 7: the same inputs always give the
same answer): the decision is a pure function of
(action_type, change_type, confidence, policy). The only I/O in this
module is reading the YAML once per process, cached; pass a policy
explicitly to make even that go away, as the tests do.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# app/policy.py -> app/ -> backend/ -> backend/data/org/automation_policy.yaml
POLICY_PATH = Path(__file__).parent.parent / "data" / "org" / "automation_policy.yaml"

# Ordered least to most automation. The order IS the semantics: every gate
# below is expressed as "at most" or "at least" a level, and both are
# comparisons on this list's index.
AUTOMATION_LEVELS: tuple[str, ...] = ("notify_only", "draft_then_approve", "auto_execute")
_LEVEL_RANK: dict[str, int] = {level: rank for rank, level in enumerate(AUTOMATION_LEVELS)}

# The default the takeoff prompt names, used for any action type the YAML
# does not mention. It is the middle level deliberately: an unrecognized
# action type should neither be silently automated nor silently reduced to
# a notification nobody tracks.
DEFAULT_LEVEL = "draft_then_approve"

# The fixed action vocabulary (takeoff prompt section 3 / M4). The LLM may
# only choose from this list when recommending actions, and this module
# rejects anything outside it rather than falling back to a default —
# an unknown action type means the vocabulary drifted somewhere upstream,
# which is a bug to surface, not to paper over.
ACTION_TYPES: tuple[str, ...] = (
    "update_policy",
    "update_procedure",
    "technical_change",
    "collect_evidence",
    "reassess_control",
    "notify_owner",
    "request_license_review",
)

# Mirrors app/llm.py's CHANGE_TYPES (and app/priority.py's SEVERITY_WEIGHT
# keys). Restated rather than imported so this module stays free of the
# OpenAI client and .env at import time; a unit test asserts all three
# lists still agree, so drift fails the suite instead of going unnoticed.
CHANGE_TYPES: tuple[str, ...] = (
    "new_obligation",
    "tightened",
    "relaxed",
    "clarification",
    "editorial",
    "renumbered",
    "withdrawn",
)

# ── The gates (see the module docstring for the reasoning behind each) ────
AUTO_EXECUTABLE_CHANGE_TYPES: frozenset[str] = frozenset({"clarification", "editorial"})   # G1
TRACKED_DECISION_CHANGE_TYPES: frozenset[str] = frozenset({"new_obligation"})              # G2
TRACKED_DECISION_FLOOR = "draft_then_approve"                                              # G2
AUTO_EXECUTABLE_ACTION_TYPES: frozenset[str] = frozenset({"collect_evidence", "notify_owner"})  # G3
MIN_AUTO_EXECUTE_CONFIDENCE = 0.7                                                          # G4

# Every cap in this module caps to the same level: a human in the loop,
# with the action still prepared for them. Named once so a future gate
# cannot quietly introduce a different ceiling.
HUMAN_REVIEW_CEILING = "draft_then_approve"


@dataclass(frozen=True)
class AutomationPolicy:
    """What the organization asked for, validated. Frozen: loaded once and
    shared, never mutated by a caller mid-run (which would break the
    determinism guarantee for everything scored after it)."""

    default_level: str
    action_levels: dict[str, str]

    def requested_level(self, action_type: str) -> str:
        return self.action_levels.get(action_type, self.default_level)


def _validate_level(level: Any, where: str) -> str:
    if level not in _LEVEL_RANK:
        raise ValueError(
            f"{where}: invalid automation level {level!r}; "
            f"expected one of {', '.join(AUTOMATION_LEVELS)}"
        )
    return level


def parse_policy(data: dict[str, Any], source: str = "<dict>") -> AutomationPolicy:
    """Validate a parsed YAML document into an AutomationPolicy.

    Every failure raises with the offending key named. A policy file that
    is subtly wrong (a typo'd action type silently falling back to the
    default, say) is worse than one that is loudly wrong: the first sets a
    level nobody intended and nobody sees.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{source}: expected a YAML mapping at the top level, got {type(data).__name__}")

    default_level = _validate_level(data.get("default_level", DEFAULT_LEVEL), f"{source}: default_level")

    raw_levels = data.get("action_levels") or {}
    if not isinstance(raw_levels, dict):
        raise ValueError(f"{source}: action_levels must be a mapping of action_type -> level")

    action_levels: dict[str, str] = {}
    for action_type, level in raw_levels.items():
        if action_type not in ACTION_TYPES:
            raise ValueError(
                f"{source}: unknown action type {action_type!r} in action_levels; "
                f"the vocabulary is fixed: {', '.join(ACTION_TYPES)}"
            )
        action_levels[action_type] = _validate_level(level, f"{source}: action_levels.{action_type}")

    return AutomationPolicy(default_level=default_level, action_levels=action_levels)


@lru_cache(maxsize=None)
def load_policy(path: Path | None = None) -> AutomationPolicy:
    """Load and validate the automation policy YAML, once per process.

    Fails loudly and says exactly which file it wanted if it is missing
    (docs/PLAN.md section 7 / no silent fallbacks) — running the agent
    against a built-in default while the operator believes their file is
    in force is exactly the silent divergence that rule exists to stop.
    """
    resolved = path or POLICY_PATH
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Automation policy file not found: {resolved}\n"
            f"Expected a YAML file at that exact path (see app/policy.py's module docstring for its schema)."
        )
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return parse_policy(data if data is not None else {}, source=str(resolved))


# ── Editing (see routes/settings.py) ──────────────────────────────────────
# docs/DESIGN.md's own Roadmap named exactly this as deferred, and said
# exactly why: "no auth means no reviewer identity to attach to a policy
# change, which is a worse gap than the missing feature." Now that
# app/auth.py exists, PUT /settings/policy (admin role only) writes here.
# The file stays the single source of truth (not a second DB-backed copy
# that could drift from it) and every hard gate above still applies
# exactly as it does to a hand-edited file — this only changes who edits
# it and whether the edit is attributed and audited.

_ACTION_TYPE_COMMENTS: dict[str, str] = {
    "update_policy": (
        "A policy is an approved, versioned governance artifact; editing one\n"
        "  # without sign-off defeats the control it documents."
    ),
    "update_procedure": (
        "Same reasoning one level down: a procedure is still a controlled\n"
        "  # document with an owner who answers for it in an audit."
    ),
    "technical_change": (
        "A configuration change to a production system in a defense\n"
        "  # manufacturing environment goes through the organization's own change\n"
        "  # management, not through us. Xposure's job here is to tell the owner\n"
        "  # what the regulator now requires; the engineering decision is theirs.\n"
        "  # (app/policy.py also refuses to auto-execute this type outright.)"
    ),
    "collect_evidence": (
        "Additive and reversible: gathering an artifact and attaching it to a\n"
        "  # control asserts nothing and breaks nothing. The one action type where\n"
        "  # unsupervised execution is genuinely low-risk, so it is the main reason\n"
        "  # auto_execute exists at all."
    ),
    "reassess_control": (
        "Changing a control's assessed status is a compliance assertion of\n"
        "  # record, the thing an auditor or regulator relies on. A human owns it."
    ),
    "notify_owner": (
        "Worst case is an unnecessary email. Safe to automate, and the value of\n"
        "  # the whole product is that the right person hears about a change in\n"
        "  # days instead of weeks."
    ),
    "request_license_review": (
        "An outbound interaction with an authority (GAMI, NCA). A human decides\n"
        "  # when this organization approaches its regulator.\n"
        "  # (app/policy.py also refuses to auto-execute this type outright.)"
    ),
}


def render_policy_yaml(policy: AutomationPolicy) -> str:
    """The inverse of parse_policy(): a policy object back to the YAML text
    saved to POLICY_PATH. Regenerates the explanatory header and a fixed,
    known comment per action type (see _ACTION_TYPE_COMMENTS above), kept as
    close to the original hand-written file's depth as a template can get,
    rather than attempting to preserve a hand-edited file's exact prose
    byte-for-byte: the semantics are what matters and those are fixed by
    policy.py, not by whatever comment happened to be in the file before
    this save."""
    lines = [
        "# Automation policy, how much of each recommended action Xposure may do",
        "# without a human (see app/policy.py). Editable from Settings (admin role",
        "# only, PUT /settings/policy) since app/auth.py gave this project real",
        "# reviewer identity; every edit is audited (event policy_updated).",
        "#",
        "# READ THIS BEFORE EDITING",
        "# ------------------------",
        "# This file can only ever make Xposure MORE cautious than the hard gates",
        "# in app/policy.py, never less. Those gates are `if` statements in code,",
        "# not configuration, precisely so that a bad edit here cannot switch on",
        "# unsupervised automation the project has decided must never happen:",
        "#",
        "#   * Only `clarification` and `editorial` changes may ever auto_execute.",
        "#   * A `new_obligation` always goes to a human, and always as a tracked",
        "#     approve/dismiss decision (never a bare notification).",
        "#   * Classification confidence below 0.7 always goes to a human.",
        "#   * Only `collect_evidence` and `notify_owner` are auto-executable",
        "#     action types at all, whatever this file says.",
        "#",
        "# So writing `auto_execute` below is a REQUEST, granted only when every",
        "# gate agrees. Writing `notify_only` is always honored: you can always",
        "# ask for less automation, never for more.",
        "#",
        "# Levels, least to most automation:",
        "#   notify_only        tell the owner; Xposure does nothing else and",
        "#                      opens no action item to chase.",
        "#   draft_then_approve Xposure prepares the action and a human approves or",
        "#                      dismisses it. Nothing takes effect unapproved.",
        "#                      This is the project default.",
        "#   auto_execute       Xposure performs it and records it in the audit log.",
        "",
        "version: 1",
        "",
        "# Applied to any action type not named in action_levels below. Kept at the",
        "# project's stated default so that adding a new action type to the",
        "# vocabulary fails safe rather than silently inheriting someone's",
        "# auto_execute.",
        f"default_level: {policy.default_level}",
        "",
        "# Per action type, for the fixed action vocabulary.",
        "action_levels:",
        "",
    ]
    for action_type in ACTION_TYPES:
        comment = _ACTION_TYPE_COMMENTS.get(action_type)
        if comment:
            lines.append(f"  # {comment}")
        level = policy.action_levels.get(action_type, policy.default_level)
        lines.append(f"  {action_type}: {level}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_policy(policy: AutomationPolicy, path: Path | None = None) -> None:
    """Validate (parse_policy on the object's own dict form, so a caller
    cannot write something this module itself would reject), write
    atomically (temp file + rename, never a half-written file on a crash
    mid-write), then clear the process-wide load_policy() cache so the
    very next pipeline run sees it."""
    resolved = path or POLICY_PATH
    as_dict = {"default_level": policy.default_level, "action_levels": dict(policy.action_levels)}
    parse_policy(as_dict, source="<PUT /settings/policy>")  # raises if invalid
    text = render_policy_yaml(policy)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(resolved)
    load_policy.cache_clear()


# ── Level algebra ─────────────────────────────────────────────────────────

def _at_most(level: str, ceiling: str) -> str:
    return level if _LEVEL_RANK[level] <= _LEVEL_RANK[ceiling] else ceiling


def _at_least(level: str, floor: str) -> str:
    return level if _LEVEL_RANK[level] >= _LEVEL_RANK[floor] else floor


# ── Decision ──────────────────────────────────────────────────────────────

def explain_automation(
    action_type: str,
    change_type: str,
    confidence: float,
    policy: AutomationPolicy | None = None,
) -> dict[str, Any]:
    """The decision plus which gates produced it, as a JSON-serializable
    dict: {"level", "requested", "gates": [...], "inputs": {...}}.

    `gates` lists, in the order applied, every gate that actually moved
    the level — an empty list means the YAML's request was granted as
    written. M6 can put this straight into an audit_log payload so
    "why did this need my approval" is answerable months later without
    re-deriving it.
    """
    if action_type not in ACTION_TYPES:
        raise ValueError(
            f"Unknown action_type {action_type!r}; the vocabulary is fixed: {', '.join(ACTION_TYPES)}"
        )
    if change_type not in CHANGE_TYPES:
        raise ValueError(
            f"Unknown change_type {change_type!r}; expected one of {', '.join(CHANGE_TYPES)}"
        )
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be a number in [0.0, 1.0], got {confidence!r}")

    active = policy if policy is not None else load_policy()
    requested = active.requested_level(action_type)
    level = requested
    gates: list[str] = []

    # G2 floor first, caps after — caps win (see the module docstring).
    if change_type in TRACKED_DECISION_CHANGE_TYPES:
        raised = _at_least(level, TRACKED_DECISION_FLOOR)
        if raised != level:
            gates.append("tracked_decision_change_type")
        level = raised

    if change_type not in AUTO_EXECUTABLE_CHANGE_TYPES:
        capped = _at_most(level, HUMAN_REVIEW_CEILING)
        if capped != level:
            gates.append("change_type_not_auto_executable")
        level = capped

    if action_type not in AUTO_EXECUTABLE_ACTION_TYPES:
        capped = _at_most(level, HUMAN_REVIEW_CEILING)
        if capped != level:
            gates.append("action_type_not_auto_executable")
        level = capped

    if confidence < MIN_AUTO_EXECUTE_CONFIDENCE:
        capped = _at_most(level, HUMAN_REVIEW_CEILING)
        if capped != level:
            gates.append("confidence_below_threshold")
        level = capped

    return {
        "level": level,
        "requested": requested,
        "gates": gates,
        "inputs": {
            "action_type": action_type,
            "change_type": change_type,
            "confidence": confidence,
        },
    }


def decide_automation(
    action_type: str,
    change_type: str,
    confidence: float,
    policy: AutomationPolicy | None = None,
) -> str:
    """Returns one of "notify_only" | "draft_then_approve" |
    "auto_execute".

    Pure function: same inputs always produce the same output. No DB, no
    LLM call. The only I/O is loading the policy YAML, which happens once
    per process and is cached (pass `policy` to skip it entirely) — given
    the same policy file, the same inputs always give the same level.

    Raises ValueError on an action_type or change_type outside the fixed
    vocabularies, or a confidence outside [0.0, 1.0]. It never falls back
    to a default for an input it does not recognize: an unknown action
    type means something upstream drifted, and quietly picking a level for
    it would hide that.

    Use explain_automation() for which gates bound the result.
    """
    return explain_automation(action_type, change_type, confidence, policy)["level"]

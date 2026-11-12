"""
LLM client: a single OpenAI-compatible chat-completions client, pointed at
whichever LLM_BASE_URL the environment names.

Two valid configurations:
  - Fully local (no cloud LLM calls, nothing leaves the machine):
    LLM_BASE_URL=http://localhost:11434/v1  (local Ollama)
  - Dev/benchmark only, current setting on this machine: a cloud/serverless
    OpenAI-compatible endpoint (e.g. LLM_BASE_URL=https://openrouter.ai/api/v1)
    used to compare the candidate models before picking one to run locally.

Structured-output analysis calls follow ComplyX's llm.py pattern (see
docs/PLAN.md section 1): forced tool-call output, temperature=0, and the
model only ever LABELS content that code has already computed — it never
reproduces or invents clause text. For classify_change() (M3) specifically,
this means diff.py's difflib delta decides WHAT changed; the model only
names the change TYPE and writes a summary, matching the guardrail "LLM
never fabricates a change: deltas are computed by code; the LLM labels
them" (docs/PLAN.md / the takeoff prompt section 7). Unlike ComplyX's
chunk-index citation trick (needed there for quote-faithfulness against
retrieved search results), there's no equivalent trick needed here: the
old/new clause text is already verbatim from Postgres by the time it
reaches the prompt, and the model's summary is meant to be a paraphrase,
not a quote.

Exercised against real models since M9 (docs/PLAN.md section 3/M9):
benchmarked across four candidate models on a hand-verified label set,
100% accuracy on the chosen model (`google/gemma-4-31b-it`). Request/
response handling is additionally covered by mocked-client unit tests
(tests/unit/test_diff.py) for cases too specific to re-run against a real
endpoint every time (malformed tool-call arguments, truncation retries).

Regulator PDFs are untrusted input (takeoff prompt section 7): `old_text`/
`new_text` below are extracted straight from a downloaded PDF, so
sanitize_untrusted() strips the cheap, obvious prompt-injection vectors
(fake chat-role prefixes, control tokens, "ignore previous instructions"
phrasing) before either reaches a prompt — found missing here during a
bulletproofing pass and fixed, moved from app/impact.py (which had its
own copy, for the *second* LLM call on already-model-summarized text) so
both of this project's LLM call sites share one definition rather than
one being protected and the other silently not. This is not a security
boundary by itself — nothing here can make an LLM safe against a
determined injection — it removes the obvious vectors; the real boundary
is architectural: forced tool-calling with a re-validated enum output,
no tools/filesystem/database access from the call itself, and a human
review gate (M5) before anything derived from it becomes an action.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from functools import lru_cache
from typing import Any

from openai import OpenAI

from . import llm_cache
from .config import settings

_INJECTION_MARKERS = re.compile(
    r"(?im)"
    r"^\s*(system|assistant|user|tool)\s*:"                       # fake chat roles
    r"|<\|[^|>]{0,40}\|>"                                          # <|im_start|>-style control tokens
    r"|\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier)\b"
    r"|\byou are now\b"
    r"|\bnew instructions?\b"
)


def sanitize_untrusted(text: str | None, *, limit: int | None = 900) -> str:
    """Collapse whitespace, neutralize prompt-ish markers, optionally
    truncate. `limit=None` means no truncation — the right choice for
    text a caller needs complete (classify_change() must see the whole
    clause to classify it correctly; the real ingested corpus has clauses
    up to ~19,600 characters, a known parsing artifact — see
    docs/PLAN.md — so even a generous fixed limit risked silently cutting
    real regulatory text off mid-classification, which would be a worse
    bug than the one this function exists to fix). Callers building a
    short LLM-facing snippet (an impact-note excerpt, a truncated summary)
    should still pass an explicit numeric limit, as app/impact.py's
    callers do."""
    if not text:
        return ""
    cleaned = _INJECTION_MARKERS.sub("[redacted]", text)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if limit is not None and len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + " [...truncated]"
    return cleaned


def strip_em_dash(text: str) -> str:
    """Deterministic backstop for the em-dash-avoidance rule in
    _CLASSIFY_SYSTEM/_IMPACT_SYSTEM: a prompt instruction is a request, not
    a guarantee, and this project's own real corpus already showed models
    don't reliably follow formatting instructions (see M9's evaluation
    notes). Applied to every LLM-generated field that reaches a user
    (summary_en/summary_ar, note_en/note_ar) so the rule holds regardless
    of what any given model actually does."""
    return text.replace(" — ", ", ").replace("—", ",")

CHANGE_TYPES = [
    "new_obligation", "tightened", "relaxed", "clarification",
    "editorial", "renumbered", "withdrawn",
]

_CLASSIFY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "classify_regulatory_change",
        "description": "Classify how a regulatory clause changed between two versions of the same regulation",
        "parameters": {
            "type": "object",
            "required": ["change_type", "confidence", "summary_en", "summary_ar"],
            "properties": {
                "change_type": {
                    "type": "string",
                    "enum": CHANGE_TYPES,
                    "description": (
                        "new_obligation: requirement has no counterpart in the old text. "
                        "tightened: requirement became stricter/more demanding. "
                        "relaxed: requirement became less strict. "
                        "clarification: wording changed but the obligation is substantively the same. "
                        "editorial: purely cosmetic (formatting, typos) — no semantic change. "
                        "renumbered: matched via similarity (not the same control ID) and substantively unchanged. "
                        "withdrawn: requirement has no counterpart in the new text. "
                        "tightened vs. clarification tie-breaker (the two most commonly confused): "
                        "does the NEW text add a requirement to DO something that the OLD text did not "
                        "require at all (a new procedural step, a new verification/assessment, a new "
                        "explicit scope this control did not previously cover) -> tightened, even if the "
                        "core subject of the control is unchanged. Does the NEW text only restate or "
                        "make more explicit something the OLD text already effectively required, with no "
                        "new action demanded of the entity -> clarification. When genuinely uncertain "
                        "between the two, prefer tightened and reflect the uncertainty in confidence "
                        "rather than defaulting to clarification — a missed tightening is a bigger "
                        "compliance risk than an over-flagged one."
                    ),
                },
                "confidence": {"type": "number", "description": "0.0-1.0"},
                "summary_en": {"type": "string", "description": "1-2 sentence plain-English summary of what changed and why it matters. Never quote clause text verbatim: paraphrase."},
                "summary_ar": {
                    "type": "string",
                    "description": (
                        "The same substance, composed independently in formal regulatory Arabic — not a "
                        "sentence-by-sentence translation of summary_en. Use the register and vocabulary "
                        "of official Saudi regulatory writing (e.g. NCA's own ECC documents): الجهة "
                        "الخاضعة for the regulated entity, الضابط for a control, المتطلب for a "
                        "requirement, الالتزام for the obligation to comply, تشديد/تخفيف for a control "
                        "tightening or relaxing. Write sentences the way a Saudi compliance officer would "
                        "phrase them natively, not English syntax carried over in Arabic words."
                    ),
                },
                "effective_date": {"type": "string", "description": "ISO 8601 date (YYYY-MM-DD), ONLY if the new text explicitly states one. Omit otherwise: never infer or guess a date."},
                "grace_days": {"type": "integer", "description": "Grace period in days, ONLY if the new text explicitly states one. Omit otherwise: never infer or guess a number."},
            },
        },
    },
}

_CLASSIFY_SYSTEM = """You are a regulatory analyst comparing two versions of the same Saudi cybersecurity control (NCA ECC).

You will be given the OLD text (or "[none: no counterpart in the old version]" if this is a new clause) and the NEW text (or "[none: no counterpart in the new version]" if withdrawn), plus how the two were matched.

Strict rules:
- Classify using ONLY the provided old/new text. Never infer requirements from outside knowledge of NCA ECC or cybersecurity practice in general.
- effective_date and grace_days: leave them out entirely unless the NEW text explicitly states one. Never estimate or guess.
- summary_en/summary_ar describe what changed and its practical effect, in your own words — never copy long verbatim spans of the source text into the summary.
- Write summary_ar as a native Arabic regulatory sentence, not a translation of summary_en: compose it independently, in the vocabulary a Saudi compliance officer actually uses (see the summary_ar field description), even though it must report the same facts as summary_en.
- Tone (both languages): factual and unhedged, like a finding, not an announcement. No hedging phrases, no exclamation marks, no "successfully"/"please" or their Arabic equivalents (بنجاح، يرجى، من فضلك).
- Never use an em dash; use a comma, colon or period instead."""


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


def probe() -> dict:
    """Best-effort connectivity + model-availability check for /health.
    Never raises: the caller always gets a status dict, reachable=False on
    any failure (unreachable server, bad key, model not pulled/available).
    No silent fallback to mock output anywhere else in the app — this probe
    result is exactly what lets main.py fail loudly instead.

    Uses a short timeout and no retries (unlike the shared client's
    defaults, which real inference calls in diff.py/impact.py want): this
    is a liveness check called on every /health hit, not a real request,
    and the OpenAI SDK's default retry-with-backoff on connection errors
    otherwise makes /health take ~14s whenever Ollama/the configured
    endpoint is down — measured, not guessed, while building M1.

    That SDK-level timeout=5.0 turned out not to be a reliable wall-clock
    cap by itself: measured directly against a slow real OpenRouter
    endpoint, single calls ranged from ~5s up to 15s+ (and /health as a
    whole, which also checks DB/Qdrant, once took 43s) — the SDK's timeout
    evidently doesn't bound every phase of a request under every failure
    mode. /health is polled by the frontend header on every page load, so
    a hang here reads as "backend unreachable" even when the backend is
    fine and only the LLM provider is slow. Wrapped in a real thread with
    a hard 5s deadline (future.result(timeout=...)) so this function
    itself can never take meaningfully longer than 5s, regardless of what
    the SDK does internally — found by timing probe() in isolation, not
    by reading the SDK's docs and assuming they held."""
    def _do_probe() -> dict:
        client = get_client().with_options(timeout=5.0, max_retries=0)
        models = [m.id for m in client.models.list().data]
        return {
            "reachable": True,
            "base_url": settings.llm_base_url,
            "configured_model": settings.llm_model,
            "model_available": settings.llm_model in models or not models,
        }

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(_do_probe).result(timeout=5.0)
    except FutureTimeoutError:
        return {
            "reachable": False,
            "base_url": settings.llm_base_url,
            "configured_model": settings.llm_model,
            "error": "TimeoutError: probe exceeded its 5s hard deadline",
        }
    except Exception as exc:
        return {
            "reachable": False,
            "base_url": settings.llm_base_url,
            "configured_model": settings.llm_model,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        # Not wait=True: on a timeout, _do_probe's thread is still running
        # the real network call underneath. We've already returned an
        # honest "not reachable within budget" to the caller; waiting here
        # would defeat the entire point of the hard deadline above.
        executor.shutdown(wait=False)


def _build_classify_messages(old_text: str, new_text: str, match_kind: str) -> list[dict]:
    old_clean = sanitize_untrusted(old_text, limit=None)
    new_clean = sanitize_untrusted(new_text, limit=None)
    old_block = old_clean if old_clean else "[none: no counterpart in the old version]"
    new_block = new_clean if new_clean else "[none: no counterpart in the new version]"
    return [
        {"role": "system", "content": _CLASSIFY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Match method: {match_kind}\n\n"
                f"OLD text:\n{old_block}\n\n"
                f"NEW text:\n{new_block}\n\n"
                "Classify this change and submit it via the classify_regulatory_change tool."
            ),
        },
    ]


_VALID_CHANGE_TYPES = set(CHANGE_TYPES)


def _classify_via_model(old_text: str, new_text: str, match_kind: str) -> dict:
    """The live model call behind classify_change(): returns the parsed
    tool-call arguments (the model's raw answer, not yet validated)."""
    for max_tokens in (4096, 8192):
        response = get_client().chat.completions.create(
            model=settings.llm_model,
            temperature=0,
            max_tokens=max_tokens,
            messages=_build_classify_messages(old_text, new_text, match_kind),
            tools=[_CLASSIFY_TOOL],
            tool_choice={"type": "function", "function": {"name": "classify_regulatory_change"}},
        )
        if response.choices[0].finish_reason != "length":
            break

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    if not tool_calls:
        raise ValueError(f"Model did not call classify_regulatory_change. finish_reason={response.choices[0].finish_reason}")

    try:
        return json.loads(tool_calls[0].function.arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned invalid JSON for classify_regulatory_change: {exc}") from exc


def classify_change(old_text: str, new_text: str, match_kind: str) -> dict:
    """Classify one aligned clause pair's delta. Raises on an unreachable
    endpoint or a malformed response — no silent fallback (docs/PLAN.md
    section 7): a failed classification must visibly fail the diff run,
    never produce a change row with fabricated/guessed content.

    Retries once at a higher token budget on truncation, same pattern as
    ComplyX's analyze_compliance(). First exercised for real during M9
    benchmarking (docs/PLAN.md): qwen3.6-27b failed 11/15 calls at the
    original max_tokens=1024 with finish_reason="length" — not a model
    quality problem, a budget problem. Its "thinking" reasoning trace
    (measured: 2053 reasoning tokens on a typical clause, via
    completion_tokens_details.reasoning_tokens) consumes the SAME
    max_tokens budget as the actual tool-call output, and 1024 was sized
    for gpt-oss-20b's near-zero reasoning overhead on this prompt. Retrying
    at 8192 resolved it in the same benchmark run (measured cost: ~$0.005/
    call at that size, not $0.05 — cheap even doubled). Every model in the
    candidate list may reason before answering; size for the neediest one,
    not the cheapest one to have tested first."""
    # Demo-mode only (see llm_cache.py): an identical earlier prompt is
    # answered from the local table with the model's real earlier output.
    # Off unless the demo runner or prepare activates it, so this is a no-op
    # for the CLI and the tests.
    cache_key = llm_cache.make_key(
        "classify", settings.llm_model, _build_classify_messages(old_text, new_text, match_kind), _CLASSIFY_TOOL
    )
    data = llm_cache.lookup("classify", cache_key)
    from_cache = data is not None
    if data is None:
        data = _classify_via_model(old_text, new_text, match_kind)

    change_type = data.get("change_type")
    if change_type not in _VALID_CHANGE_TYPES:
        raise ValueError(f"Model returned an invalid change_type: {change_type!r}")

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        raise ValueError(f"Model returned an invalid confidence: {confidence!r}")

    if not from_cache:
        llm_cache.store("classify", cache_key, settings.llm_model, data)  # only after validation passed

    return {
        "change_type": change_type,
        "confidence": float(confidence),
        "summary_en": strip_em_dash(str(data.get("summary_en", ""))),
        "summary_ar": strip_em_dash(str(data.get("summary_ar", ""))),
        "effective_date": data.get("effective_date") or None,
        "grace_days": data.get("grace_days") if isinstance(data.get("grace_days"), int) else None,
    }

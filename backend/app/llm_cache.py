"""
Persistent LLM result cache (demo mode only).

Why this exists: a cold end-to-end run of the pipeline makes roughly 250
sequential LLM calls (about 208 classifications plus one impact note per
impacted node) at around 3 seconds each, which is about 15 minutes. That
is fine for a batch job and unusable for a live demo that has to be reset
and replayed. This cache stores the model's REAL output for a call keyed by
everything that determines the output (model name, the complete message
list, the tool schema, temperature 0), so an identical prompt replayed
later is answered from the local table instead of the network.

What it is not: it never invents, edits or interpolates a result. A hit
returns exactly the tool-call arguments a real model call produced earlier
for a byte-identical prompt. The demo pipeline reports how many answers
were hits (see app/demo/tracker.py), so nothing is presented as a live model
answer when it was not.

Two switches, both required:
  1. `settings.demo_mode` (env DEMO_MODE, default true in dev).
  2. An explicit process-wide activation, `with llm_cache.activated():`,
     taken by the demo runner and by `python -m app.demo.prepare`.
Everything else, in particular the unit tests and the plain CLI
(`python -m app.diff`, `python -m app.agent.graph`), never touches this
table, so behaviour outside the demo is exactly what it was before.

The cached value is the parsed tool-call arguments (the model's raw
answer), NOT the validated result. Validation (enum checks, range checks,
em dash stripping) runs on every call, hit or miss, so a change to those
rules applies to cached answers too. An entry is only stored after its
answer passed validation, so a malformed model response is never cached.

A cache failure (table missing because the migration has not been applied,
database briefly unreachable) degrades to a normal live model call and logs
a warning once. It never turns into a wrong answer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .config import settings
from .db.base import Base
from .db.session import get_engine

log = logging.getLogger(__name__)

#: Bump when the way keys are derived changes, so old entries are simply not found.
KEY_VERSION = 1


class LlmCache(Base):
    """One cached model answer. `key` is the SHA-256 of the request."""

    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # "classify" | "impact"
    model: Mapped[str] = mapped_column(String)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    hit_count: Mapped[int] = mapped_column(default=0)


# ── Activation ────────────────────────────────────────────────────────────

_state_lock = threading.Lock()
_active_depth = 0


@contextmanager
def activated():
    """Turn the cache on for this process while the block runs. Re-entrant
    and safe across threads (a counter, not a flag)."""
    global _active_depth
    with _state_lock:
        _active_depth += 1
    try:
        yield
    finally:
        with _state_lock:
            _active_depth -= 1


def is_active() -> bool:
    return bool(settings.demo_mode) and _active_depth > 0


# ── Counters (per process, read by the demo progress tracker) ─────────────

_stats: dict[str, dict[str, int]] = {}


def _bump(kind: str, field: str) -> None:
    with _state_lock:
        bucket = _stats.setdefault(kind, {"calls": 0, "cache_hits": 0})
        bucket[field] += 1


def stats_snapshot() -> dict[str, dict[str, int]]:
    """{kind: {"calls": n, "cache_hits": h}}. `calls` counts every lookup,
    whether or not the cache was active, so `calls - cache_hits` is the
    number of answers the model produced live."""
    with _state_lock:
        return {kind: dict(bucket) for kind, bucket in _stats.items()}


def stats_delta(before: dict[str, dict[str, int]], after: dict[str, dict[str, int]], kind: str) -> tuple[int, int]:
    """(calls, cache_hits) for `kind` between two snapshots."""
    b = before.get(kind, {"calls": 0, "cache_hits": 0})
    a = after.get(kind, {"calls": 0, "cache_hits": 0})
    return a["calls"] - b["calls"], a["cache_hits"] - b["cache_hits"]


def reset_stats() -> None:
    with _state_lock:
        _stats.clear()


# ── Keys ──────────────────────────────────────────────────────────────────

def tools_hash(tools: Any) -> str:
    return hashlib.sha256(json.dumps(tools, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def make_key(kind: str, model: str, messages: list[dict[str, Any]], tools: Any) -> str:
    """SHA-256 over the model name, the full message list, the tool schema
    hash and the fixed temperature. Any change to the prompt text, the
    system prompt, the node attributes or the schema yields a new key."""
    payload = json.dumps(
        {
            "v": KEY_VERSION,
            "kind": kind,
            "model": model,
            "temperature": 0,
            "messages": messages,
            "tools_sha256": tools_hash(tools),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Lookup and store ──────────────────────────────────────────────────────

_warned = False


def _warn_once(exc: Exception) -> None:
    global _warned
    if not _warned:
        _warned = True
        log.warning(
            "llm_cache unavailable (%s: %s); falling back to live model calls. "
            "Run `alembic upgrade head` if the llm_cache table is missing.",
            type(exc).__name__, exc,
        )


def lookup(kind: str, key: str) -> dict[str, Any] | None:
    """The cached model answer for `key`, or None. Always counts the call
    (see stats_snapshot); only touches the database when active."""
    _bump(kind, "calls")
    if not is_active():
        return None
    try:
        with Session(get_engine()) as db:
            row = db.get(LlmCache, key)
            if row is None:
                return None
            response = json.loads(json.dumps(row.response_json))  # detach a plain copy
            db.execute(update(LlmCache).where(LlmCache.key == key).values(hit_count=LlmCache.hit_count + 1))
            db.commit()
    except Exception as exc:  # cache trouble is a miss, not a failure
        _warn_once(exc)
        return None
    _bump(kind, "cache_hits")
    return response


def store(kind: str, key: str, model: str, response: dict[str, Any]) -> bool:
    """Persist a validated model answer. Returns True when a row was
    written. A concurrent identical insert is not an error."""
    if not is_active():
        return False
    try:
        with Session(get_engine()) as db:
            db.add(LlmCache(key=key, kind=kind, model=model, response_json=response, hit_count=0))
            db.commit()
        return True
    except IntegrityError:
        return False
    except Exception as exc:
        _warn_once(exc)
        return False


def count_entries() -> dict[str, int]:
    """{"total": n, "classify": a, "impact": b} for the status endpoint.
    Zeros when the table does not exist yet."""
    try:
        with Session(get_engine()) as db:
            rows = db.execute(select(LlmCache.kind, func.count()).group_by(LlmCache.kind)).all()
    except Exception:
        return {"total": 0}
    out = {kind: n for kind, n in rows}
    out["total"] = sum(out.values())
    return out

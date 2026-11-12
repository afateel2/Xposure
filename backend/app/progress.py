"""
In-process progress hooks for long pipeline steps.

diff.py and the agent graph call `emit()` at natural checkpoints (clause
alignment finished, one change classified, one change's impact traced).
With no listener installed, `emit()` returns immediately and nothing
changes, so the CLI and the tests behave exactly as before. The demo runner
(app/demo/runner.py) installs a listener for the duration of a run and turns
these events into the live stage progress served by GET /demo/run.

A listener that raises must never break the pipeline, so exceptions are
logged and swallowed here. The events carry facts the pipeline already
computed; nothing in this module decides anything.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Listener = Callable[[str, dict[str, Any]], None]

_lock = threading.Lock()
_listener: Listener | None = None


def set_listener(listener: Listener | None) -> None:
    global _listener
    with _lock:
        _listener = listener


def emit(event: str, **data: Any) -> None:
    listener = _listener
    if listener is None:
        return
    try:
        listener(event, data)
    except Exception:  # never let a display concern break the pipeline
        log.exception("progress listener failed on %s", event)

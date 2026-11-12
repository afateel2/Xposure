"""
Outbound webhook integration (M8, takeoff prompt section 8): signed HTTP
POST notifications for change.detected / impact.computed / action.approved,
to a configurable URL, with HMAC-SHA256 signing so a receiver can verify a
payload actually came from this Xposure instance and was not tampered with
in transit — the same "verify, don't trust" instinct as `llm.py`'s
re-validated `change_type` or `impact.py`'s re-validated action vocabulary,
applied to an outbound HTTP boundary instead of a model response.

Deliberately best-effort, never blocking: `WEBHOOK_URL` defaults to empty
(disabled), and any send failure (unreachable URL, timeout, non-2xx) is
caught and returned as a result dict for the caller to audit-log, never
raised. A compliance pipeline must not fail because a demo webhook
receiver happens to be down — this mirrors `agent/graph.py`'s
auto_execute_node, which records "no external system" honestly rather
than pretending an unreachable integration succeeded.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import settings

WEBHOOK_EVENTS: tuple[str, ...] = (
    "change.detected", "impact.computed", "action.approved", "action.delegated", "action.confirmed", "digest.sent",
)
_TIMEOUT_SECONDS = 5.0
_SIGNATURE_PREFIX = "sha256="


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def send_webhook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Best-effort signed POST of one event envelope. Always returns a
    result dict describing what happened (never raises) so callers can
    audit-log the outcome unconditionally:
      - {"sent": False, "reason": "no WEBHOOK_URL configured"} — the
        normal, expected result when the integration is not opted into.
      - {"sent": True, "status_code": ...} — delivered (a non-2xx status
        is still "sent": the request reached the receiver; the receiver's
        own response is the caller's business, not ours to retry here).
      - {"sent": False, "reason": "<exception>"} — network/timeout
        failure.

    Raises ValueError only for a programming error (an event name outside
    WEBHOOK_EVENTS) — that is a bug in the caller, not a delivery failure,
    and should not be swallowed the way a real delivery failure is.
    """
    if event not in WEBHOOK_EVENTS:
        raise ValueError(f"Unknown webhook event {event!r}; expected one of {WEBHOOK_EVENTS}")
    if not settings.webhook_url:
        return {"sent": False, "event": event, "reason": "no WEBHOOK_URL configured"}

    envelope = {
        "event": event,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }
    body = json.dumps(envelope, sort_keys=True, default=str).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.webhook_secret:
        headers["X-Xposure-Signature"] = _SIGNATURE_PREFIX + _sign(settings.webhook_secret, body)

    try:
        response = httpx.post(settings.webhook_url, content=body, headers=headers, timeout=_TIMEOUT_SECONDS)
        return {"sent": True, "event": event, "url": settings.webhook_url, "status_code": response.status_code}
    except Exception as exc:
        return {"sent": False, "event": event, "url": settings.webhook_url, "reason": f"{type(exc).__name__}: {exc}"}


def verify_signature(secret: str, body: bytes, header_value: str | None) -> bool:
    """Constant-time signature check for the receiver side
    (routes/webhooks.py's demo endpoint). Returns False (never raises) on
    a missing/malformed header — an absent signature is a verification
    failure, not an error."""
    if not header_value or not header_value.startswith(_SIGNATURE_PREFIX):
        return False
    expected = _sign(secret, body)
    return hmac.compare_digest(header_value[len(_SIGNATURE_PREFIX):], expected)

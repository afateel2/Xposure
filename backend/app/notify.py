"""
Outbound notification integration: tell a delegated action's assignee
what's expected of them. Same "opt-in, never a hard dependency, never
raises on a delivery failure" shape as app/webhooks.py's send_webhook() —
deliberately, so a delegation never fails because a mail server happens to
be unreachable, the same way approving an action never fails because a
webhook receiver is down.

Channel-agnostic by design: this is a generic "notify a person" capability
(currently just SMTP email), not an ERP-specific one. A real Odoo
write-back (posting to a record's chatter) is a different, later
capability — this module's contract (send_notification's signature and
result shape) is what that future implementation would satisfy too,
without any caller-side change.
"""

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from .config import settings

NOTIFICATION_CHANNELS: tuple[str, ...] = ("email",)
_TIMEOUT_SECONDS = 5.0


def send_notification(
    channel: str | None,
    target: str | None,
    subject: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Best-effort delivery of one notification. Always returns a result
    dict describing what happened (never raises on a delivery failure) so
    callers can audit-log the outcome unconditionally:
      - {"sent": False, "reason": "no notification channel configured"} —
        settings.notification_channel is unset, or no `channel` was given.
      - {"sent": False, "reason": "no recipient contact given"} — `target`
        is empty (e.g. the delegator typed a name only, no email).
      - {"sent": True, "channel": ..., "target": ...} — handed off to the
        transport successfully.
      - {"sent": False, "reason": "<exception>"} — transport failure
        (unreachable SMTP host, auth failure, timeout).

    Raises ValueError only for a programming error (a `channel` outside
    NOTIFICATION_CHANNELS) — a bug in the caller, not a delivery failure.
    """
    if channel is not None and channel not in NOTIFICATION_CHANNELS:
        raise ValueError(f"Unknown notification channel {channel!r}; expected one of {NOTIFICATION_CHANNELS}")

    effective_channel = channel or settings.notification_channel
    if not effective_channel:
        return {"sent": False, "reason": "no notification channel configured"}
    if not target:
        return {"sent": False, "channel": effective_channel, "reason": "no recipient contact given"}
    if not settings.smtp_host:
        return {"sent": False, "channel": effective_channel, "target": target, "reason": "no SMTP host configured"}

    try:
        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = settings.notification_from or "xposure@localhost"
        email["To"] = target
        email["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        email.set_content(message)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_TIMEOUT_SECONDS) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(email)
        return {"sent": True, "channel": effective_channel, "target": target}
    except Exception as exc:
        return {
            "sent": False,
            "channel": effective_channel,
            "target": target,
            "reason": f"{type(exc).__name__}: {exc}",
        }

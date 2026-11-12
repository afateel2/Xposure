"""
POST /webhooks/receiver — a local receiver standing in for a real
downstream GRC system, per the takeoff prompt's "a signed outbound webhook
... with a local receiver for demo" (section 3/M8). Verifies the HMAC
signature app/webhooks.py attaches (when WEBHOOK_SECRET is configured) and
records the event via the audit log rather than a dedicated table:
"an external event was received" is exactly what audit_log already models
(actor, event, payload), and a demo receiver does not need its own schema.

GET /webhooks/received lets the demo show what actually arrived, without
needing a second terminal watching a log file.

Security note, found during a bulletproofing pass rather than designed in
up front: when WEBHOOK_SECRET is unset (the shipped default — see
.env.example), signature verification is skipped entirely, by design, so
the demo works with zero configuration. That also means anyone who can
reach this endpoint can write arbitrary, attacker-chosen events into the
audit log, indistinguishable at a glance from genuine ones — a real gap
given this app has no auth anywhere yet (see docs/DESIGN.md's Risks).
Not fixed by requiring a secret (that would break the zero-config demo
path the feature exists for); fixed by making the trust level of every
recorded event honest rather than implicit: every payload this endpoint
writes now carries `_verified` (True only when a real signature was
checked and matched), so nothing reading the audit log later — a human,
the Settings screen's webhook-activity table — has to guess whether a
given row was authenticated or just accepted on faith.
"""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db.models import AuditLog
from ..db.session import get_db
from ..webhooks import verify_signature

router = APIRouter(tags=["webhooks"])

_RECEIVER_ACTOR = "webhook:receiver"


@router.post("/webhooks/receiver")
async def receive_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_xposure_signature: str | None = Header(default=None),
):
    body = await request.body()
    verified = False
    if settings.webhook_secret:
        if not verify_signature(settings.webhook_secret, body, x_xposure_signature):
            raise HTTPException(status_code=401, detail="Invalid or missing X-Xposure-Signature.")
        verified = True

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    entry = audit.record(
        db,
        actor=_RECEIVER_ACTOR,
        event=f"webhook_received:{payload.get('event', 'unknown')}",
        # _verified distinguishes a signature-checked delivery from one
        # accepted on faith (no WEBHOOK_SECRET configured) — see this
        # module's docstring. Prefixed with an underscore so it reads as
        # metadata about the record, not part of the delivered payload
        # itself, if this dict is ever compared against what was sent.
        payload={**payload, "_verified": verified},
    )
    return {"received": True, "verified": verified, "audit_log_id": entry.id}


@router.get("/webhooks/received")
def list_received_webhooks(db: Session = Depends(get_db), limit: int = 50):
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.actor == _RECEIVER_ACTOR)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    return [{"id": r.id, "ts": r.ts, "event": r.event, "payload": r.payload_json} for r in rows]

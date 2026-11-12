"""
Real reviewer identity. Before it existed, every approval was attributed
to one fixed actor string, which made the audit trail far weaker than it
should be. This module is deliberately small
and dependency-free (stdlib `hashlib`/`secrets` only, no new package):
password hashing, opaque session tokens, and the two FastAPI dependencies
every mutating route now takes, `require_user` and `require_admin`.

Design choices, stated rather than left implicit:
  - Passwords: PBKDF2-HMAC-SHA256, 200,000 iterations, a random 16-byte
    salt per user, stored as `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`.
    Not bcrypt/argon2 (no new dependency) but a real, salted, slow KDF,
    not a bare hash.
  - Sessions: a random 32-byte URL-safe token is the cookie value; only
    its SHA-256 digest is stored server-side (db/models.py's UserSession
    docstring). 14-day fixed expiry, refreshed on login. Logout deletes
    the row, not just the cookie, so a stolen cookie after logout is
    worthless.
  - Reads stay open (this is a single-organization internal tool and the
    whole visibility feature set is meant to be glanceable); every
    state-changing endpoint requires `require_user`. `require_admin`
    additionally requires role == "admin" and is used only for the
    automation-policy editor.
  - No multi-tenant scoping (docs/DESIGN.md Roadmap: still out of scope).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import AppUser, UserSession
from .db.session import get_db

SESSION_COOKIE = "xposure_session"
SESSION_TTL_DAYS = 14
_PBKDF2_ITERATIONS = 200_000
_PBKDF2_ALGO = "pbkdf2_sha256"


# ── Passwords ────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations_s, salt_hex, hash_hex = stored.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(computed, expected)


# ── Sessions ─────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: AppUser) -> str:
    """Create a session row and return the raw token (only ever returned
    here, never stored or logged in plain form again)."""
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=SESSION_TTL_DAYS),
            last_seen_at=now,
        )
    )
    db.commit()
    return token


def destroy_session(db: Session, token: str) -> None:
    row = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    if row is not None:
        db.delete(row)
        db.commit()


def resolve_session(db: Session, token: str | None) -> AppUser | None:
    """Return the live user for a session cookie, or None (expired,
    unknown, logged out, no cookie, or the account was deactivated) —
    every caller treats None as "not signed in," never as an error."""
    if not token:
        return None
    row = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    if row is None:
        return None
    if row.expires_at < datetime.utcnow():
        db.delete(row)
        db.commit()
        return None
    user = db.get(AppUser, row.user_id)
    if user is None or not user.is_active:
        return None
    row.last_seen_at = datetime.utcnow()
    db.commit()
    return user


# ── FastAPI dependencies ───────────────────────────────────────────────────

def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser | None:
    """Optional identity: None when signed out. Used by GET /auth/me and
    anywhere a route wants to personalize a read without requiring login."""
    return resolve_session(db, request.cookies.get(SESSION_COOKIE))


def require_user(user: AppUser | None = Depends(get_current_user)) -> AppUser:
    """Every state-changing endpoint depends on this. A bilingual 401
    (this app's honesty convention — see app/erp/client.py's ErpError for
    the same "English | Arabic" detail-string pattern) rather than a bare
    FastAPI default, so the frontend can show the right-language message
    without a lookup table."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to do this. | سجل الدخول لتنفيذ هذا الإجراء.",
        )
    return user


def require_admin(user: AppUser = Depends(require_user)) -> AppUser:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator can do this. | هذا الإجراء متاح للمسؤول فقط.",
        )
    return user


@dataclass(frozen=True)
class PublicUser:
    """What GET /auth/me and ActionOut-adjacent responses expose — never
    the password hash, never the session token."""

    id: int
    email: str
    name_en: str
    name_ar: str
    role: str
    job_title_en: str | None
    job_title_ar: str | None

    @classmethod
    def from_model(cls, user: AppUser) -> "PublicUser":
        return cls(
            id=user.id,
            email=user.email,
            name_en=user.name_en,
            name_ar=user.name_ar,
            role=user.role,
            job_title_en=user.job_title_en,
            job_title_ar=user.job_title_ar,
        )

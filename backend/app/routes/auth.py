"""
POST /auth/login, POST /auth/logout, GET /auth/me. See app/auth.py's
module docstring for the session/password design. Login rate limiting is
intentionally not built yet (no attacker surface worth it in a
single-organization demo deployment, and adding it half-heartedly would
be worse than the honest absence); noted here rather than left silent.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..auth import (
    SESSION_COOKIE,
    SESSION_TTL_DAYS,
    PublicUser,
    create_session,
    destroy_session,
    get_current_user,
    verify_password,
)
from ..db.models import AppUser
from ..db.session import get_db

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class MeOut(BaseModel):
    authenticated: bool
    user: PublicUser | None = None


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.scalar(select(AppUser).where(AppUser.email == email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. | البريد الإلكتروني أو كلمة المرور غير صحيحة.",
        )
    token = create_session(db, user)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )
    audit.record(db, actor=user.actor(), event="user_logged_in", ref_type="user", ref_id=user.id, payload={})
    return MeOut(authenticated=True, user=PublicUser.from_model(user))


@router.post("/auth/logout", response_model=MeOut)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        destroy_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MeOut(authenticated=False, user=None)


@router.get("/auth/me", response_model=MeOut)
def me(user: AppUser | None = Depends(get_current_user)):
    if user is None:
        return MeOut(authenticated=False, user=None)
    return MeOut(authenticated=True, user=PublicUser.from_model(user))

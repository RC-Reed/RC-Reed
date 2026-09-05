from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import audit, get_current_user
from app.config import settings
from app.db import get_db
from app.models.user import User
from app.schemas.core import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status(db: Session = Depends(get_db)) -> dict:
    """Lets the UI show 'create your account' before the first user exists."""
    count = db.scalar(select(func.count(User.id))) or 0
    return {"registered": count > 0, "user_count": int(count)}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """Open only until the first account exists.

    This is a personal system, so bootstrapping is self-service — but leaving
    registration open on something holding your finances would be careless.
    Additional users are created deliberately with `python -m app.seed`.
    """
    if (db.scalar(select(func.count(User.id))) or 0) > 0:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Registration is closed. This instance already has an account.",
        )

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name or payload.email.split("@")[0],
    )
    db.add(user)
    db.flush()
    audit(db, request, user.id, "user.register", entity="user", entity_id=user.id)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in_minutes=settings.access_token_ttl_minutes,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalars(select(User).where(User.email == payload.email.lower())).first()
    # Verify against a dummy hash when the user is missing so a bad email and a
    # bad password take the same time to answer.
    hashed = user.hashed_password if user else hash_password("not-a-real-password")
    if not verify_password(payload.password, hashed) or user is None or not user.is_active:
        audit(db, request, None, "user.login_failed", detail={"email": payload.email})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    audit(db, request, user.id, "user.login", entity="user", entity_id=user.id)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in_minutes=settings.access_token_ttl_minutes,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user

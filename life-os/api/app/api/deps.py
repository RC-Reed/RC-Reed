"""Shared FastAPI dependencies."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.connections import AuditEvent
from app.models.user import User
from app.security import constant_time_equals, decode_access_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is not active")
    return user


def require_ingest_token(x_ingest_token: str | None = Header(default=None), token: str | None = None) -> None:
    """Auth for push endpoints, which come from devices that can't hold a JWT.

    Accepts the token in a header or a query string, because iOS Shortcuts and
    similar automations vary in what they can send.
    """
    supplied = x_ingest_token or token or ""
    if not supplied or not constant_time_equals(supplied, settings.ingest_token or ""):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid ingest token")


def audit(
    db: Session,
    request: Request | None,
    user_id: str | None,
    action: str,
    *,
    entity: str = "",
    entity_id: str | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            user_id=user_id,
            at=datetime.now(timezone.utc),
            action=action,
            entity=entity,
            entity_id=entity_id,
            detail=detail or {},
            source_ip=(request.client.host if request and request.client else ""),
        )
    )


def first_user(db: Session) -> User | None:
    return db.scalars(select(User).limit(1)).first()

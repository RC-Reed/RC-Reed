"""Token-authenticated push endpoints.

Your phone can't hold a rotating JWT, so device pushes authenticate with a
long random ingest token instead. Find yours at GET /api/v1/system/ingest-info
(authenticated) or in api/data/ingest.token.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import first_user, require_ingest_token
from app.connectors.base import IngestPayload
from app.db import get_db
from app.models.connections import Connection
from app.schemas.core import SyncRunOut
from app.services import insights as insights_service
from app.services.sync import run_ingest

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_BODY_BYTES = 64 * 1024 * 1024


def _resolve_connection(db: Session, slug: str, connection_id: str | None) -> Connection:
    if connection_id:
        connection = db.get(Connection, connection_id)
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
        return connection

    user = first_user(db)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No account exists yet")

    connection = db.scalars(
        select(Connection).where(
            Connection.user_id == user.id, Connection.connector_slug == slug
        )
    ).first()
    if connection is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No '{slug}' connection configured. Add one in the Connections page first.",
        )
    return connection


@router.post("/health", response_model=SyncRunOut, dependencies=[Depends(require_ingest_token)])
async def ingest_health(
    request: Request, connection_id: str | None = None, db: Session = Depends(get_db)
) -> SyncRunOut:
    """Receives Health Auto Export (or Shortcuts) payloads from your iPhone."""
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")

    text = raw.decode("utf-8", errors="replace")
    parsed = None
    if text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid JSON: {exc}") from exc

    connection = _resolve_connection(db, "apple_health", connection_id)
    run = run_ingest(db, connection, IngestPayload(text=text, json=parsed))
    insights_service.refresh_insights(db, connection.user_id)
    return run

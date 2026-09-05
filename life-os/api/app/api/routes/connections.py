"""Connector catalogue, connection management, sync and ingest."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import audit, get_current_user
from app.connectors.base import ConnectorMode, IngestPayload
from app.connectors.registry import all_connectors, get_connector
from app.db import get_db
from app.models.connections import Connection, ConnectionStatus, SyncRun
from app.models.user import User
from app.schemas.core import ConnectionIn, ConnectionOut, ConnectionUpdate, SyncRunOut
from app.security import decrypt_secrets, encrypt_secrets
from app.services import insights as insights_service
from app.services.sync import run_ingest, run_sync

router = APIRouter(tags=["connections"])

MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # Apple Health exports get large.


def _serialize(connection: Connection) -> ConnectionOut:
    connector = get_connector(connection.connector_slug)
    out = ConnectionOut.model_validate(connection)
    out.has_secrets = bool(connection.secrets_encrypted)
    out.connector = connector.describe() if connector else None
    # Connector scratch state is an implementation detail, not user config.
    out.config = {k: v for k, v in (connection.config or {}).items() if not k.startswith("_")}
    return out


def _owned(db: Session, user: User, connection_id: str) -> Connection:
    connection = db.get(Connection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return connection


@router.get("/connectors")
def catalogue():
    """Everything installable. The UI builds setup forms from this."""
    return [connector.describe() for connector in all_connectors()]


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    connections = db.scalars(
        select(Connection).where(Connection.user_id == user.id).order_by(Connection.created_at)
    ).all()
    return [_serialize(c) for c in connections]


@router.post("/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
def create_connection(
    payload: ConnectionIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connector = get_connector(payload.connector_slug)
    if connector is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown connector '{payload.connector_slug}'")

    problems = connector.validate(payload.config, payload.secrets)
    connection = Connection(
        user_id=user.id,
        connector_slug=payload.connector_slug,
        display_name=payload.display_name or connector.name,
        config=payload.config,
        secrets_encrypted=encrypt_secrets(payload.secrets) if payload.secrets else None,
        sync_interval_minutes=payload.sync_interval_minutes,
        status=ConnectionStatus.needs_setup if problems else ConnectionStatus.active,
        last_error="; ".join(problems) if problems else None,
    )
    db.add(connection)
    db.flush()
    audit(
        db, request, user.id, "connection.create",
        entity="connection", entity_id=connection.id,
        detail={"connector": payload.connector_slug},
    )
    db.commit()
    return _serialize(connection)


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connection = _owned(db, user, connection_id)
    values = payload.model_dump(exclude_unset=True)

    if "secrets" in values and values["secrets"] is not None:
        # Merge so a form that only re-sends changed fields doesn't wipe the rest.
        merged = {**decrypt_secrets(connection.secrets_encrypted), **values.pop("secrets")}
        merged = {k: v for k, v in merged.items() if v not in ("", None)}
        connection.secrets_encrypted = encrypt_secrets(merged) if merged else None
    if "config" in values and values["config"] is not None:
        preserved = {k: v for k, v in (connection.config or {}).items() if k.startswith("_")}
        connection.config = {**values.pop("config"), **preserved}

    for key, value in values.items():
        setattr(connection, key, value)

    connector = get_connector(connection.connector_slug)
    if connector:
        problems = connector.validate(
            connection.config or {}, decrypt_secrets(connection.secrets_encrypted)
        )
        connection.status = ConnectionStatus.needs_setup if problems else ConnectionStatus.active
        connection.last_error = "; ".join(problems) if problems else None

    audit(db, request, user.id, "connection.update", entity="connection", entity_id=connection.id)
    db.commit()
    return _serialize(connection)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connection = _owned(db, user, connection_id)
    audit(db, request, user.id, "connection.delete", entity="connection", entity_id=connection.id)
    db.delete(connection)
    db.commit()


@router.post("/connections/{connection_id}/sync", response_model=SyncRunOut)
def sync_now(
    connection_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    connection = _owned(db, user, connection_id)
    connector = get_connector(connection.connector_slug)
    if connector and connector.mode == ConnectorMode.push:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{connector.name} receives pushed data — upload a file or point your device at "
            "the ingest endpoint instead of syncing.",
        )
    run = run_sync(db, connection, trigger="manual")
    insights_service.refresh_insights(db, user.id)
    return run


@router.post("/connections/{connection_id}/ingest", response_model=SyncRunOut)
async def ingest_file(
    connection_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload a CSV or XML export into a push connector."""
    connection = _owned(db, user, connection_id)
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")

    payload = IngestPayload(
        content_type=file.content_type or "text/plain",
        filename=file.filename or "",
        text=raw.decode("utf-8", errors="replace"),
    )
    run = run_ingest(db, connection, payload)
    insights_service.refresh_insights(db, user.id)
    return run


@router.get("/connections/{connection_id}/runs", response_model=list[SyncRunOut])
def sync_history(
    connection_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _owned(db, user, connection_id)
    return db.scalars(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    ).all()


@router.post("/connections/sync-all")
def sync_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Kick every schedulable connection at once."""
    connections = db.scalars(
        select(Connection).where(Connection.user_id == user.id, Connection.is_enabled.is_(True))
    ).all()

    results = []
    for connection in connections:
        connector = get_connector(connection.connector_slug)
        if connector is None or not connector.schedulable:
            continue
        run = run_sync(db, connection, trigger="manual-all")
        results.append(
            {
                "connection": connection.display_name,
                "status": str(run.status),
                "created": run.created_count,
                "updated": run.updated_count,
                "message": run.message,
            }
        )
    insights_service.refresh_insights(db, user.id)
    return {"ran": len(results), "results": results}

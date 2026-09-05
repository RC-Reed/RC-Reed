"""Runs connectors and records what happened.

One place owns the lifecycle — open a SyncRun, resolve credentials, call the
connector, persist its state, close the run — so connectors stay small and
the audit trail is never optional.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError, IngestPayload, SyncContext, SyncResult
from app.connectors.registry import get_connector
from app.models.connections import Connection, ConnectionStatus, SyncRun, SyncStatus
from app.security import decrypt_secrets

log = logging.getLogger("lifeos.sync")

STATE_KEY = "_state"


def _begin(db: Session, connection: Connection, trigger: str) -> SyncRun:
    run = SyncRun(
        connection_id=connection.id,
        started_at=datetime.now(timezone.utc),
        status=SyncStatus.running,
        trigger=trigger,
    )
    db.add(run)
    db.flush()
    return run


def _finish(
    db: Session,
    run: SyncRun,
    connection: Connection,
    *,
    status: SyncStatus,
    result: SyncResult | None = None,
    error: str = "",
) -> SyncRun:
    run.finished_at = datetime.now(timezone.utc)
    run.status = status
    if result:
        run.created_count = result.created
        run.updated_count = result.updated
        run.message = "; ".join(filter(None, [result.message, *result.warnings]))[:2000]
    else:
        run.message = error[:2000]

    connection.last_sync_at = run.finished_at
    if status == SyncStatus.failed:
        connection.last_error = error[:2000]
        connection.status = ConnectionStatus.error
    else:
        connection.last_error = None
        connection.status = ConnectionStatus.active
    db.commit()
    return run


def _context(db: Session, connection: Connection) -> SyncContext:
    config = dict(connection.config or {})
    return SyncContext(
        db=db,
        user_id=connection.user_id,
        connection_id=connection.id,
        config=config,
        secrets=decrypt_secrets(connection.secrets_encrypted),
        state=dict(config.get(STATE_KEY) or {}),
    )


def _persist_state(connection: Connection, ctx: SyncContext) -> None:
    """Write connector scratch state back onto the connection row."""
    if not ctx.state:
        return
    config = dict(connection.config or {})
    config[STATE_KEY] = ctx.state
    connection.config = config


def run_sync(db: Session, connection: Connection, *, trigger: str = "manual") -> SyncRun:
    connector = get_connector(connection.connector_slug)
    run = _begin(db, connection, trigger)

    if connector is None:
        return _finish(
            db, run, connection,
            status=SyncStatus.failed,
            error=f"Unknown connector '{connection.connector_slug}'",
        )
    if not connection.is_enabled:
        return _finish(db, run, connection, status=SyncStatus.failed, error="Connection is disabled")

    ctx = _context(db, connection)
    try:
        result = connector.sync(ctx)
        _persist_state(connection, ctx)
        db.flush()
    except ConnectorError as exc:
        db.rollback()
        db.add(run)
        log.warning("sync failed for %s: %s", connection.display_name, exc)
        return _finish(db, run, connection, status=SyncStatus.failed, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - a bad connector must not kill the scheduler
        db.rollback()
        db.add(run)
        log.exception("unexpected sync error for %s", connection.display_name)
        return _finish(
            db, run, connection, status=SyncStatus.failed, error=f"Unexpected error: {exc}"
        )

    status = SyncStatus.partial if result.warnings else SyncStatus.success
    return _finish(db, run, connection, status=status, result=result)


def run_ingest(db: Session, connection: Connection, payload: IngestPayload) -> SyncRun:
    connector = get_connector(connection.connector_slug)
    run = _begin(db, connection, "ingest")

    if connector is None:
        return _finish(
            db, run, connection,
            status=SyncStatus.failed,
            error=f"Unknown connector '{connection.connector_slug}'",
        )

    ctx = _context(db, connection)
    try:
        result = connector.ingest(ctx, payload)
        _persist_state(connection, ctx)
        db.flush()
    except ConnectorError as exc:
        db.rollback()
        db.add(run)
        return _finish(db, run, connection, status=SyncStatus.failed, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        db.add(run)
        log.exception("unexpected ingest error for %s", connection.display_name)
        return _finish(
            db, run, connection, status=SyncStatus.failed, error=f"Unexpected error: {exc}"
        )

    status = SyncStatus.partial if result.warnings else SyncStatus.success
    return _finish(db, run, connection, status=status, result=result)


def due_connections(db: Session) -> list[Connection]:
    """Connections whose schedule says it is time, for the background worker."""
    now = datetime.now(timezone.utc)
    candidates = db.scalars(
        select(Connection).where(
            Connection.is_enabled.is_(True),
            Connection.status.in_([ConnectionStatus.active, ConnectionStatus.needs_setup]),
        )
    ).all()

    due: list[Connection] = []
    for connection in candidates:
        connector = get_connector(connection.connector_slug)
        if connector is None or not connector.schedulable:
            continue
        if connection.last_sync_at is None:
            due.append(connection)
            continue
        last = connection.last_sync_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() >= connection.sync_interval_minutes * 60:
            due.append(connection)
    return due

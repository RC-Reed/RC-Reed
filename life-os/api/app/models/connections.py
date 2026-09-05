"""Connector instances, their sync history, and derived insights."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONField, TimestampMixin, UUIDMixin


class ConnectionStatus(str, enum.Enum):
    active = "active"
    needs_setup = "needs_setup"
    needs_auth = "needs_auth"
    error = "error"
    disabled = "disabled"


class Connection(UUIDMixin, TimestampMixin, Base):
    """One configured instance of a connector (e.g. "Fidelity CSV", "Chase")."""

    __tablename__ = "connections"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connector_slug: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(160))

    status: Mapped[ConnectionStatus] = mapped_column(String(24), default=ConnectionStatus.needs_setup)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Non-sensitive settings live in the clear so they are queryable/debuggable.
    config: Mapped[dict] = mapped_column(JSONField, default=dict)
    # Everything sensitive is a single Fernet-encrypted blob. See app/security.py.
    secrets_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncStatus(str, enum.Enum):
    running = "running"
    success = "success"
    partial = "partial"
    failed = "failed"


class SyncRun(UUIDMixin, Base):
    """Audit trail: every sync attempt, what it wrote, and why it failed."""

    __tablename__ = "sync_runs"

    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SyncStatus] = mapped_column(String(16), default=SyncStatus.running)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(String(24), default="manual")


class InsightSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class Insight(UUIDMixin, TimestampMixin, Base):
    """A derived, actionable observation produced by the rules engine."""

    __tablename__ = "insights"
    __table_args__ = (
        # Re-running the engine refreshes an insight instead of stacking copies.
        UniqueConstraint("user_id", "dedupe_key", name="uq_insight_dedupe"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(190), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[InsightSeverity] = mapped_column(String(16), default=InsightSeverity.info)
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text, default="")
    action_label: Mapped[str] = mapped_column(String(64), default="")
    action_href: Mapped[str] = mapped_column(String(240), default="")
    data: Mapped[dict] = mapped_column(JSONField, default=dict)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(UUIDMixin, Base):
    """Who did what, when. Cheap to write, invaluable when something looks off."""

    __tablename__ = "audit_events"

    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONField, default=dict)
    source_ip: Mapped[str] = mapped_column(String(64), default="")

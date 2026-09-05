"""Todos and work items."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONField, TimestampMixin, UUIDMixin


class Area(str, enum.Enum):
    work = "work"
    personal = "personal"
    finance = "finance"
    health = "health"
    home = "home"
    learning = "learning"


class TaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"
    cancelled = "cancelled"


OPEN_STATUSES = (TaskStatus.todo, TaskStatus.in_progress, TaskStatus.blocked)


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    area: Mapped[Area] = mapped_column(String(24), default=Area.personal)
    color: Mapped[str] = mapped_column(String(16), default="#6366f1")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class Task(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_task_external"),
        Index("ix_task_user_status", "user_id", "status"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Set when a connector (GitHub, calendar, ...) owns this task.
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(String(190), nullable=True)
    source: Mapped[str] = mapped_column(String(48), default="manual")

    title: Mapped[str] = mapped_column(String(400))
    notes: Mapped[str] = mapped_column(Text, default="")
    area: Mapped[Area] = mapped_column(String(24), default=Area.personal)
    status: Mapped[TaskStatus] = mapped_column(String(24), default=TaskStatus.todo, index=True)
    # 1 = highest. Matches the "P1..P4" convention most task apps use.
    priority: Mapped[int] = mapped_column(Integer, default=3)

    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tags: Mapped[list] = mapped_column(JSONField, default=list)
    url: Mapped[str] = mapped_column(String(400), default="")

    @property
    def is_open(self) -> bool:
        return TaskStatus(self.status) in OPEN_STATUSES

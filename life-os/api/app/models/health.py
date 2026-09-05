"""Health metrics and workouts.

Metrics are stored long/narrow (one row per reading) rather than wide, so a
new metric type from a new device needs no migration.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONField, Quantity, TimestampMixin, UUIDMixin

# Canonical metric keys. Connectors map their own vocabulary onto these so the
# dashboard doesn't care whether a number came from Apple Health or a scale.
METRIC_UNITS = {
    "steps": "count",
    "active_energy": "kcal",
    "exercise_minutes": "min",
    "resting_heart_rate": "bpm",
    "heart_rate_variability": "ms",
    "vo2_max": "ml/kg/min",
    "sleep_duration": "min",
    "sleep_efficiency": "%",
    "weight": "lb",
    "body_fat": "%",
    "mindful_minutes": "min",
    "blood_pressure_systolic": "mmHg",
    "blood_pressure_diastolic": "mmHg",
}


class HealthMetric(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "health_metrics"
    __table_args__ = (
        # One value per metric per day per source: re-importing an Apple Health
        # export updates rows instead of multiplying them.
        UniqueConstraint("user_id", "metric", "recorded_on", "source", name="uq_metric_day"),
        Index("ix_metric_lookup", "user_id", "metric", "recorded_on"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Quantity)
    unit: Mapped[str] = mapped_column(String(24), default="")
    recorded_on: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    extra: Mapped[dict] = mapped_column(JSONField, default=dict)


class Workout(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workouts"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_workout_external"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(190), nullable=True)
    activity: Mapped[str] = mapped_column(String(64), default="workout")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[float] = mapped_column(Quantity, default=0)
    distance_miles: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    energy_kcal: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    avg_heart_rate: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="manual")

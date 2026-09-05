"""Health read models: current values, trends, and series for charts."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.health import METRIC_UNITS, HealthMetric, Workout

# Metrics where a higher number is the better outcome. Drives trend colouring.
HIGHER_IS_BETTER = {
    "steps",
    "active_energy",
    "exercise_minutes",
    "heart_rate_variability",
    "vo2_max",
    "sleep_duration",
    "sleep_efficiency",
    "mindful_minutes",
}

HEADLINE_METRICS = ("steps", "sleep_duration", "resting_heart_rate", "exercise_minutes", "weight")


def _avg(db: Session, user_id: str, metric: str, start: date, end: date) -> float | None:
    value = db.scalar(
        select(func.avg(HealthMetric.value)).where(
            HealthMetric.user_id == user_id,
            HealthMetric.metric == metric,
            HealthMetric.recorded_on >= start,
            HealthMetric.recorded_on <= end,
        )
    )
    return round(float(value), 2) if value is not None else None


def summary(db: Session, user_id: str, metrics: tuple[str, ...] = HEADLINE_METRICS) -> list[dict[str, Any]]:
    """Latest value plus a 7-day average vs the prior 7 days."""
    today = date.today()
    out: list[dict[str, Any]] = []

    for metric in metrics:
        latest = db.scalars(
            select(HealthMetric)
            .where(HealthMetric.user_id == user_id, HealthMetric.metric == metric)
            .order_by(HealthMetric.recorded_on.desc())
            .limit(1)
        ).first()
        if latest is None:
            continue

        recent = _avg(db, user_id, metric, today - timedelta(days=6), today)
        previous = _avg(db, user_id, metric, today - timedelta(days=13), today - timedelta(days=7))
        change = None
        direction = "flat"
        if recent is not None and previous:
            change = round((recent - previous) / abs(previous) * 100, 1)
            if abs(change) >= 2:
                improving = change > 0 if metric in HIGHER_IS_BETTER else change < 0
                direction = "up" if improving else "down"

        out.append(
            {
                "metric": metric,
                "label": metric.replace("_", " ").title(),
                "value": round(float(latest.value), 2),
                "unit": latest.unit or METRIC_UNITS.get(metric, ""),
                "recorded_on": latest.recorded_on.isoformat(),
                "avg_7d": recent,
                "avg_prev_7d": previous,
                "change_pct": change,
                "direction": direction,
                "higher_is_better": metric in HIGHER_IS_BETTER,
            }
        )
    return out


def series(db: Session, user_id: str, metric: str, days: int = 90) -> list[dict[str, Any]]:
    since = date.today() - timedelta(days=days)
    rows = db.scalars(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == user_id,
            HealthMetric.metric == metric,
            HealthMetric.recorded_on >= since,
        )
        .order_by(HealthMetric.recorded_on)
    ).all()
    return [
        {"date": row.recorded_on.isoformat(), "value": round(float(row.value), 2)} for row in rows
    ]


def available_metrics(db: Session, user_id: str) -> list[str]:
    rows = db.scalars(
        select(HealthMetric.metric).where(HealthMetric.user_id == user_id).distinct()
    ).all()
    return sorted(rows)


def recent_workouts(db: Session, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Workout)
        .where(Workout.user_id == user_id)
        .order_by(Workout.started_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": w.id,
            "activity": w.activity,
            "started_at": w.started_at.isoformat(),
            "duration_minutes": round(float(w.duration_minutes or 0), 1),
            "distance_miles": round(float(w.distance_miles), 2) if w.distance_miles else None,
            "energy_kcal": round(float(w.energy_kcal), 0) if w.energy_kcal else None,
            "avg_heart_rate": round(float(w.avg_heart_rate), 0) if w.avg_heart_rate else None,
        }
        for w in rows
    ]

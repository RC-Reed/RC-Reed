"""Health metrics and workouts."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.health import HealthMetric
from app.models.user import User
from app.schemas.core import HealthMetricIn, HealthMetricOut
from app.services import health as health_service
from app.services.upserts import upsert_health_metric

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "metrics": health_service.summary(db, user.id),
        "available": health_service.available_metrics(db, user.id),
        "workouts": health_service.recent_workouts(db, user.id),
    }


@router.get("/series/{metric}")
def series(
    metric: str, days: int = 90, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return health_service.series(db, user.id, metric, days=days)


@router.get("/metrics", response_model=list[HealthMetricOut])
def list_metrics(
    metric: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(HealthMetric).where(HealthMetric.user_id == user.id)
    if metric:
        stmt = stmt.where(HealthMetric.metric == metric)
    return db.scalars(stmt.order_by(HealthMetric.recorded_on.desc()).limit(limit)).all()


@router.post("/metrics", status_code=status.HTTP_201_CREATED)
def record_metric(
    payload: HealthMetricIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Manual entry — a scale reading, a blood pressure cuff, anything offline."""
    created = upsert_health_metric(
        db,
        user_id=user.id,
        metric=payload.metric,
        recorded_on=payload.recorded_on or date.today(),
        value=payload.value,
        unit=payload.unit,
        source=payload.source,
    )
    db.commit()
    return {"created": created}

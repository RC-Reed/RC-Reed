"""Insight feed."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.connections import Insight
from app.models.user import User
from app.schemas.core import InsightOut
from app.services import insights as insights_service

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=list[InsightOut])
def list_insights(
    include_dismissed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Insight).where(Insight.user_id == user.id)
    if not include_dismissed:
        stmt = stmt.where(Insight.dismissed_at.is_(None))
    return db.scalars(stmt.order_by(Insight.created_at.desc())).all()


@router.post("/refresh", response_model=list[InsightOut])
def refresh(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return insights_service.refresh_insights(db, user.id)


@router.post("/{insight_id}/dismiss", response_model=InsightOut)
def dismiss(insight_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    insight = db.get(Insight, insight_id)
    if insight is None or insight.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Insight not found")
    insight.dismissed_at = datetime.now(timezone.utc)
    db.commit()
    return insight

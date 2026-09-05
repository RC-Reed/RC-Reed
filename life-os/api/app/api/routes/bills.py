"""Bills and subscriptions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.bills import Bill
from app.models.user import User
from app.schemas.core import BillIn, BillOut, BillUpdate, MarkPaidRequest
from app.services import bills as bills_service

router = APIRouter(prefix="/bills", tags=["bills"])


def _owned(db: Session, user: User, bill_id: str) -> Bill:
    bill = db.get(Bill, bill_id)
    if bill is None or bill.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return bill


@router.get("", response_model=list[BillOut])
def list_bills(
    subscriptions_only: bool = False,
    include_dismissed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Bill).where(Bill.user_id == user.id, Bill.is_active.is_(True))
    if subscriptions_only:
        stmt = stmt.where(Bill.is_subscription.is_(True))
    if not include_dismissed:
        stmt = stmt.where(Bill.dismissed.is_(False))
    return db.scalars(stmt.order_by(Bill.next_due_on.is_(None), Bill.next_due_on)).all()


@router.get("/upcoming")
def upcoming(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return bills_service.upcoming(db, user.id, days=days)


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return bills_service.monthly_obligations(db, user.id)


@router.post("", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def create_bill(
    payload: BillIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    bill = Bill(user_id=user.id, **payload.model_dump())
    db.add(bill)
    db.commit()
    return bill


@router.patch("/{bill_id}", response_model=BillOut)
def update_bill(
    bill_id: str,
    payload: BillUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bill = _owned(db, user, bill_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(bill, key, value)
    db.commit()
    return bill


@router.post("/{bill_id}/paid", response_model=BillOut)
def mark_paid(
    bill_id: str,
    payload: MarkPaidRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bill = bills_service.mark_paid(
        db, _owned(db, user, bill_id), amount=payload.amount, on=payload.paid_on
    )
    db.commit()
    return bill


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(bill_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_owned(db, user, bill_id))
    db.commit()


@router.post("/detect")
def detect(
    lookback_days: int = 400,
    min_occurrences: int = 3,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Scan transactions for recurring charges and create the missing bills."""
    findings = bills_service.detect_recurring(
        db, user.id, lookback_days=lookback_days, min_occurrences=min_occurrences
    )
    return {"detected": len(findings), "results": findings}

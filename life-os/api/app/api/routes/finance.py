"""Accounts, transactions, holdings and the debt planner."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.finance import Account, DebtDetail, Holding, Transaction
from app.models.user import User
from app.schemas.core import (
    AccountIn,
    AccountOut,
    AccountUpdate,
    DebtDetailIn,
    HoldingOut,
    PayoffRequest,
    TransactionIn,
    TransactionOut,
    TransactionUpdate,
)
from app.services import analytics, debt as debt_service
from app.services.upserts import normalize_merchant, record_balance

router = APIRouter(tags=["finance"])


def _owned_account(db: Session, user: User, account_id: str) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


# --- accounts --------------------------------------------------------------
@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Account).where(Account.user_id == user.id)
    if not include_inactive:
        stmt = stmt.where(Account.is_active.is_(True))
    return db.scalars(stmt.order_by(Account.type, Account.name)).all()


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    account = Account(user_id=user.id, **payload.model_dump())
    db.add(account)
    db.flush()
    record_balance(db, account)
    db.commit()
    return account


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: str,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = _owned_account(db, user, account_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    record_balance(db, account)
    db.commit()
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    db.delete(_owned_account(db, user, account_id))
    db.commit()


@router.put("/accounts/{account_id}/debt", response_model=AccountOut)
def set_debt_detail(
    account_id: str,
    payload: DebtDetailIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Attach APR / minimum payment / due date so the payoff planner can work."""
    account = _owned_account(db, user, account_id)
    if not account.is_liability:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Debt details only apply to credit or loan accounts"
        )
    detail = db.scalars(select(DebtDetail).where(DebtDetail.account_id == account.id)).first()
    if detail is None:
        detail = DebtDetail(account_id=account.id)
        db.add(detail)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(detail, key, value)
    db.commit()
    db.refresh(account)
    return account


# --- transactions ----------------------------------------------------------
@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    account_id: str | None = None,
    category: str | None = None,
    search: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Transaction).where(Transaction.user_id == user.id)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if category:
        stmt = stmt.where(Transaction.category == category)
    if start:
        stmt = stmt.where(Transaction.posted_on >= start)
    if end:
        stmt = stmt.where(Transaction.posted_on <= end)
    if search:
        stmt = stmt.where(Transaction.description.ilike(f"%{search}%"))
    return db.scalars(
        stmt.order_by(Transaction.posted_on.desc(), Transaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _owned_account(db, user, payload.account_id)
    txn = Transaction(
        user_id=user.id,
        merchant=normalize_merchant(payload.description),
        **payload.model_dump(),
    )
    db.add(txn)
    db.commit()
    return txn


@router.patch("/transactions/{transaction_id}", response_model=TransactionOut)
def update_transaction(
    transaction_id: str,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    txn = db.get(Transaction, transaction_id)
    if txn is None or txn.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(txn, key, value)
    db.commit()
    return txn


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Transaction.category).where(Transaction.user_id == user.id).distinct()
    ).all()
    return sorted(filter(None, rows))


# --- holdings --------------------------------------------------------------
@router.get("/holdings", response_model=list[HoldingOut])
def list_holdings(
    account_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(Holding)
        .join(Account, Account.id == Holding.account_id)
        .where(Account.user_id == user.id)
    )
    if account_id:
        stmt = stmt.where(Holding.account_id == account_id)
    return db.scalars(stmt.order_by(Holding.market_value.desc())).all()


# --- analytics -------------------------------------------------------------
@router.get("/finance/net-worth")
def get_net_worth(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return analytics.net_worth(db, user.id)


@router.get("/finance/net-worth/history")
def get_net_worth_history(
    days: int = 180, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return analytics.net_worth_history(db, user.id, days=days)


@router.get("/finance/cash-flow")
def get_cash_flow(
    months: int = 6, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return analytics.cash_flow(db, user.id, months=months)


@router.get("/finance/spending")
def get_spending(
    days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return analytics.spending_by_category(db, user.id, days=days)


@router.get("/finance/allocation")
def get_allocation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return analytics.allocation(db, user.id)


@router.post("/finance/payoff-plan")
def payoff_plan(
    payload: PayoffRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    debts = debt_service.load_debts(db, user.id)
    plan = debt_service.simulate(
        debts, strategy=payload.strategy, extra_payment=payload.extra_payment
    )
    return {
        "plan": plan.__dict__,
        "comparison": debt_service.compare(db, user.id, extra_payment=payload.extra_payment),
    }

"""Read-side calculations: net worth, cash flow, spending, allocation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.finance import Account, BalanceSnapshot, Holding, Transaction


def _f(value: Any) -> float:
    return round(float(value or 0), 2)


def net_worth(db: Session, user_id: str) -> dict[str, Any]:
    accounts = db.scalars(
        select(Account).where(
            Account.user_id == user_id,
            Account.is_active.is_(True),
            Account.include_in_net_worth.is_(True),
        )
    ).all()

    assets = sum(a.signed_balance for a in accounts if not a.is_liability)
    liabilities = sum(-a.signed_balance for a in accounts if a.is_liability)
    by_type: dict[str, float] = defaultdict(float)
    for account in accounts:
        by_type[str(account.type)] += account.signed_balance

    return {
        "assets": _f(assets),
        "liabilities": _f(liabilities),
        "net_worth": _f(assets - liabilities),
        "by_type": {key: _f(value) for key, value in sorted(by_type.items())},
        "account_count": len(accounts),
    }


def net_worth_history(db: Session, user_id: str, days: int = 180) -> list[dict[str, Any]]:
    """Daily net worth from balance snapshots.

    Snapshots are sparse — a connector only writes on sync days — so each
    account's last known balance is carried forward. Without that, a day where
    only the checking account synced would show every other account at zero.
    """
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(BalanceSnapshot.as_of, BalanceSnapshot.account_id, BalanceSnapshot.balance, Account.type)
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .where(
            Account.user_id == user_id,
            Account.include_in_net_worth.is_(True),
            BalanceSnapshot.as_of >= since,
        )
        .order_by(BalanceSnapshot.as_of)
    ).all()
    if not rows:
        return []

    from app.models.finance import LIABILITY_TYPES, AccountType

    by_day: dict[date, dict[str, tuple[float, bool]]] = defaultdict(dict)
    for as_of, account_id, balance, acct_type in rows:
        is_liability = AccountType(acct_type) in LIABILITY_TYPES
        by_day[as_of][account_id] = (float(balance or 0), is_liability)

    carried: dict[str, tuple[float, bool]] = {}
    series: list[dict[str, Any]] = []
    for day in sorted(by_day):
        carried.update(by_day[day])
        assets = sum(v for v, liability in carried.values() if not liability)
        debts = sum(abs(v) for v, liability in carried.values() if liability)
        series.append(
            {
                "date": day.isoformat(),
                "assets": _f(assets),
                "liabilities": _f(debts),
                "net_worth": _f(assets - debts),
            }
        )
    return series


def cash_flow(db: Session, user_id: str, months: int = 6) -> list[dict[str, Any]]:
    """Income vs spending per calendar month, transfers excluded."""
    since = date.today().replace(day=1) - timedelta(days=31 * months)
    rows = db.execute(
        select(Transaction.posted_on, Transaction.amount).where(
            Transaction.user_id == user_id,
            Transaction.posted_on >= since,
            Transaction.is_transfer.is_(False),
            Transaction.pending.is_(False),
        )
    ).all()

    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "spending": 0.0})
    for posted_on, amount in rows:
        key = posted_on.strftime("%Y-%m")
        value = float(amount or 0)
        if value >= 0:
            buckets[key]["income"] += value
        else:
            buckets[key]["spending"] += -value

    return [
        {
            "month": month,
            "income": _f(values["income"]),
            "spending": _f(values["spending"]),
            "net": _f(values["income"] - values["spending"]),
        }
        for month, values in sorted(buckets.items())[-months:]
    ]


def spending_by_category(db: Session, user_id: str, days: int = 30) -> list[dict[str, Any]]:
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(Transaction.category, func.sum(Transaction.amount))
        .where(
            Transaction.user_id == user_id,
            Transaction.posted_on >= since,
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
        )
        .group_by(Transaction.category)
    ).all()

    total = sum(abs(float(amount or 0)) for _, amount in rows) or 1.0
    return sorted(
        (
            {
                "category": category or "uncategorized",
                "amount": _f(abs(float(amount or 0))),
                "share": round(abs(float(amount or 0)) / total * 100, 1),
            }
            for category, amount in rows
        ),
        key=lambda row: row["amount"],
        reverse=True,
    )


def allocation(db: Session, user_id: str) -> dict[str, Any]:
    """Investment mix across every brokerage/retirement account."""
    rows = db.execute(
        select(Holding.asset_class, func.sum(Holding.market_value))
        .join(Account, Account.id == Holding.account_id)
        .where(Account.user_id == user_id)
        .group_by(Holding.asset_class)
    ).all()

    total = sum(float(value or 0) for _, value in rows)
    return {
        "total_value": _f(total),
        "by_class": sorted(
            (
                {
                    "asset_class": asset_class or "other",
                    "value": _f(value),
                    "share": round(float(value or 0) / total * 100, 1) if total else 0.0,
                }
                for asset_class, value in rows
            ),
            key=lambda row: row["value"],
            reverse=True,
        ),
    }


def top_holdings(db: Session, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Holding)
        .join(Account, Account.id == Holding.account_id)
        .where(Account.user_id == user_id)
        .order_by(Holding.market_value.desc())
        .limit(limit)
    ).all()
    return [
        {
            "symbol": h.symbol,
            "name": h.name,
            "asset_class": h.asset_class,
            "quantity": float(h.quantity or 0),
            "price": _f(h.price),
            "market_value": _f(h.market_value),
            "cost_basis": _f(h.cost_basis) if h.cost_basis is not None else None,
            "gain_loss": _f(h.gain_loss) if h.gain_loss is not None else None,
        }
        for h in rows
    ]

"""Debt payoff modelling: avalanche vs snowball, with an extra-payment lever.

The simulation is a straightforward month-by-month amortisation:
  1. accrue one month of interest on each balance,
  2. pay every minimum,
  3. throw all remaining money at one target debt,
  4. when a debt dies, its minimum joins the snowball.

Deliberately simple and inspectable — you can check it against a spreadsheet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.finance import LIABILITY_TYPES, Account, AccountType, DebtDetail

Strategy = Literal["avalanche", "snowball"]
MAX_MONTHS = 600  # 50 years; anything longer means the plan doesn't work

# Used when an account has no APR on file, so a plan is still produced instead
# of silently treating the debt as interest-free.
DEFAULT_APR = {AccountType.credit: 22.0, AccountType.loan: 7.0}


@dataclass
class DebtLine:
    account_id: str
    name: str
    balance: float
    apr: float
    minimum: float
    account_type: str
    paid_off_month: int | None = None
    interest_paid: float = 0.0

    @property
    def monthly_rate(self) -> float:
        return self.apr / 100 / 12


@dataclass
class PayoffPlan:
    strategy: str
    months: int
    total_interest: float
    total_paid: float
    monthly_payment: float
    payoff_date: str | None
    order: list[dict[str, Any]] = field(default_factory=list)
    schedule: list[dict[str, Any]] = field(default_factory=list)
    feasible: bool = True
    note: str = ""


def load_debts(db: Session, user_id: str) -> list[DebtLine]:
    rows = db.execute(
        select(Account, DebtDetail)
        .outerjoin(DebtDetail, DebtDetail.account_id == Account.id)
        .where(Account.user_id == user_id, Account.is_active.is_(True))
    ).all()

    lines: list[DebtLine] = []
    for account, detail in rows:
        if AccountType(account.type) not in LIABILITY_TYPES:
            continue
        balance = abs(float(account.current_balance or 0))
        if balance < 0.01:
            continue
        apr = float(detail.apr) if detail and detail.apr is not None else None
        if apr is None:
            apr = DEFAULT_APR.get(AccountType(account.type), 10.0)
        minimum = float(detail.minimum_payment) if detail and detail.minimum_payment else 0.0
        if minimum <= 0:
            # Card issuers typically use ~2% of balance with a floor of $25.
            minimum = max(25.0, round(balance * 0.02, 2))
        lines.append(
            DebtLine(
                account_id=account.id,
                name=account.name,
                balance=balance,
                apr=apr,
                minimum=min(minimum, balance + balance * (apr / 1200)),
                account_type=str(account.type),
            )
        )
    return lines


def _order(debts: list[DebtLine], strategy: Strategy) -> list[DebtLine]:
    if strategy == "snowball":
        return sorted(debts, key=lambda d: (d.balance, -d.apr))
    return sorted(debts, key=lambda d: (-d.apr, d.balance))


def simulate(
    debts: list[DebtLine], *, strategy: Strategy = "avalanche", extra_payment: float = 0.0
) -> PayoffPlan:
    lines = [
        DebtLine(
            account_id=d.account_id,
            name=d.name,
            balance=d.balance,
            apr=d.apr,
            minimum=d.minimum,
            account_type=d.account_type,
        )
        for d in debts
    ]
    if not lines:
        return PayoffPlan(
            strategy=strategy,
            months=0,
            total_interest=0.0,
            total_paid=0.0,
            monthly_payment=0.0,
            payoff_date=None,
            note="No open debts. Nothing to plan.",
        )

    base_budget = sum(d.minimum for d in lines) + max(extra_payment, 0.0)
    schedule: list[dict[str, Any]] = []
    total_interest = 0.0
    total_paid = 0.0
    month = 0

    while any(d.balance > 0.005 for d in lines) and month < MAX_MONTHS:
        month += 1
        budget = base_budget
        month_interest = 0.0

        for debt in lines:
            if debt.balance <= 0:
                continue
            interest = round(debt.balance * debt.monthly_rate, 2)
            debt.balance += interest
            debt.interest_paid += interest
            month_interest += interest

        # Minimums first — they are non-negotiable.
        for debt in lines:
            if debt.balance <= 0:
                continue
            payment = min(debt.minimum, debt.balance, budget)
            debt.balance -= payment
            budget -= payment
            total_paid += payment

        # Everything left goes to the strategy's current target, cascading as
        # each debt is cleared so no money is wasted in a month.
        for debt in _order([d for d in lines if d.balance > 0], strategy):
            if budget <= 0:
                break
            payment = min(budget, debt.balance)
            debt.balance -= payment
            budget -= payment
            total_paid += payment

        total_interest += month_interest
        for debt in lines:
            if debt.balance <= 0.005 and debt.paid_off_month is None:
                debt.balance = 0.0
                debt.paid_off_month = month

        schedule.append(
            {
                "month": month,
                "remaining_balance": round(sum(d.balance for d in lines), 2),
                "interest_paid": round(month_interest, 2),
            }
        )

        if month_interest >= base_budget and month > 3:
            # Interest outruns the payment: the balance can never fall.
            return PayoffPlan(
                strategy=strategy,
                months=month,
                total_interest=round(total_interest, 2),
                total_paid=round(total_paid, 2),
                monthly_payment=round(base_budget, 2),
                payoff_date=None,
                feasible=False,
                note=(
                    "Monthly interest exceeds the payment budget — this debt cannot be "
                    "paid off at this rate. Increase the extra payment."
                ),
                order=_order_summary(lines, strategy),
                schedule=schedule[:24],
            )

    today = date.today()
    payoff_year = today.year + (today.month - 1 + month) // 12
    payoff_month = (today.month - 1 + month) % 12 + 1

    return PayoffPlan(
        strategy=strategy,
        months=month,
        total_interest=round(total_interest, 2),
        total_paid=round(total_paid, 2),
        monthly_payment=round(base_budget, 2),
        payoff_date=f"{payoff_year}-{payoff_month:02d}",
        order=_order_summary(lines, strategy),
        schedule=schedule,
        feasible=month < MAX_MONTHS,
    )


def _order_summary(lines: list[DebtLine], strategy: Strategy) -> list[dict[str, Any]]:
    """Report the order debts were actually cleared in.

    Sorting the finished lines with _order would be wrong: by then every
    balance is zero, so the strategy's own key no longer distinguishes them.
    The month each debt was paid off is the real answer; anything still
    outstanding falls to the end in strategy order.
    """
    ordered = sorted(
        _order(lines, strategy),
        key=lambda d: (d.paid_off_month is None, d.paid_off_month or 0),
    )
    return [
        {
            "account_id": d.account_id,
            "name": d.name,
            "apr": round(d.apr, 2),
            "minimum": round(d.minimum, 2),
            "paid_off_month": d.paid_off_month,
            "interest_paid": round(d.interest_paid, 2),
        }
        for d in ordered
    ]


def compare(db: Session, user_id: str, extra_payment: float = 0.0) -> dict[str, Any]:
    """Both strategies side by side — the interest delta is the real answer."""
    debts = load_debts(db, user_id)
    avalanche = simulate(debts, strategy="avalanche", extra_payment=extra_payment)
    snowball = simulate(debts, strategy="snowball", extra_payment=extra_payment)

    return {
        "total_debt": round(sum(d.balance for d in debts), 2),
        "debt_count": len(debts),
        "extra_payment": round(extra_payment, 2),
        "avalanche": avalanche.__dict__,
        "snowball": snowball.__dict__,
        "interest_saved_with_avalanche": round(
            snowball.total_interest - avalanche.total_interest, 2
        ),
    }

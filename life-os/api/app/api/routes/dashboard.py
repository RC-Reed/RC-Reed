"""The front page.

One request returns everything the dashboard renders. A personal dashboard is
read almost every time it is opened and written rarely, so paying for a single
wide query beats a dozen round trips.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.connections import Connection, Insight
from app.models.finance import Account, AccountType
from app.models.tasks import OPEN_STATUSES, Task
from app.models.user import User
from app.schemas.core import InsightOut, TaskOut
from app.services import analytics, bills as bills_service, health as health_service
from app.services import debt as debt_service
from app.services import insights as insights_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(
    refresh: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if refresh:
        insights_service.refresh_insights(db, user.id)

    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59)

    open_tasks = db.scalar(
        select(func.count(Task.id)).where(
            Task.user_id == user.id, Task.status.in_([s.value for s in OPEN_STATUSES])
        )
    ) or 0
    overdue_tasks = db.scalar(
        select(func.count(Task.id)).where(
            Task.user_id == user.id,
            Task.status.in_([s.value for s in OPEN_STATUSES]),
            Task.due_at.is_not(None),
            Task.due_at < now,
        )
    ) or 0
    today_tasks = db.scalars(
        select(Task)
        .where(
            Task.user_id == user.id,
            Task.status.in_([s.value for s in OPEN_STATUSES]),
            Task.due_at.is_not(None),
            Task.due_at <= end_of_day,
        )
        .order_by(Task.due_at, Task.priority)
        .limit(8)
    ).all()

    cash = db.scalar(
        select(func.sum(Account.current_balance)).where(
            Account.user_id == user.id,
            Account.type == AccountType.depository,
            Account.is_active.is_(True),
        )
    ) or 0

    debts = debt_service.load_debts(db, user.id)
    plan = debt_service.simulate(debts, strategy="avalanche")

    active_insights = db.scalars(
        select(Insight)
        .where(Insight.user_id == user.id, Insight.dismissed_at.is_(None))
        .order_by(Insight.created_at.desc())
        .limit(12)
    ).all()

    last_sync = db.scalar(
        select(func.max(Connection.last_sync_at)).where(Connection.user_id == user.id)
    )

    return {
        "generated_at": now.isoformat(),
        "user": {"display_name": user.display_name, "email": user.email},
        "finance": {
            **analytics.net_worth(db, user.id),
            "cash_on_hand": round(float(cash), 2),
            "net_worth_history": analytics.net_worth_history(db, user.id, days=180),
            "cash_flow": analytics.cash_flow(db, user.id, months=6),
            "spending_30d": analytics.spending_by_category(db, user.id, days=30)[:6],
        },
        "investments": {
            **analytics.allocation(db, user.id),
            "top_holdings": analytics.top_holdings(db, user.id, limit=8),
        },
        "debt": {
            "total": round(sum(d.balance for d in debts), 2),
            "count": len(debts),
            "months_to_payoff": plan.months,
            "payoff_date": plan.payoff_date,
            "total_interest": plan.total_interest,
            "monthly_minimum": plan.monthly_payment,
            "feasible": plan.feasible,
        },
        "bills": {
            **bills_service.monthly_obligations(db, user.id),
            "upcoming": bills_service.upcoming(db, user.id, days=14),
        },
        "tasks": {
            "open": int(open_tasks),
            "overdue": int(overdue_tasks),
            "today": [TaskOut.model_validate(t).model_dump() for t in today_tasks],
        },
        "health": {"metrics": health_service.summary(db, user.id)},
        "insights": [InsightOut.model_validate(i).model_dump() for i in active_insights],
        "system": {
            "last_sync_at": last_sync.isoformat() if last_sync else None,
            "connection_count": db.scalar(
                select(func.count(Connection.id)).where(Connection.user_id == user.id)
            ) or 0,
        },
    }

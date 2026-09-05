"""The rules engine.

A dashboard that only shows numbers makes you do the noticing. These rules do
the noticing: they run after every sync and turn state into a short list of
things that actually want attention.

Each rule is a small function returning zero or more insight dicts. Adding a
rule means appending to RULES — nothing else changes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bills import Bill
from app.models.connections import Connection, ConnectionStatus, Insight, InsightSeverity
from app.models.finance import Account, AccountType, DebtDetail, Transaction
from app.models.tasks import OPEN_STATUSES, Task
from app.services import bills as bills_service

Rule = Callable[[Session, str], list[dict[str, Any]]]

CREDIT_UTILIZATION_WARN = 30.0
CREDIT_UTILIZATION_CRITICAL = 70.0
BILL_HORIZON_DAYS = 7
SPENDING_SPIKE_FACTOR = 1.5


def _insight(
    kind: str,
    dedupe_key: str,
    title: str,
    body: str,
    *,
    severity: InsightSeverity = InsightSeverity.info,
    action_label: str = "",
    action_href: str = "",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "dedupe_key": dedupe_key,
        "title": title,
        "body": body,
        "severity": severity,
        "action_label": action_label,
        "action_href": action_href,
        "data": data or {},
    }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def rule_bills_due(db: Session, user_id: str) -> list[dict[str, Any]]:
    out = []
    for bill in bills_service.upcoming(db, user_id, days=BILL_HORIZON_DAYS):
        days = bill["days_until_due"]
        if days is None:
            continue
        if days < 0:
            out.append(
                _insight(
                    "bill_overdue",
                    f"bill_overdue:{bill['id']}",
                    f"{bill['name']} is {abs(days)} day(s) overdue",
                    f"${bill['amount']:,.2f} was due {bill['next_due_on']}.",
                    severity=InsightSeverity.critical,
                    action_label="Open bills",
                    action_href="/bills",
                    data=bill,
                )
            )
        elif not bill["autopay"]:
            out.append(
                _insight(
                    "bill_due_soon",
                    f"bill_due:{bill['id']}:{bill['next_due_on']}",
                    f"{bill['name']} due in {days} day(s)",
                    f"${bill['amount']:,.2f} due {bill['next_due_on']}.",
                    severity=InsightSeverity.warning if days <= 2 else InsightSeverity.info,
                    action_label="Open bills",
                    action_href="/bills",
                    data=bill,
                )
            )
    return out


def rule_cash_vs_bills(db: Session, user_id: str) -> list[dict[str, Any]]:
    """Will the cash on hand cover what is due in the next two weeks?"""
    cash = db.scalar(
        select(func.sum(Account.current_balance)).where(
            Account.user_id == user_id,
            Account.type == AccountType.depository,
            Account.is_active.is_(True),
        )
    ) or 0
    due = sum(b["amount"] for b in bills_service.upcoming(db, user_id, days=14))
    if due == 0 or float(cash) >= due:
        return []
    return [
        _insight(
            "cash_shortfall",
            "cash_shortfall",
            "Upcoming bills exceed cash on hand",
            f"${due:,.2f} due in the next 14 days against ${float(cash):,.2f} in checking/savings.",
            severity=InsightSeverity.critical,
            action_label="Review bills",
            action_href="/bills",
            data={"cash": round(float(cash), 2), "due_14d": round(due, 2)},
        )
    ]


def rule_credit_utilization(db: Session, user_id: str) -> list[dict[str, Any]]:
    accounts = db.scalars(
        select(Account).where(
            Account.user_id == user_id,
            Account.type == AccountType.credit,
            Account.is_active.is_(True),
        )
    ).all()
    out = []
    for account in accounts:
        limit = float(account.credit_limit or 0)
        if limit <= 0:
            continue
        utilization = abs(float(account.current_balance or 0)) / limit * 100
        if utilization < CREDIT_UTILIZATION_WARN:
            continue
        out.append(
            _insight(
                "credit_utilization",
                f"utilization:{account.id}",
                f"{account.name} is at {utilization:.0f}% utilization",
                (
                    f"${abs(float(account.current_balance or 0)):,.2f} of a ${limit:,.2f} limit. "
                    "Under 30% is the usual scoring threshold."
                ),
                severity=(
                    InsightSeverity.critical
                    if utilization >= CREDIT_UTILIZATION_CRITICAL
                    else InsightSeverity.warning
                ),
                action_label="Debt plan",
                action_href="/debt",
                data={"utilization": round(utilization, 1), "limit": limit},
            )
        )
    return out


def rule_high_apr_debt(db: Session, user_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Account, DebtDetail)
        .join(DebtDetail, DebtDetail.account_id == Account.id)
        .where(Account.user_id == user_id, Account.is_active.is_(True))
    ).all()
    out = []
    for account, detail in rows:
        apr = float(detail.apr or 0)
        balance = abs(float(account.current_balance or 0))
        if apr < 15 or balance < 100:
            continue
        annual_interest = balance * apr / 100
        out.append(
            _insight(
                "high_apr_debt",
                f"high_apr:{account.id}",
                f"{account.name} costs about ${annual_interest:,.0f}/yr in interest",
                f"${balance:,.2f} at {apr:.2f}% APR. Target this first under the avalanche method.",
                severity=InsightSeverity.warning,
                action_label="Build payoff plan",
                action_href="/debt",
                data={"apr": apr, "balance": balance, "annual_interest": round(annual_interest, 2)},
            )
        )
    return out


def rule_subscription_load(db: Session, user_id: str) -> list[dict[str, Any]]:
    summary = bills_service.monthly_obligations(db, user_id)
    if summary["subscription_count"] == 0:
        return []
    return [
        _insight(
            "subscription_load",
            "subscription_load",
            f"{summary['subscription_count']} subscriptions cost ${summary['subscriptions_monthly']:,.2f}/mo",
            f"That is ${summary['subscriptions_annual']:,.2f} a year. Worth a look for anything unused.",
            severity=InsightSeverity.info,
            action_label="Review subscriptions",
            action_href="/bills?filter=subscriptions",
            data=summary,
        )
    ]


def rule_spending_spike(db: Session, user_id: str) -> list[dict[str, Any]]:
    """Compare this month's spend per category against the prior 3 months."""
    today = date.today()
    month_start = today.replace(day=1)
    baseline_start = month_start - timedelta(days=95)

    rows = db.execute(
        select(Transaction.category, Transaction.posted_on, Transaction.amount).where(
            Transaction.user_id == user_id,
            Transaction.posted_on >= baseline_start,
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
        )
    ).all()

    current: dict[str, float] = defaultdict(float)
    prior: dict[str, list[float]] = defaultdict(list)
    prior_months: dict[tuple[str, str], float] = defaultdict(float)

    for category, posted_on, amount in rows:
        value = abs(float(amount or 0))
        if posted_on >= month_start:
            current[category] += value
        else:
            prior_months[(category, posted_on.strftime("%Y-%m"))] += value

    for (category, _month), total in prior_months.items():
        prior[category].append(total)

    # Only meaningful once the month is far enough along to compare.
    elapsed_fraction = min(today.day / 30, 1.0)
    if elapsed_fraction < 0.4:
        return []

    out = []
    for category, spent in current.items():
        history = prior.get(category, [])
        if len(history) < 2:
            continue
        average = sum(history) / len(history)
        projected = spent / elapsed_fraction
        if average < 50 or projected < average * SPENDING_SPIKE_FACTOR:
            continue
        out.append(
            _insight(
                "spending_spike",
                f"spike:{category}:{today.strftime('%Y-%m')}",
                f"{category.title()} spending is tracking {projected / average:.1f}x normal",
                f"${spent:,.2f} so far this month, projecting ${projected:,.0f} against a ${average:,.0f} average.",
                severity=InsightSeverity.warning,
                action_label="See transactions",
                action_href=f"/transactions?category={category}",
                data={"category": category, "spent": round(spent, 2), "average": round(average, 2)},
            )
        )
    return out


def rule_stale_connections(db: Session, user_id: str) -> list[dict[str, Any]]:
    connections = db.scalars(
        select(Connection).where(Connection.user_id == user_id, Connection.is_enabled.is_(True))
    ).all()
    now = datetime.now(timezone.utc)
    out = []
    for connection in connections:
        if connection.status == ConnectionStatus.error:
            out.append(
                _insight(
                    "connection_error",
                    f"connection_error:{connection.id}",
                    f"{connection.display_name} failed to sync",
                    connection.last_error or "Check the connection settings.",
                    severity=InsightSeverity.warning,
                    action_label="Fix connection",
                    action_href="/connections",
                    data={"connection_id": connection.id},
                )
            )
            continue
        if connection.last_sync_at is None:
            continue
        last = connection.last_sync_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        stale_after = connection.sync_interval_minutes * 60 * 3
        if (now - last).total_seconds() > stale_after:
            out.append(
                _insight(
                    "connection_stale",
                    f"connection_stale:{connection.id}",
                    f"{connection.display_name} data is going stale",
                    f"Last synced {last.date().isoformat()}.",
                    severity=InsightSeverity.info,
                    action_label="Sync now",
                    action_href="/connections",
                    data={"connection_id": connection.id},
                )
            )
    return out


def rule_overdue_tasks(db: Session, user_id: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    count = db.scalar(
        select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.status.in_([s.value for s in OPEN_STATUSES]),
            Task.due_at.is_not(None),
            Task.due_at < now,
        )
    ) or 0
    if not count:
        return []
    return [
        _insight(
            "tasks_overdue",
            "tasks_overdue",
            f"{count} task(s) past due",
            "Reschedule or close them out so the list stays trustworthy.",
            severity=InsightSeverity.warning if count > 3 else InsightSeverity.info,
            action_label="Open tasks",
            action_href="/tasks",
            data={"count": int(count)},
        )
    ]


RULES: tuple[Rule, ...] = (
    rule_bills_due,
    rule_cash_vs_bills,
    rule_credit_utilization,
    rule_high_apr_debt,
    rule_subscription_load,
    rule_spending_spike,
    rule_stale_connections,
    rule_overdue_tasks,
)


def refresh_insights(db: Session, user_id: str, *, commit: bool = True) -> list[Insight]:
    """Run every rule and reconcile the stored insight set.

    Insights the rules no longer produce are deleted rather than left to rot —
    a stale warning is worse than no warning. Dismissed ones are respected
    until the underlying condition clears and returns.
    """
    produced: list[dict[str, Any]] = []
    for rule in RULES:
        try:
            produced.extend(rule(db, user_id))
        except Exception:  # noqa: BLE001 - one broken rule must not blank the page
            import logging

            logging.getLogger("lifeos.insights").exception("rule %s failed", rule.__name__)

    existing = {
        insight.dedupe_key: insight
        for insight in db.scalars(select(Insight).where(Insight.user_id == user_id)).all()
    }
    live_keys = set()

    for payload in produced:
        key = payload["dedupe_key"]
        live_keys.add(key)
        insight = existing.get(key)
        if insight:
            insight.title = payload["title"]
            insight.body = payload["body"]
            insight.severity = payload["severity"]
            insight.data = payload["data"]
            insight.action_label = payload["action_label"]
            insight.action_href = payload["action_href"]
        else:
            db.add(Insight(user_id=user_id, **payload))

    for key, insight in existing.items():
        if key not in live_keys:
            db.delete(insight)

    if commit:
        db.commit()

    return db.scalars(
        select(Insight)
        .where(Insight.user_id == user_id, Insight.dismissed_at.is_(None))
        .order_by(Insight.severity, Insight.created_at.desc())
    ).all()

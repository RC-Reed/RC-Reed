"""Bills, subscriptions, and the recurring-charge detector.

The detector is the part that earns its keep: you do not have to remember to
tell the system about a subscription, because a subscription looks like a
charge from the same merchant, for about the same amount, on a regular
interval. Find that shape in your transactions and you have found the bill.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bills import Bill, BillPayment, Cadence
from app.models.finance import Transaction
from app.services.upserts import normalize_merchant

# Median gap in days -> cadence, with tolerance for weekends and short months.
CADENCE_WINDOWS: tuple[tuple[int, int, Cadence], ...] = (
    (6, 8, Cadence.weekly),
    (12, 16, Cadence.biweekly),
    (27, 34, Cadence.monthly),
    (85, 97, Cadence.quarterly),
    (175, 190, Cadence.semiannual),
    (355, 375, Cadence.annual),
)

CADENCE_STEP = {
    Cadence.weekly: relativedelta(weeks=1),
    Cadence.biweekly: relativedelta(weeks=2),
    Cadence.monthly: relativedelta(months=1),
    Cadence.quarterly: relativedelta(months=3),
    Cadence.semiannual: relativedelta(months=6),
    Cadence.annual: relativedelta(years=1),
}

# Merchants that recur but are not subscriptions you would cancel. The
# distinction matters: the "subscriptions cost you $X/yr" number is only useful
# if it means "money you could stop spending", so utilities, insurance and
# phone service belong with fixed bills even though they recur identically.
# Matched on whole words — otherwise "Progressive Renters" trips the "rent" hint.
NON_SUBSCRIPTION_HINTS = (
    # income and transfers
    "payroll", "transfer", "deposit", "irs", "tax",
    # housing and debt
    "rent", "mortgage", "hoa", "loan", "lease",
    # utilities
    "utility", "utilities", "electric", "water", "sewer", "energy", "power",
    "gas co", "pse", "peco", "coned",
    # telecom
    "wireless", "mobile", "telecom", "broadband", "fios",
    "verizon", "at&t", "t-mobile", "comcast", "xfinity", "spectrum",
    # insurance and care
    "insurance", "geico", "progressive", "allstate", "statefarm", "state farm",
    "tuition", "childcare", "daycare",
)
_NON_SUBSCRIPTION = re.compile(
    r"\b(?:" + "|".join(NON_SUBSCRIPTION_HINTS) + r")\b", re.IGNORECASE
)


def advance_due_date(bill: Bill, today: date | None = None) -> date | None:
    """Roll next_due_on forward until it is in the future."""
    today = today or date.today()
    cadence = Cadence(bill.cadence)
    if cadence == Cadence.one_time or not bill.next_due_on:
        return bill.next_due_on

    step = CADENCE_STEP[cadence]
    due = bill.next_due_on
    guard = 0
    while due < today and guard < 500:
        due += step
        guard += 1
    bill.next_due_on = due
    return due


def mark_paid(db: Session, bill: Bill, *, amount: float | None = None, on: date | None = None) -> Bill:
    on = on or date.today()
    db.add(
        BillPayment(bill_id=bill.id, paid_on=on, amount=amount if amount is not None else bill.amount)
    )
    bill.last_paid_on = on
    cadence = Cadence(bill.cadence)
    if cadence == Cadence.one_time:
        bill.is_active = False
    elif bill.next_due_on:
        bill.next_due_on = bill.next_due_on + CADENCE_STEP[cadence]
        advance_due_date(bill, on)
    return bill


def upcoming(db: Session, user_id: str, *, days: int = 30) -> list[dict[str, Any]]:
    horizon = date.today() + timedelta(days=days)
    bills = db.scalars(
        select(Bill)
        .where(
            Bill.user_id == user_id,
            Bill.is_active.is_(True),
            Bill.dismissed.is_(False),
            Bill.next_due_on.is_not(None),
            Bill.next_due_on <= horizon,
        )
        .order_by(Bill.next_due_on)
    ).all()

    return [
        {
            "id": b.id,
            "name": b.name,
            "amount": round(float(b.amount or 0), 2),
            "cadence": str(b.cadence),
            "next_due_on": b.next_due_on.isoformat() if b.next_due_on else None,
            "days_until_due": b.days_until_due(),
            "is_subscription": b.is_subscription,
            "autopay": b.autopay,
            "overdue": (b.days_until_due() or 0) < 0,
        }
        for b in bills
    ]


def monthly_obligations(db: Session, user_id: str) -> dict[str, Any]:
    bills = db.scalars(
        select(Bill).where(
            Bill.user_id == user_id, Bill.is_active.is_(True), Bill.dismissed.is_(False)
        )
    ).all()
    subscriptions = [b for b in bills if b.is_subscription]
    return {
        "bills_monthly": round(sum(b.monthly_cost for b in bills if not b.is_subscription), 2),
        "subscriptions_monthly": round(sum(b.monthly_cost for b in subscriptions), 2),
        "subscriptions_annual": round(sum(b.monthly_cost for b in subscriptions) * 12, 2),
        "total_monthly": round(sum(b.monthly_cost for b in bills), 2),
        "subscription_count": len(subscriptions),
        "bill_count": len(bills),
    }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
_TRAILING_NOISE = re.compile(r"(?:\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?|\s+#?\d{3,})\s*$")


def _clean_label(items: list[Transaction]) -> str:
    """Build a human name from the raw descriptions.

    Bank descriptions carry a date or store number on the end ("SPOTIFY USA
    09/09"); the shortest description is usually the least decorated, and
    stripping the trailing noise handles the rest.
    """
    shortest = min((t.description for t in items if t.description), key=len, default="")
    cleaned = _TRAILING_NOISE.sub("", shortest).strip()
    return (cleaned or shortest)[:60].title().strip()

def detect_recurring(
    db: Session,
    user_id: str,
    *,
    lookback_days: int = 400,
    min_occurrences: int = 3,
    commit: bool = True,
) -> list[dict[str, Any]]:
    """Find recurring charges and create Bill rows for the new ones.

    Returns one entry per detected series, flagged as created or existing.
    """
    since = date.today() - timedelta(days=lookback_days)
    transactions = db.scalars(
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.posted_on >= since,
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
        )
        .order_by(Transaction.posted_on)
    ).all()

    groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        key = txn.merchant or normalize_merchant(txn.description)
        if key:
            groups[key].append(txn)

    existing = {
        (b.merchant or normalize_merchant(b.name)): b
        for b in db.scalars(select(Bill).where(Bill.user_id == user_id)).all()
    }

    findings: list[dict[str, Any]] = []
    for merchant, items in groups.items():
        if len(items) < min_occurrences:
            continue

        dates = sorted({t.posted_on for t in items})
        if len(dates) < min_occurrences:
            continue
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not gaps:
            continue

        median_gap = statistics.median(gaps)
        cadence = next(
            (c for low, high, c in CADENCE_WINDOWS if low <= median_gap <= high), None
        )
        if cadence is None:
            continue

        amounts = [abs(float(t.amount)) for t in items]
        mean_amount = statistics.fmean(amounts)
        if mean_amount < 1:
            continue
        spread = statistics.pstdev(amounts) / mean_amount if mean_amount else 1.0
        if spread > 0.35:
            # Amount jumps around too much to be a fixed recurring charge.
            continue

        # Regularity is the real signal. Coffee from the same shop at similar
        # prices looks like a subscription on amount alone, but the gaps between
        # charges are all over the place; a real recurring charge lands on a
        # rhythm. Gate on it rather than only folding it into confidence.
        regularity = statistics.pstdev(gaps) / median_gap if median_gap else 1.0
        if regularity > 0.25:
            continue
        # A monthly charge should also span distinct months, not cluster.
        if cadence in (Cadence.monthly, Cadence.quarterly) and len({d.strftime("%Y-%m") for d in dates}) < min_occurrences:
            continue

        confidence = round(
            max(0.0, min(1.0, (1 - min(spread, 1.0)) * 0.5 + (1 - min(regularity, 1.0)) * 0.3
                         + min(len(dates) / 12, 1.0) * 0.2)),
            2,
        )

        label = _clean_label(items)
        is_subscription = not _NON_SUBSCRIPTION.search(merchant)
        next_due = dates[-1] + CADENCE_STEP[cadence]
        while next_due < date.today():
            next_due += CADENCE_STEP[cadence]

        record = {
            "merchant": merchant,
            "name": label or merchant.title(),
            "amount": round(mean_amount, 2),
            "cadence": cadence.value,
            "occurrences": len(dates),
            "confidence": confidence,
            "next_due_on": next_due.isoformat(),
            "is_subscription": is_subscription,
            "monthly_equivalent": None,
            "status": "existing",
        }

        bill = existing.get(merchant)
        if bill:
            # Refresh the amount estimate, but never resurrect something the
            # user dismissed or override fields they edited by hand.
            if bill.auto_detected and not bill.dismissed:
                bill.amount = record["amount"]
                bill.confidence = confidence
                if not bill.next_due_on or bill.next_due_on < date.today():
                    bill.next_due_on = next_due
                record["status"] = "updated"
            record["id"] = bill.id
        else:
            bill = Bill(
                user_id=user_id,
                name=record["name"],
                merchant=merchant,
                amount=record["amount"],
                cadence=cadence,
                next_due_on=next_due,
                account_id=items[-1].account_id,
                is_subscription=is_subscription,
                auto_detected=True,
                confidence=confidence,
                category="subscriptions" if is_subscription else "bills",
                notes=f"Detected from {len(dates)} transactions since {dates[0].isoformat()}.",
            )
            db.add(bill)
            db.flush()
            record["id"] = bill.id
            record["status"] = "created"

        record["monthly_equivalent"] = bill.monthly_cost
        findings.append(record)

    if commit:
        db.commit()
    return sorted(findings, key=lambda r: r["confidence"], reverse=True)

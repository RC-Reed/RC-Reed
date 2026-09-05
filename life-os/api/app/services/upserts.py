"""Idempotent write helpers shared by every connector.

Connectors should never touch the ORM directly for the core entities. Going
through here guarantees two things that matter a lot once syncs run on a
timer: re-running a sync updates rather than duplicates, and every write is
counted so the sync log is honest.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.finance import Account, BalanceSnapshot, DebtDetail, Holding, Transaction
from app.models.health import METRIC_UNITS, HealthMetric, Workout
from app.models.tasks import Task

_NOISE = re.compile(
    r"(?ix)"
    r"\b(?:pos|ach|debit|credit|purchase|payment|recurring|autopay|pmt|des|id|indn|ppd|web)\b"
    r"|[#]\S*"                 # store/reference numbers: "#41", "#4417"
    r"|\*\d+"                  # numeric refs introduced by an asterisk
    r"|\b\d{3,}\b"            # long digit runs: card fragments, invoice numbers
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"   # embedded dates
    r"|\*"                      # a bare asterisk separator, keeping the word after it
)

# Payment processors prepend their own tag to the real merchant name.
# "SQ *NETFLIX.COM" is Netflix, not Square.
_PROCESSOR_PREFIXES = {"sq", "tst", "sp", "py", "pp", "paypal", "sumup", "wpy", "ppl"}


def normalize_merchant(description: str) -> str:
    """Collapse a bank description into a stable merchant key.

    "SQ *NETFLIX.COM 4829 CA 03/14" -> "netflix.com". Good enough to group
    recurring charges; deliberately not clever enough to be unpredictable.
    """
    cleaned = _NOISE.sub(" ", description or "")
    cleaned = re.sub(r"[^A-Za-z0-9.& ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()

    tokens = cleaned.split()
    while tokens and tokens[0] in _PROCESSOR_PREFIXES:
        tokens.pop(0)
    return " ".join(tokens)[:80]


def _apply(obj: Any, values: dict[str, Any]) -> bool:
    """Assign only changed fields. Returns True when something actually moved.

    Note this is *not* the flag the upserts return — they report whether a row
    was inserted, which is what a sync log means by "created".
    """
    changed = False
    for key, value in values.items():
        if value is None:
            continue
        if getattr(obj, key, None) != value:
            setattr(obj, key, value)
            changed = True
    return changed


def upsert_account(
    db: Session,
    *,
    user_id: str,
    external_id: str,
    connection_id: str | None,
    defaults: dict[str, Any],
) -> tuple[Account, bool]:
    stmt = select(Account).where(
        Account.user_id == user_id,
        Account.external_id == external_id,
        Account.connection_id == connection_id,
    )
    account = db.scalars(stmt).first()
    if account:
        _apply(account, defaults)
        account.last_synced_at = datetime.now(tz=None).astimezone()
        return account, False

    account = Account(
        user_id=user_id,
        connection_id=connection_id,
        external_id=external_id,
        last_synced_at=datetime.now(tz=None).astimezone(),
        **defaults,
    )
    db.add(account)
    db.flush()
    return account, True


def record_balance(db: Session, account: Account, as_of: date | None = None) -> None:
    """Write today's balance point. One row per account per day."""
    as_of = as_of or date.today()
    snapshot = db.scalars(
        select(BalanceSnapshot).where(
            BalanceSnapshot.account_id == account.id, BalanceSnapshot.as_of == as_of
        )
    ).first()
    if snapshot:
        snapshot.balance = account.current_balance
        snapshot.available = account.available_balance
        return
    db.add(
        BalanceSnapshot(
            account_id=account.id,
            as_of=as_of,
            balance=account.current_balance,
            available=account.available_balance,
        )
    )


def upsert_debt_detail(db: Session, account: Account, values: dict[str, Any]) -> None:
    detail = db.scalars(
        select(DebtDetail).where(DebtDetail.account_id == account.id)
    ).first()
    if not detail:
        detail = DebtDetail(account_id=account.id)
        db.add(detail)
    _apply(detail, values)


def upsert_transaction(
    db: Session,
    *,
    user_id: str,
    account_id: str,
    external_id: str,
    defaults: dict[str, Any],
) -> tuple[Transaction, bool]:
    txn = db.scalars(
        select(Transaction).where(
            Transaction.account_id == account_id, Transaction.external_id == external_id
        )
    ).first()
    if txn:
        _apply(txn, defaults)
        return txn, False

    defaults.setdefault("merchant", normalize_merchant(defaults.get("description", "")))
    txn = Transaction(
        user_id=user_id, account_id=account_id, external_id=external_id, **defaults
    )
    db.add(txn)
    return txn, True


def upsert_holding(
    db: Session, *, account_id: str, symbol: str, defaults: dict[str, Any]
) -> tuple[Holding, bool]:
    holding = db.scalars(
        select(Holding).where(Holding.account_id == account_id, Holding.symbol == symbol)
    ).first()
    if holding:
        _apply(holding, defaults)
        return holding, False
    holding = Holding(account_id=account_id, symbol=symbol, **defaults)
    db.add(holding)
    return holding, True


def upsert_health_metric(
    db: Session,
    *,
    user_id: str,
    metric: str,
    recorded_on: date,
    value: float,
    source: str,
    unit: str | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Returns True when a new row was created."""
    existing = db.scalars(
        select(HealthMetric).where(
            HealthMetric.user_id == user_id,
            HealthMetric.metric == metric,
            HealthMetric.recorded_on == recorded_on,
            HealthMetric.source == source,
        )
    ).first()
    unit = unit or METRIC_UNITS.get(metric, "")
    if existing:
        existing.value = value
        existing.unit = unit
        if extra:
            existing.extra = extra
        return False
    db.add(
        HealthMetric(
            user_id=user_id,
            metric=metric,
            recorded_on=recorded_on,
            value=value,
            unit=unit,
            source=source,
            extra=extra or {},
        )
    )
    return True


def upsert_workout(
    db: Session, *, user_id: str, external_id: str, defaults: dict[str, Any]
) -> bool:
    existing = db.scalars(
        select(Workout).where(Workout.user_id == user_id, Workout.external_id == external_id)
    ).first()
    if existing:
        _apply(existing, defaults)
        return False
    db.add(Workout(user_id=user_id, external_id=external_id, **defaults))
    return True


def upsert_task(
    db: Session,
    *,
    user_id: str,
    connection_id: str,
    external_id: str,
    defaults: dict[str, Any],
) -> bool:
    existing = db.scalars(
        select(Task).where(
            Task.connection_id == connection_id, Task.external_id == external_id
        )
    ).first()
    if existing:
        # Never clobber a status the user set by hand from an upstream refresh.
        defaults.pop("status", None)
        _apply(existing, defaults)
        return False
    db.add(
        Task(user_id=user_id, connection_id=connection_id, external_id=external_id, **defaults)
    )
    return True

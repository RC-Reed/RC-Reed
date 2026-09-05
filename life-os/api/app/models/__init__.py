"""Import every model module so metadata.create_all() sees the full schema."""

from app.models.base import Base  # noqa: F401
from app.models.bills import Bill, BillPayment, Cadence  # noqa: F401
from app.models.connections import (  # noqa: F401
    AuditEvent,
    Connection,
    ConnectionStatus,
    Insight,
    InsightSeverity,
    SyncRun,
    SyncStatus,
)
from app.models.finance import (  # noqa: F401
    Account,
    AccountType,
    BalanceSnapshot,
    DebtDetail,
    Holding,
    Transaction,
)
from app.models.health import METRIC_UNITS, HealthMetric, Workout  # noqa: F401
from app.models.tasks import Area, Project, Task, TaskStatus  # noqa: F401
from app.models.user import User  # noqa: F401

__all__ = [
    "Base",
    "User",
    "Account",
    "AccountType",
    "BalanceSnapshot",
    "Transaction",
    "Holding",
    "DebtDetail",
    "Bill",
    "BillPayment",
    "Cadence",
    "Project",
    "Task",
    "TaskStatus",
    "Area",
    "HealthMetric",
    "Workout",
    "METRIC_UNITS",
    "Connection",
    "ConnectionStatus",
    "SyncRun",
    "SyncStatus",
    "Insight",
    "InsightSeverity",
    "AuditEvent",
]

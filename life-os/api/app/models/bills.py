"""Bills and subscriptions — anything with a due date and a cadence."""

from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, UUIDMixin


class Cadence(str, enum.Enum):
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    semiannual = "semiannual"
    annual = "annual"
    one_time = "one_time"


CADENCE_DAYS = {
    Cadence.weekly: 7,
    Cadence.biweekly: 14,
    Cadence.monthly: 30,
    Cadence.quarterly: 91,
    Cadence.semiannual: 182,
    Cadence.annual: 365,
    Cadence.one_time: 0,
}


class Bill(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bills"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    merchant: Mapped[str] = mapped_column(String(190), default="", index=True)
    category: Mapped[str] = mapped_column(String(64), default="bills")

    amount: Mapped[float] = mapped_column(Money, default=0)
    cadence: Mapped[Cadence] = mapped_column(String(24), default=Cadence.monthly)
    next_due_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    # A subscription is a bill you could cancel; separating them makes the
    # "what am I actually paying for" view possible.
    is_subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    autopay: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Set when the recurring-charge detector created this rather than a human.
    auto_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float | None] = mapped_column(Money, nullable=True)
    # Detector output the user rejected; kept so it is not re-suggested forever.
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    url: Mapped[str] = mapped_column(String(400), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    def days_until_due(self, today: date | None = None) -> int | None:
        if not self.next_due_on:
            return None
        return (self.next_due_on - (today or date.today())).days

    @property
    def monthly_cost(self) -> float:
        """Normalised to a month so bills of different cadences can be summed."""
        amount = float(self.amount or 0)
        factors = {
            Cadence.weekly: 52 / 12,
            Cadence.biweekly: 26 / 12,
            Cadence.monthly: 1.0,
            Cadence.quarterly: 1 / 3,
            Cadence.semiannual: 1 / 6,
            Cadence.annual: 1 / 12,
            Cadence.one_time: 0.0,
        }
        return round(amount * factors[Cadence(self.cadence)], 2)


class BillPayment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bill_payments"

    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"), index=True)
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Money)
    transaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )

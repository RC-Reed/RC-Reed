"""Financial domain: accounts, balances, transactions, holdings, debt."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONField, Money, Quantity, TimestampMixin, UUIDMixin


class AccountType(str, enum.Enum):
    """Drives whether a balance counts as an asset or a liability."""

    depository = "depository"      # checking, savings, HSA cash
    investment = "investment"      # brokerage, 401k, IRA (Fidelity lives here)
    credit = "credit"              # credit cards
    loan = "loan"                  # student, auto, mortgage, personal
    property = "property"          # house, car — manually valued
    other = "other"


LIABILITY_TYPES = {AccountType.credit, AccountType.loan}


class Account(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_account_external"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Stable id from the upstream provider; lets a re-sync update instead of duplicate.
    external_id: Mapped[str | None] = mapped_column(String(190), nullable=True)

    name: Mapped[str] = mapped_column(String(160))
    institution: Mapped[str] = mapped_column(String(160), default="")
    type: Mapped[AccountType] = mapped_column(String(32), default=AccountType.depository)
    subtype: Mapped[str] = mapped_column(String(64), default="")
    mask: Mapped[str] = mapped_column(String(16), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    current_balance: Mapped[float] = mapped_column(Money, default=0)
    available_balance: Mapped[float | None] = mapped_column(Money, nullable=True)
    credit_limit: Mapped[float | None] = mapped_column(Money, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Excluded accounts still sync but stay out of net worth (e.g. a shared account).
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict] = mapped_column(JSONField, default=dict)

    debt: Mapped["DebtDetail | None"] = relationship(
        back_populates="account", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def is_liability(self) -> bool:
        return AccountType(self.type) in LIABILITY_TYPES

    @property
    def signed_balance(self) -> float:
        """Balance as it contributes to net worth (liabilities are negative).

        Providers report card/loan balances as a positive number owed, so we
        flip the sign here rather than storing two conventions.
        """
        value = float(self.current_balance or 0)
        return -abs(value) if self.is_liability else value


class BalanceSnapshot(UUIDMixin, Base):
    """Daily point-in-time balance, the raw material for net worth history."""

    __tablename__ = "balance_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "as_of", name="uq_snapshot_account_day"),
        Index("ix_snapshot_asof", "as_of"),
    )

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    balance: Mapped[float] = mapped_column(Money)
    available: Mapped[float | None] = mapped_column(Money, nullable=True)


class Transaction(UUIDMixin, TimestampMixin, Base):
    """Signed amounts: positive = money in, negative = money out. Always."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_txn_external"),
        Index("ix_txn_user_date", "user_id", "posted_on"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(190), nullable=True)

    posted_on: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Money)
    description: Mapped[str] = mapped_column(String(400), default="")
    merchant: Mapped[str] = mapped_column(String(190), default="", index=True)
    category: Mapped[str] = mapped_column(String(64), default="uncategorized", index=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    # Transfers between your own accounts must not count as income or spending.
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    bill_id: Mapped[str | None] = mapped_column(
        ForeignKey("bills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    raw: Mapped[dict] = mapped_column(JSONField, default=dict)


class Holding(UUIDMixin, TimestampMixin, Base):
    """A position inside an investment account (Fidelity, 401k, IRA...)."""

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_holding_symbol"),)

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(190), default="")
    asset_class: Mapped[str] = mapped_column(String(32), default="equity")
    quantity: Mapped[float] = mapped_column(Quantity, default=0)
    price: Mapped[float] = mapped_column(Money, default=0)
    market_value: Mapped[float] = mapped_column(Money, default=0)
    cost_basis: Mapped[float | None] = mapped_column(Money, nullable=True)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def gain_loss(self) -> float | None:
        if self.cost_basis is None:
            return None
        return float(self.market_value or 0) - float(self.cost_basis)


class DebtDetail(UUIDMixin, TimestampMixin, Base):
    """The extra fields a payoff plan needs but a plain balance doesn't carry."""

    __tablename__ = "debt_details"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, index=True
    )
    apr: Mapped[float | None] = mapped_column(Money, nullable=True)
    minimum_payment: Mapped[float | None] = mapped_column(Money, nullable=True)
    statement_balance: Mapped[float | None] = mapped_column(Money, nullable=True)
    next_payment_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    original_principal: Mapped[float | None] = mapped_column(Money, nullable=True)
    term_months: Mapped[int | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    account: Mapped[Account] = relationship(back_populates="debt")

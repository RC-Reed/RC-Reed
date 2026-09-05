"""Request/response models.

Money crosses the wire as float: the database keeps exact decimals, and JSON
has no decimal type, so converting once here beats string-typed amounts
everywhere in the UI.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.bills import Cadence
from app.models.finance import AccountType
from app.models.tasks import Area, TaskStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, description="At least 10 characters.")
    display_name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserOut(ORMModel):
    id: str
    email: str
    display_name: str
    timezone: str


# --- accounts --------------------------------------------------------------
class AccountIn(BaseModel):
    name: str
    institution: str = ""
    type: AccountType = AccountType.depository
    subtype: str = ""
    mask: str = ""
    currency: str = "USD"
    current_balance: float = 0
    available_balance: float | None = None
    credit_limit: float | None = None
    include_in_net_worth: bool = True


class AccountUpdate(BaseModel):
    name: str | None = None
    institution: str | None = None
    type: AccountType | None = None
    current_balance: float | None = None
    credit_limit: float | None = None
    include_in_net_worth: bool | None = None
    is_active: bool | None = None


class DebtDetailIn(BaseModel):
    apr: float | None = None
    minimum_payment: float | None = None
    statement_balance: float | None = None
    next_payment_due: date | None = None
    original_principal: float | None = None
    term_months: int | None = None
    notes: str = ""


class DebtDetailOut(DebtDetailIn):
    model_config = ConfigDict(from_attributes=True)


class AccountOut(ORMModel):
    id: str
    name: str
    institution: str
    type: str
    subtype: str
    mask: str
    currency: str
    current_balance: float
    available_balance: float | None
    credit_limit: float | None
    include_in_net_worth: bool
    is_active: bool
    connection_id: str | None
    last_synced_at: datetime | None
    signed_balance: float
    is_liability: bool
    debt: DebtDetailOut | None = None


# --- transactions ----------------------------------------------------------
class TransactionOut(ORMModel):
    id: str
    account_id: str
    posted_on: date
    amount: float
    description: str
    merchant: str
    category: str
    pending: bool
    is_transfer: bool
    bill_id: str | None


class TransactionIn(BaseModel):
    account_id: str
    posted_on: date
    amount: float
    description: str
    category: str = "uncategorized"
    is_transfer: bool = False


class TransactionUpdate(BaseModel):
    category: str | None = None
    is_transfer: bool | None = None
    description: str | None = None
    bill_id: str | None = None


# --- holdings --------------------------------------------------------------
class HoldingOut(ORMModel):
    id: str
    account_id: str
    symbol: str
    name: str
    asset_class: str
    quantity: float
    price: float
    market_value: float
    cost_basis: float | None
    as_of: date | None


# --- bills -----------------------------------------------------------------
class BillIn(BaseModel):
    name: str
    amount: float
    cadence: Cadence = Cadence.monthly
    next_due_on: date | None = None
    merchant: str = ""
    category: str = "bills"
    account_id: str | None = None
    is_subscription: bool = False
    autopay: bool = False
    url: str = ""
    notes: str = ""


class BillUpdate(BaseModel):
    name: str | None = None
    amount: float | None = None
    cadence: Cadence | None = None
    next_due_on: date | None = None
    is_subscription: bool | None = None
    autopay: bool | None = None
    is_active: bool | None = None
    dismissed: bool | None = None
    url: str | None = None
    notes: str | None = None


class BillOut(ORMModel):
    id: str
    name: str
    merchant: str
    amount: float
    cadence: str
    category: str
    next_due_on: date | None
    last_paid_on: date | None
    is_subscription: bool
    autopay: bool
    is_active: bool
    auto_detected: bool
    confidence: float | None
    dismissed: bool
    url: str
    notes: str
    monthly_cost: float


class MarkPaidRequest(BaseModel):
    amount: float | None = None
    paid_on: date | None = None


# --- tasks -----------------------------------------------------------------
class ProjectIn(BaseModel):
    name: str
    area: Area = Area.personal
    color: str = "#6366f1"
    notes: str = ""


class ProjectOut(ORMModel):
    id: str
    name: str
    area: str
    color: str
    is_archived: bool
    notes: str


class TaskIn(BaseModel):
    title: str
    notes: str = ""
    area: Area = Area.personal
    project_id: str | None = None
    status: TaskStatus = TaskStatus.todo
    priority: int = Field(default=3, ge=1, le=4)
    due_at: datetime | None = None
    estimate_minutes: int | None = None
    tags: list[str] = Field(default_factory=list)
    url: str = ""


class TaskUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    area: Area | None = None
    project_id: str | None = None
    status: TaskStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    due_at: datetime | None = None
    estimate_minutes: int | None = None
    tags: list[str] | None = None


class TaskOut(ORMModel):
    id: str
    title: str
    notes: str
    area: str
    status: str
    priority: int
    project_id: str | None
    due_at: datetime | None
    completed_at: datetime | None
    estimate_minutes: int | None
    tags: list[str]
    source: str
    url: str


# --- health ----------------------------------------------------------------
class HealthMetricIn(BaseModel):
    metric: str
    value: float
    recorded_on: date | None = None
    unit: str = ""
    source: str = "manual"


class HealthMetricOut(ORMModel):
    id: str
    metric: str
    value: float
    unit: str
    recorded_on: date
    source: str


# --- connections -----------------------------------------------------------
class ConnectionIn(BaseModel):
    connector_slug: str
    display_name: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, Any] = Field(default_factory=dict)
    sync_interval_minutes: int = 60

    @field_validator("sync_interval_minutes")
    @classmethod
    def _sane_interval(cls, value: int) -> int:
        # Below 5 minutes you are just rate-limiting yourself at the provider.
        return max(5, min(value, 60 * 24 * 7))


class ConnectionUpdate(BaseModel):
    display_name: str | None = None
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    sync_interval_minutes: int | None = None
    is_enabled: bool | None = None


class ConnectionOut(ORMModel):
    id: str
    connector_slug: str
    display_name: str
    status: str
    is_enabled: bool
    config: dict[str, Any]
    sync_interval_minutes: int
    last_sync_at: datetime | None
    last_error: str | None
    has_secrets: bool = False
    connector: dict[str, Any] | None = None


class SyncRunOut(ORMModel):
    id: str
    connection_id: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    created_count: int
    updated_count: int
    message: str
    trigger: str


# --- insights --------------------------------------------------------------
class InsightOut(ORMModel):
    id: str
    kind: str
    severity: str
    title: str
    body: str
    action_label: str
    action_href: str
    data: dict[str, Any]
    created_at: datetime


# --- misc ------------------------------------------------------------------
class PayoffRequest(BaseModel):
    extra_payment: float = 0.0
    strategy: Literal["avalanche", "snowball"] = "avalanche"

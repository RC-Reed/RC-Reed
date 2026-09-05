"""The connector contract.

Everything that brings outside data into Life OS is a Connector. Adding an
integration means writing one class and decorating it with @register — no
changes to the API layer, the scheduler, or the UI, because all three are
driven by this metadata.

Two shapes are supported:

  pull  — Life OS reaches out on a schedule (Plaid, an ICS feed, GitHub).
          Implement sync().
  push  — the outside world sends data in (Apple Health via an iOS
          automation, a CSV you export from Fidelity). Implement ingest().

A connector may do both; declare it with `mode`.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


class ConnectorCategory(str, enum.Enum):
    finance = "finance"
    health = "health"
    productivity = "productivity"
    work = "work"
    other = "other"


class ConnectorMode(str, enum.Enum):
    pull = "pull"
    push = "push"
    both = "both"


class FieldType(str, enum.Enum):
    text = "text"
    password = "password"
    number = "number"
    select = "select"
    url = "url"
    textarea = "textarea"
    checkbox = "checkbox"


@dataclass(frozen=True)
class ConnectorField:
    """One input on the connector's setup form. The UI renders from these."""

    key: str
    label: str
    type: FieldType = FieldType.text
    required: bool = True
    secret: bool = False
    help: str = ""
    default: Any = None
    options: tuple[str, ...] = ()


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> "SyncResult":
        self.created += other.created
        self.updated += other.updated
        self.warnings.extend(other.warnings)
        return self

    @property
    def total(self) -> int:
        return self.created + self.updated


class ConnectorError(Exception):
    """Raised for expected, reportable failures (bad creds, malformed file)."""


@dataclass
class SyncContext:
    """Everything a connector needs, and nothing it doesn't."""

    db: Session
    user_id: str
    connection_id: str
    config: dict[str, Any]
    secrets: dict[str, Any]
    # Scratch space a connector owns across runs (sync cursors, last-seen ids).
    # The sync runner persists it back onto the connection after a successful
    # run, so connectors never write to the Connection row themselves.
    state: dict[str, Any] = field(default_factory=dict)

    def opt(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)


@dataclass
class IngestPayload:
    """Data pushed in from outside: an uploaded file or a JSON body."""

    content_type: str = "application/json"
    filename: str = ""
    text: str = ""
    json: Any = None


class Connector(ABC):
    slug: str = ""
    name: str = ""
    category: ConnectorCategory = ConnectorCategory.other
    mode: ConnectorMode = ConnectorMode.pull
    description: str = ""
    # What this connector writes, for the UI ("accounts", "transactions", ...).
    provides: tuple[str, ...] = ()
    fields: tuple[ConnectorField, ...] = ()
    docs_url: str = ""
    # False for connectors that need a human or a file and can't run on a timer.
    schedulable: bool = True

    @property
    def secret_field_keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields if f.secret)

    def validate(self, config: dict[str, Any], secrets: dict[str, Any]) -> list[str]:
        """Return a list of human-readable problems; empty means good to go."""
        problems: list[str] = []
        for spec in self.fields:
            if not spec.required:
                continue
            bucket = secrets if spec.secret else config
            if not str(bucket.get(spec.key, "") or "").strip():
                problems.append(f"{spec.label} is required")
        return problems

    def sync(self, ctx: SyncContext) -> SyncResult:
        """Pull data in. Override for pull/both connectors."""
        raise ConnectorError(f"{self.name} does not support scheduled sync")

    def ingest(self, ctx: SyncContext, payload: IngestPayload) -> SyncResult:
        """Accept pushed data. Override for push/both connectors."""
        raise ConnectorError(f"{self.name} does not accept pushed data")

    def describe(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "category": self.category.value,
            "mode": self.mode.value,
            "description": self.description,
            "provides": list(self.provides),
            "docs_url": self.docs_url,
            "schedulable": self.schedulable,
            "fields": [
                {
                    "key": f.key,
                    "label": f.label,
                    "type": f.type.value,
                    "required": f.required,
                    "secret": f.secret,
                    "help": f.help,
                    "default": f.default,
                    "options": list(f.options),
                }
                for f in self.fields
            ],
        }

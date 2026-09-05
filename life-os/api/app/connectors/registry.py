"""Connector registry.

Import side effects do the work: every module listed in `_MODULES` is imported
once, and each @register decorator adds itself here.
"""

from __future__ import annotations

import importlib
from typing import Iterable

from app.connectors.base import Connector

_REGISTRY: dict[str, Connector] = {}

_MODULES = (
    "app.connectors.manual",
    "app.connectors.plaid_connector",
    "app.connectors.fidelity_csv",
    "app.connectors.bank_csv",
    "app.connectors.apple_health",
    "app.connectors.ics_calendar",
    "app.connectors.github_work",
)

_loaded = False


def register(cls: type[Connector]) -> type[Connector]:
    instance = cls()
    if not instance.slug:
        raise ValueError(f"{cls.__name__} is missing a slug")
    if instance.slug in _REGISTRY:
        raise ValueError(f"duplicate connector slug: {instance.slug}")
    _REGISTRY[instance.slug] = instance
    return cls


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    # Set first: a connector module that imports the registry back must not
    # re-enter this function.
    _loaded = True
    for module in _MODULES:
        importlib.import_module(module)


def get_connector(slug: str) -> Connector | None:
    _ensure_loaded()
    return _REGISTRY.get(slug)


def all_connectors() -> Iterable[Connector]:
    _ensure_loaded()
    return sorted(_REGISTRY.values(), key=lambda c: (c.category.value, c.name))

"""Manual entry.

Not every number has an API. Property values, a 401k your employer hides
behind a portal, cash under the mattress — you type those in, and they still
need to be first-class citizens of net worth. This connector exists so that
manually-entered accounts have somewhere to belong and still get a daily
balance snapshot written for history.
"""

from __future__ import annotations

from sqlalchemy import select

from app.connectors.base import Connector, ConnectorCategory, ConnectorMode, SyncContext, SyncResult
from app.connectors.registry import register
from app.models.finance import Account
from app.services.upserts import record_balance


@register
class ManualConnector(Connector):
    slug = "manual"
    name = "Manual Entry"
    category = ConnectorCategory.finance
    mode = ConnectorMode.pull
    description = (
        "Accounts you maintain by hand — property, cash, anything without an API. "
        "Syncing snapshots today's balances so manual accounts still build history."
    )
    provides = ("accounts", "balances")
    fields = ()

    def sync(self, ctx: SyncContext) -> SyncResult:
        accounts = ctx.db.scalars(
            select(Account).where(
                Account.user_id == ctx.user_id,
                Account.connection_id == ctx.connection_id,
                Account.is_active.is_(True),
            )
        ).all()
        for account in accounts:
            record_balance(ctx.db, account)
        return SyncResult(
            updated=len(accounts),
            message=f"Snapshotted {len(accounts)} manual account(s)",
        )

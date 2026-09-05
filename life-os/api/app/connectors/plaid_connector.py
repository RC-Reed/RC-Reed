"""Plaid — automated banking, credit, loan and investment sync.

This is the automated path for balances, debt and Fidelity holdings. You
supply a client id, a secret and an access token for an Item you have already
linked; Life OS then pulls on a schedule.

Getting an access token: Plaid's Link flow exchanges a public token for an
access token. For a personal setup the quickest route is Plaid's Quickstart
(https://plaid.com/docs/quickstart/) run locally once — copy the resulting
access token here. Life OS deliberately does not host Link itself: that would
mean standing up a public callback, and a personal system shouldn't need one.

Everything here degrades gracefully. If your Plaid plan doesn't include
liabilities or investments, those calls are skipped with a warning rather
than failing the whole sync.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from app.connectors.base import (
    Connector,
    ConnectorCategory,
    ConnectorError,
    ConnectorField,
    ConnectorMode,
    FieldType,
    SyncContext,
    SyncResult,
)
from app.connectors.registry import register
from app.models.finance import AccountType
from app.services.upserts import (
    record_balance,
    upsert_account,
    upsert_debt_detail,
    upsert_holding,
    upsert_transaction,
)

ENVIRONMENTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}

# Plaid's account types line up almost 1:1 with ours.
TYPE_MAP = {
    "depository": AccountType.depository,
    "credit": AccountType.credit,
    "loan": AccountType.loan,
    "investment": AccountType.investment,
    "brokerage": AccountType.investment,
    "other": AccountType.other,
}


@register
class PlaidConnector(Connector):
    slug = "plaid"
    name = "Plaid (banks, cards, loans, brokerages)"
    category = ConnectorCategory.finance
    mode = ConnectorMode.pull
    description = (
        "Automated sync of balances, transactions, credit-card and loan terms, "
        "and investment holdings for any institution Plaid supports — including "
        "Fidelity."
    )
    provides = ("accounts", "balances", "transactions", "holdings", "debt")
    docs_url = "https://plaid.com/docs/quickstart/"
    fields = (
        ConnectorField(
            key="environment",
            label="Plaid environment",
            type=FieldType.select,
            default="production",
            options=tuple(ENVIRONMENTS),
        ),
        ConnectorField(key="client_id", label="Client ID", secret=True),
        ConnectorField(key="secret", label="Secret", type=FieldType.password, secret=True),
        ConnectorField(
            key="access_token",
            label="Access token",
            type=FieldType.password,
            secret=True,
            help="The access_token for one linked Item. Add one connection per institution.",
        ),
        ConnectorField(
            key="sync_transactions",
            label="Sync transactions",
            type=FieldType.checkbox,
            required=False,
            default=True,
        ),
        ConnectorField(
            key="sync_investments",
            label="Sync investment holdings",
            type=FieldType.checkbox,
            required=False,
            default=True,
        ),
    )

    # ------------------------------------------------------------------
    def _post(self, ctx: SyncContext, path: str, body: dict[str, Any]) -> dict[str, Any]:
        base = ENVIRONMENTS.get(ctx.opt("environment", "production"), ENVIRONMENTS["production"])
        payload = {
            "client_id": ctx.secrets.get("client_id"),
            "secret": ctx.secrets.get("secret"),
            "access_token": ctx.secrets.get("access_token"),
            **body,
        }
        try:
            response = httpx.post(f"{base}{path}", json=payload, timeout=45)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Could not reach Plaid: {exc}") from exc

        if response.status_code >= 400:
            detail = response.json() if "json" in response.headers.get("content-type", "") else {}
            code = detail.get("error_code", response.status_code)
            message = detail.get("error_message", response.text[:200])
            if code in {"ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN"}:
                raise ConnectorError(f"Re-authentication needed at your institution ({code}).")
            raise ConnectorError(f"Plaid error {code}: {message}")
        return response.json()

    # ------------------------------------------------------------------
    def sync(self, ctx: SyncContext) -> SyncResult:
        result = SyncResult()
        accounts_by_plaid_id = self._sync_accounts(ctx, result)

        if ctx.opt("sync_transactions", True):
            self._sync_transactions(ctx, result, accounts_by_plaid_id)
        self._sync_liabilities(ctx, result, accounts_by_plaid_id)
        if ctx.opt("sync_investments", True):
            self._sync_holdings(ctx, result, accounts_by_plaid_id)

        result.message = f"Plaid sync: {result.created} new, {result.updated} updated"
        return result

    def _sync_accounts(self, ctx: SyncContext, result: SyncResult) -> dict[str, Any]:
        data = self._post(ctx, "/accounts/balance/get", {})
        mapping: dict[str, Any] = {}
        institution = data.get("item", {}).get("institution_id", "")

        for entry in data.get("accounts", []):
            balances = entry.get("balances", {})
            account, created = upsert_account(
                ctx.db,
                user_id=ctx.user_id,
                connection_id=ctx.connection_id,
                external_id=entry["account_id"],
                defaults={
                    "name": entry.get("name") or entry.get("official_name") or "Account",
                    "institution": ctx.opt("institution_name") or institution,
                    "type": TYPE_MAP.get(entry.get("type", "other"), AccountType.other),
                    "subtype": entry.get("subtype") or "",
                    "mask": entry.get("mask") or "",
                    "currency": balances.get("iso_currency_code") or "USD",
                    "current_balance": balances.get("current") or 0,
                    "available_balance": balances.get("available"),
                    "credit_limit": balances.get("limit"),
                },
            )
            record_balance(ctx.db, account)
            mapping[entry["account_id"]] = account
            result.created += int(created)
            result.updated += int(not created)
        return mapping

    def _sync_transactions(
        self, ctx: SyncContext, result: SyncResult, accounts: dict[str, Any]
    ) -> None:
        """Incremental pull via /transactions/sync, resuming from a saved cursor."""
        cursor = ctx.state.get("transactions_cursor")
        pages = 0
        while pages < 25:  # bounded so one huge backfill can't run forever
            body: dict[str, Any] = {"count": 500}
            if cursor:
                body["cursor"] = cursor
            data = self._post(ctx, "/transactions/sync", body)

            for group in ("added", "modified"):
                for txn in data.get(group, []):
                    account = accounts.get(txn.get("account_id"))
                    if account is None:
                        continue
                    posted = txn.get("date")
                    _, created = upsert_transaction(
                        ctx.db,
                        user_id=ctx.user_id,
                        account_id=account.id,
                        external_id=txn["transaction_id"],
                        defaults={
                            # Plaid reports outflow as positive; we store it negative.
                            "amount": -float(txn.get("amount") or 0),
                            "posted_on": date.fromisoformat(posted) if posted else date.today(),
                            "description": txn.get("name") or "",
                            "merchant": (txn.get("merchant_name") or "").lower(),
                            "category": (txn.get("personal_finance_category") or {}).get(
                                "primary", "uncategorized"
                            ).lower(),
                            "pending": bool(txn.get("pending")),
                            "is_transfer": (txn.get("personal_finance_category") or {})
                            .get("primary", "")
                            .upper()
                            .startswith("TRANSFER"),
                        },
                    )
                    result.created += int(created)
                    result.updated += int(not created)

            cursor = data.get("next_cursor")
            pages += 1
            if not data.get("has_more"):
                break

        if cursor:
            ctx.state["transactions_cursor"] = cursor

    def _sync_liabilities(
        self, ctx: SyncContext, result: SyncResult, accounts: dict[str, Any]
    ) -> None:
        try:
            data = self._post(ctx, "/liabilities/get", {})
        except ConnectorError as exc:
            result.warnings.append(f"Liabilities skipped: {exc}")
            return

        liabilities = data.get("liabilities", {})
        for card in liabilities.get("credit", []) or []:
            account = accounts.get(card.get("account_id"))
            if not account:
                continue
            apr_entries = card.get("aprs") or []
            purchase_apr = next(
                (a.get("apr_percentage") for a in apr_entries if a.get("apr_type") == "purchase_apr"),
                apr_entries[0].get("apr_percentage") if apr_entries else None,
            )
            upsert_debt_detail(
                ctx.db,
                account,
                {
                    "apr": purchase_apr,
                    "minimum_payment": card.get("minimum_payment_amount"),
                    "statement_balance": card.get("last_statement_balance"),
                    "next_payment_due": _as_date(card.get("next_payment_due_date")),
                },
            )
            result.updated += 1

        for group in ("student", "mortgage"):
            for loan in liabilities.get(group, []) or []:
                account = accounts.get(loan.get("account_id"))
                if not account:
                    continue
                rate = loan.get("interest_rate_percentage")
                if isinstance(loan.get("interest_rate"), dict):
                    rate = loan["interest_rate"].get("percentage")
                upsert_debt_detail(
                    ctx.db,
                    account,
                    {
                        "apr": rate,
                        "minimum_payment": loan.get("minimum_payment_amount")
                        or loan.get("next_monthly_payment"),
                        "next_payment_due": _as_date(loan.get("next_payment_due_date")),
                        "original_principal": loan.get("origination_principal_amount"),
                    },
                )
                result.updated += 1

    def _sync_holdings(
        self, ctx: SyncContext, result: SyncResult, accounts: dict[str, Any]
    ) -> None:
        try:
            data = self._post(ctx, "/investments/holdings/get", {})
        except ConnectorError as exc:
            result.warnings.append(f"Investments skipped: {exc}")
            return

        securities = {s["security_id"]: s for s in data.get("securities", [])}
        for holding in data.get("holdings", []):
            account = accounts.get(holding.get("account_id"))
            if not account:
                continue
            security = securities.get(holding.get("security_id"), {})
            symbol = security.get("ticker_symbol") or security.get("name") or "UNKNOWN"
            _, created = upsert_holding(
                ctx.db,
                account_id=account.id,
                symbol=symbol[:32],
                defaults={
                    "name": security.get("name") or "",
                    "asset_class": (security.get("type") or "equity").lower(),
                    "quantity": holding.get("quantity") or 0,
                    "price": holding.get("institution_price") or 0,
                    "market_value": holding.get("institution_value") or 0,
                    "cost_basis": holding.get("cost_basis"),
                    "as_of": date.today(),
                },
            )
            result.created += int(created)
            result.updated += int(not created)


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None

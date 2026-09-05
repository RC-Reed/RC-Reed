"""Fidelity — positions and history via CSV export.

Fidelity has no public personal-investment API. The supported, no-scraping,
no-credential-sharing path is the export button:

    Fidelity.com -> Accounts & Trade -> Portfolio -> Positions -> Download
    (produces "Portfolio_Positions_<date>.csv")

Upload that file here and it becomes accounts + holdings + a net worth point.
The same connector also accepts a Fidelity "History" export to populate
transactions for a brokerage account.

If you later want this automated, Plaid covers Fidelity for balances and
holdings — see the plaid connector. This one is the zero-dependency path that
works today.
"""

from __future__ import annotations

from datetime import date

from app.connectors._csvutil import parse_date, parse_money, pick, sniff_rows
from app.connectors.base import (
    Connector,
    ConnectorCategory,
    ConnectorError,
    ConnectorField,
    ConnectorMode,
    FieldType,
    IngestPayload,
    SyncContext,
    SyncResult,
)
from app.connectors.registry import register
from app.models.finance import AccountType
from app.services.upserts import (
    record_balance,
    upsert_account,
    upsert_holding,
    upsert_transaction,
)

# Fidelity uses these for core cash / money market sweep positions.
CASH_SYMBOLS = {"SPAXX", "FDRXX", "FZFXX", "CORE", "FCASH"}


def _asset_class(symbol: str, description: str) -> str:
    symbol = symbol.upper().strip("*")
    if symbol in CASH_SYMBOLS or "MONEY MARKET" in description.upper():
        return "cash"
    if any(word in description.upper() for word in ("BOND", "TREASURY", "TIPS")):
        return "bond"
    if any(word in description.upper() for word in ("INDEX", "ETF", "FUND", "TRUST")):
        return "fund"
    return "equity"


@register
class FidelityCsvConnector(Connector):
    slug = "fidelity_csv"
    name = "Fidelity (CSV export)"
    category = ConnectorCategory.finance
    mode = ConnectorMode.push
    schedulable = False
    description = (
        "Import a Fidelity Portfolio Positions export to load investment accounts "
        "and holdings, or a History export to load transactions. No credentials "
        "leave your machine."
    )
    provides = ("accounts", "holdings", "transactions", "balances")
    docs_url = "https://www.fidelity.com/customer-service/how-to-download-account-information"
    fields = (
        ConnectorField(
            key="institution",
            label="Institution label",
            required=False,
            default="Fidelity",
            help="Shown on the accounts list.",
        ),
        ConnectorField(
            key="account_type",
            label="Account type",
            type=FieldType.select,
            required=False,
            default="investment",
            options=("investment", "depository"),
            help="Investment for brokerage/IRA/401k.",
        ),
    )

    def ingest(self, ctx: SyncContext, payload: IngestPayload) -> SyncResult:
        rows = sniff_rows(payload.text or "")
        if not rows:
            raise ConnectorError("No CSV rows found. Upload the file Fidelity generated, unmodified.")

        header_keys = " ".join(rows[0].keys()).lower()
        if "quantity" in header_keys or "current value" in header_keys:
            return self._ingest_positions(ctx, rows)
        if "amount" in header_keys or "action" in header_keys:
            return self._ingest_history(ctx, rows)
        raise ConnectorError(
            "Unrecognised Fidelity export. Expected a Positions file (has "
            "'Quantity'/'Current Value') or a History file (has 'Action'/'Amount')."
        )

    # ------------------------------------------------------------------
    def _ingest_positions(self, ctx: SyncContext, rows: list[dict[str, str]]) -> SyncResult:
        result = SyncResult()
        institution = ctx.opt("institution") or "Fidelity"
        account_type = AccountType(ctx.opt("account_type") or "investment")
        totals: dict[str, float] = {}
        seen_accounts: dict[str, object] = {}

        for row in rows:
            account_number = pick(row, "Account Number", "Account")
            symbol = pick(row, "Symbol").strip()
            if not account_number or not symbol:
                continue
            # Fidelity appends a synthetic row for unsettled activity.
            if symbol.lower().startswith("pending"):
                continue

            account_name = pick(row, "Account Name", "Account Name/Number") or account_number
            account = seen_accounts.get(account_number)
            if account is None:
                account, created = upsert_account(
                    ctx.db,
                    user_id=ctx.user_id,
                    connection_id=ctx.connection_id,
                    external_id=account_number,
                    defaults={
                        "name": account_name,
                        "institution": institution,
                        "type": account_type,
                        "subtype": "brokerage",
                        "mask": account_number[-4:],
                    },
                )
                seen_accounts[account_number] = account
                totals[account_number] = 0.0
                result.created += int(created)
                result.updated += int(not created)

            description = pick(row, "Description")
            quantity = parse_money(pick(row, "Quantity")) or 0.0
            price = parse_money(pick(row, "Last Price", "Price")) or 0.0
            value = parse_money(pick(row, "Current Value", "Value", "Market Value"))
            if value is None:
                value = quantity * price
            cost_basis = parse_money(pick(row, "Cost Basis Total", "Cost Basis"))

            totals[account_number] += value

            _, created = upsert_holding(
                ctx.db,
                account_id=account.id,
                symbol=symbol.strip("*"),
                defaults={
                    "name": description,
                    "asset_class": _asset_class(symbol, description),
                    "quantity": quantity,
                    "price": price,
                    "market_value": round(value, 2),
                    "cost_basis": cost_basis,
                    "as_of": date.today(),
                },
            )
            result.created += int(created)
            result.updated += int(not created)

        if not seen_accounts:
            raise ConnectorError("No positions found in that file.")

        for account_number, total in totals.items():
            account = seen_accounts[account_number]
            account.current_balance = round(total, 2)
            record_balance(ctx.db, account)

        result.message = (
            f"Imported {len(seen_accounts)} account(s), "
            f"${sum(totals.values()):,.2f} total value"
        )
        return result

    # ------------------------------------------------------------------
    def _ingest_history(self, ctx: SyncContext, rows: list[dict[str, str]]) -> SyncResult:
        result = SyncResult()
        institution = ctx.opt("institution") or "Fidelity"
        cache: dict[str, object] = {}

        for index, row in enumerate(rows):
            account_number = pick(row, "Account Number", "Account")
            posted = parse_date(pick(row, "Run Date", "Date", "Settlement Date"))
            amount = parse_money(pick(row, "Amount", "Amount ($)"))
            if not account_number or posted is None or amount is None:
                continue

            account = cache.get(account_number)
            if account is None:
                account, created = upsert_account(
                    ctx.db,
                    user_id=ctx.user_id,
                    connection_id=ctx.connection_id,
                    external_id=account_number,
                    defaults={
                        "name": pick(row, "Account Name") or account_number,
                        "institution": institution,
                        "type": AccountType.investment,
                        "mask": account_number[-4:],
                    },
                )
                cache[account_number] = account
                result.created += int(created)

            action = pick(row, "Action", "Description") or "Activity"
            # History exports have no stable row id, so derive a deterministic
            # one; a re-import of the same file updates instead of duplicating.
            external_id = f"{posted.isoformat()}|{amount:.2f}|{action[:60]}|{index}"
            _, created = upsert_transaction(
                ctx.db,
                user_id=ctx.user_id,
                account_id=account.id,
                external_id=external_id,
                defaults={
                    "posted_on": posted,
                    "amount": amount,
                    "description": action,
                    "category": "investment",
                    "is_transfer": "TRANSFER" in action.upper(),
                },
            )
            result.created += int(created)
            result.updated += int(not created)

        result.message = f"Imported {result.total} history row(s)"
        return result

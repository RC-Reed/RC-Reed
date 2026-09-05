"""Generic bank / credit-card CSV import.

Every bank exports a slightly different CSV. Rather than write one connector
per bank, this one is configured with the column names and the sign
convention, so a new institution is a form, not a code change.
"""

from __future__ import annotations

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
from app.services.upserts import record_balance, upsert_account, upsert_transaction

TRANSFER_HINTS = ("transfer", "payment thank you", "autopay", "online payment", "xfer")


def _categorize(description: str) -> str:
    """A small, readable first pass. Rules beat a model you can't debug."""
    text = description.lower()
    buckets = {
        "groceries": ("grocery", "market", "aldi", "wegmans", "kroger", "safeway", "publix", "trader joe"),
        "dining": ("restaurant", "coffee", "starbucks", "chipotle", "doordash", "grubhub", "uber eats", "pizza"),
        "transport": ("uber", "lyft", "shell", "exxon", "chevron", "bp ", "parking", "transit", "toll"),
        "utilities": ("electric", "water", "gas co", "internet", "comcast", "verizon", "at&t", "t-mobile"),
        "housing": ("rent", "mortgage", "hoa", "property"),
        "insurance": ("insurance", "geico", "progressive", "allstate"),
        "subscriptions": ("netflix", "spotify", "hulu", "prime", "adobe", "github", "openai", "icloud", "youtube"),
        "health": ("pharmacy", "cvs", "walgreens", "dental", "medical", "clinic", "gym", "fitness"),
        "income": ("payroll", "direct dep", "deposit", "salary"),
        "debt": ("loan", "student", "card payment"),
    }
    for category, needles in buckets.items():
        if any(needle in text for needle in needles):
            return category
    return "uncategorized"


@register
class BankCsvConnector(Connector):
    slug = "bank_csv"
    name = "Bank / Card CSV"
    category = ConnectorCategory.finance
    mode = ConnectorMode.push
    schedulable = False
    description = (
        "Import transactions from any bank or credit-card CSV export by telling "
        "it which columns to read. Feeds spending, categories and the recurring-"
        "charge detector."
    )
    provides = ("accounts", "transactions")
    fields = (
        ConnectorField(key="account_name", label="Account name", default="Checking"),
        ConnectorField(key="institution", label="Institution", required=False, default=""),
        ConnectorField(
            key="account_type",
            label="Account type",
            type=FieldType.select,
            default="depository",
            options=("depository", "credit", "loan"),
        ),
        ConnectorField(
            key="date_column", label="Date column", default="Date", help="Header text, case-insensitive."
        ),
        ConnectorField(key="description_column", label="Description column", default="Description"),
        ConnectorField(
            key="amount_column",
            label="Amount column",
            default="Amount",
            help="Leave as-is if the file uses separate Debit/Credit columns.",
        ),
        ConnectorField(key="debit_column", label="Debit column", required=False, default="Debit"),
        ConnectorField(key="credit_column", label="Credit column", required=False, default="Credit"),
        ConnectorField(
            key="flip_sign",
            label="File lists spending as positive",
            type=FieldType.checkbox,
            required=False,
            default=False,
            help="Most credit-card exports do. Life OS always stores spending as negative.",
        ),
        ConnectorField(
            key="date_format",
            label="Date format",
            required=False,
            default="",
            help="Optional strptime format, e.g. %m/%d/%Y. Auto-detected when blank.",
        ),
    )

    def ingest(self, ctx: SyncContext, payload: IngestPayload) -> SyncResult:
        rows = sniff_rows(payload.text or "")
        if not rows:
            raise ConnectorError("No rows found in that CSV.")

        account, created = upsert_account(
            ctx.db,
            user_id=ctx.user_id,
            connection_id=ctx.connection_id,
            external_id=ctx.opt("account_name", "csv-account"),
            defaults={
                "name": ctx.opt("account_name") or "Imported account",
                "institution": ctx.opt("institution") or "",
                "type": AccountType(ctx.opt("account_type") or "depository"),
            },
        )
        result = SyncResult(created=int(created))

        date_col = ctx.opt("date_column") or "Date"
        desc_col = ctx.opt("description_column") or "Description"
        amount_col = ctx.opt("amount_column") or "Amount"
        debit_col = ctx.opt("debit_column") or ""
        credit_col = ctx.opt("credit_column") or ""
        flip = bool(ctx.opt("flip_sign"))
        date_format = ctx.opt("date_format") or ""

        skipped = 0
        running_total = 0.0
        for index, row in enumerate(rows):
            posted = parse_date(pick(row, date_col, "Date", "Transaction Date", "Posted Date"), date_format)
            description = pick(row, desc_col, "Description", "Payee", "Memo", "Name")
            amount = parse_money(pick(row, amount_col, "Amount"))

            if amount is None and (debit_col or credit_col):
                debit = parse_money(pick(row, debit_col)) or 0.0
                credit = parse_money(pick(row, credit_col)) or 0.0
                amount = credit - abs(debit)

            if posted is None or amount is None:
                skipped += 1
                continue
            if flip:
                amount = -amount

            running_total += amount
            _, created_txn = upsert_transaction(
                ctx.db,
                user_id=ctx.user_id,
                account_id=account.id,
                external_id=f"{posted.isoformat()}|{amount:.2f}|{description[:60]}|{index}",
                defaults={
                    "posted_on": posted,
                    "amount": amount,
                    "description": description,
                    "category": _categorize(description),
                    "is_transfer": any(hint in description.lower() for hint in TRANSFER_HINTS),
                },
            )
            result.created += int(created_txn)
            result.updated += int(not created_txn)

        record_balance(ctx.db, account)
        if skipped:
            result.warnings.append(
                f"{skipped} row(s) skipped — check the date and amount column names."
            )
        result.message = f"Imported {result.total} transaction(s) into {account.name}"
        return result

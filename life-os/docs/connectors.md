# Writing a connector

A connector is one class. Everything else — the setup form, the scheduler, the
sync log, the manual "Sync now" button, the file upload — is driven from its
metadata, so you never touch the API or the UI to add an integration.

## The contract

```python
class Connector:
    slug: str                  # unique id, e.g. "monarch"
    name: str                  # shown in the catalogue
    category: ConnectorCategory  # finance | health | productivity | work | other
    mode: ConnectorMode        # pull | push | both
    description: str           # one or two sentences, shown on the card
    provides: tuple[str, ...]  # "accounts", "transactions", "health_metrics", ...
    fields: tuple[ConnectorField, ...]   # the setup form
    schedulable: bool = True   # False for anything needing a human or a file

    def sync(self, ctx) -> SyncResult:            # pull connectors
    def ingest(self, ctx, payload) -> SyncResult: # push connectors
```

**Pull** means Life OS reaches out on a schedule (Plaid, an ICS feed, GitHub) —
implement `sync()`. **Push** means the outside world sends data in (an iPhone
automation, a CSV you export) — implement `ingest()`. A connector may do both.

`fields` marked `secret=True` are encrypted at rest and never returned to the
browser. Everything else is stored in the clear so it stays queryable and
debuggable.

## A complete example

Say you want to track a savings goal from a bank that publishes a JSON endpoint.
Create `api/app/connectors/savings_goal.py`:

```python
from datetime import date

import httpx

from app.connectors.base import (
    Connector, ConnectorCategory, ConnectorError, ConnectorField,
    ConnectorMode, FieldType, SyncContext, SyncResult,
)
from app.connectors.registry import register
from app.models.finance import AccountType
from app.services.upserts import record_balance, upsert_account


@register
class SavingsGoalConnector(Connector):
    slug = "savings_goal"
    name = "Savings Goal"
    category = ConnectorCategory.finance
    mode = ConnectorMode.pull
    description = "Pulls a savings balance from a JSON endpoint."
    provides = ("accounts", "balances")
    fields = (
        ConnectorField(key="url", label="Endpoint URL", type=FieldType.url),
        ConnectorField(key="api_key", label="API key",
                       type=FieldType.password, secret=True),
        ConnectorField(key="account_name", label="Account name",
                       required=False, default="Savings Goal"),
    )

    def sync(self, ctx: SyncContext) -> SyncResult:
        try:
            response = httpx.get(
                ctx.opt("url"),
                headers={"Authorization": f"Bearer {ctx.secrets['api_key']}"},
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # ConnectorError becomes a clean failed SyncRun with your message,
            # not a stack trace in the log.
            raise ConnectorError(f"Could not reach the endpoint: {exc}") from exc

        payload = response.json()
        account, created = upsert_account(
            ctx.db,
            user_id=ctx.user_id,
            connection_id=ctx.connection_id,
            external_id="savings-goal",       # stable → re-syncs update
            defaults={
                "name": ctx.opt("account_name") or "Savings Goal",
                "type": AccountType.depository,
                "current_balance": payload["balance"],
            },
        )
        record_balance(ctx.db, account, date.today())

        return SyncResult(
            created=int(created),
            updated=int(not created),
            message=f"Balance ${payload['balance']:,.2f}",
        )
```

Register the module in `app/connectors/registry.py`:

```python
_MODULES = (
    ...
    "app.connectors.savings_goal",
)
```

That's it. Restart the API and it appears in the catalogue with a working setup
form, a schedule, a sync button and a run history.

## Rules that keep syncs honest

**Always write through `services/upserts.py`.** Those helpers key on
`(source, external_id)` and return whether a row was *inserted*. Going around
them means a re-sync duplicates data and the sync log lies about what happened.

**Give every record a stable `external_id`.** If the provider has one, use it.
If it doesn't (Fidelity's history export), derive one deterministically from the
row's own contents so re-importing the same file updates in place:

```python
external_id = f"{posted.isoformat()}|{amount:.2f}|{description[:60]}|{index}"
```

**Normalise at the edge.** Convert to the internal conventions before writing:
spending negative, liabilities positive-owed, weight in pounds, sleep in
minutes. Downstream code should never need to know where a number came from.

**Raise `ConnectorError` for anything expected.** Bad credentials, a malformed
file, a provider outage. It produces a failed `SyncRun` carrying your message,
which is what the user sees on the Connections page. Unexpected exceptions are
caught too, but they read like bugs — because they are.

**Degrade partially rather than failing whole.** If one optional call fails
(say your Plaid plan lacks investments), append to `result.warnings` and carry
on. The run is recorded as `partial`, and the data you *did* get is kept.

**Persist cursors in `ctx.state`.** It's a dict the sync runner saves back onto
the connection after a successful run. Use it for incremental pulls:

```python
cursor = ctx.state.get("transactions_cursor")
...
ctx.state["transactions_cursor"] = data["next_cursor"]
```

Never write to the `Connection` row yourself.

## Testing one

Connectors are plain objects — no HTTP, no database fixtures beyond a session:

```python
def test_my_connector(db, user, fixture_text):
    ctx = SyncContext(db=db, user_id=user.id, connection_id=None,
                      config={"account_name": "Test"}, secrets={}, state={})
    result = get_connector("my_slug").ingest(
        ctx, IngestPayload(text=fixture_text("my_export.csv"))
    )
    db.commit()
    assert result.created == 5
```

Put a realistic export in `api/tests/fixtures/` — one with the provider's actual
quirks (currency symbols, a footer, a "Pending Activity" row). The existing
fixtures were built that way, and each one caught a bug.

Always add an idempotency test. Run the ingest twice and assert the second run
creates nothing:

```python
def test_reimport_is_idempotent(db, user, fixture_text):
    ...
    second = connector.ingest(ctx, payload)
    assert second.created == 0
```

## Built-in connectors

| Slug | Mode | Provides |
|---|---|---|
| `manual` | pull | accounts, balances |
| `bank_csv` | push | accounts, transactions |
| `fidelity_csv` | push | accounts, holdings, transactions, balances |
| `plaid` | pull | accounts, balances, transactions, holdings, debt |
| `apple_health` | push | health metrics, workouts |
| `ics_calendar` | pull | tasks |
| `github_work` | pull | tasks |

## Notes on the harder providers

**Fidelity** has no public personal-investment API. The supported path is the
export button (Portfolio → Positions → Download), which is what `fidelity_csv`
parses — no credential sharing, no scraping, no terms-of-service problem. Plaid
also covers Fidelity for balances and holdings if you want it automated.

**Apple Health** deliberately keeps data on the device; there is no server-side
API to call. So the flow is push: the Health Auto Export app (or a Shortcuts
automation) POSTs JSON to your ingest endpoint on a schedule. Your phone talks
to your server directly. For history, the Health app's "Export All Health Data"
produces an `export.xml` you upload once.

**Plaid** needs an access token for an already-linked Item. Life OS doesn't host
Plaid Link, because that would mean standing up a public callback — run Plaid's
Quickstart locally once and paste the resulting token in.

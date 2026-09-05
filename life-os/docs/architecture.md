# Architecture

## The shape of it

```
   iPhone ──push──┐
   CSV export ────┤
   Plaid ─────────┤        ┌──────────────┐      ┌───────────┐
   ICS feed ──────┼─pull──▶│  Connectors  │─────▶│  Upserts  │──┐
   GitHub ────────┘        └──────────────┘      └───────────┘  │
                                  ▲                             ▼
                           ┌──────┴───────┐              ┌────────────┐
                           │  Sync runner │              │  Postgres  │
                           │  + scheduler │              │  / SQLite  │
                           └──────────────┘              └─────┬──────┘
                                                               │
                    ┌──────────────────────────────────────────┤
                    ▼                    ▼                     ▼
              ┌──────────┐        ┌────────────┐        ┌────────────┐
              │ Analytics│        │   Debt     │        │  Insights  │
              │ net worth│        │  payoff    │        │   rules    │
              │ cash flow│        │ simulation │        │   engine   │
              └────┬─────┘        └─────┬──────┘        └─────┬──────┘
                   └────────────────────┴─────────────────────┘
                                        │
                                  FastAPI routes
                                        │
                                  React dashboard
```

## Principles

**Normalise at the edge.** Connectors translate whatever the provider gives
them into one internal vocabulary, then write through `services/upserts.py`.
Once data is in the database, nothing downstream knows or cares whether a
balance came from Plaid, a CSV, or a number typed in by hand. Adding a provider
never changes analytics code.

**One convention per concept, enforced at the boundary.**
- Transaction amounts are **signed**: positive is money in, negative is money
  out. Plaid reports outflow as positive, so the connector flips it once, at
  the edge. Nothing downstream has to remember a special case.
- Liability balances are stored as the **positive amount owed** (that's how
  every provider reports them) and flipped by `Account.signed_balance` when
  contributing to net worth.
- Money is `Numeric(18,2)` in the database — never float — and converted to
  float only at the JSON boundary, where there is no decimal type anyway.

**Idempotency is not optional.** Every write goes through an upsert keyed on
`(source, external_id)`. Re-running a sync, or re-uploading the same CSV,
updates rather than duplicates. Providers that give no stable id (Fidelity's
history export) get a deterministic one derived from the row's own contents.

**The audit trail is part of the product.** Every sync attempt writes a
`SyncRun` — what ran, what it wrote, why it failed. Every connection change
writes an `AuditEvent`. When a number looks wrong six months from now, the
question "where did this come from and when" has an answer.

**Rules over models.** The insight engine is a list of small functions. You can
read one, disagree with its threshold, and change it. A model you can't debug
has no place deciding whether to tell you a bill is late.

## Data model

| Table | Holds | Notes |
|---|---|---|
| `accounts` | every account, asset or liability | `type` decides which side of net worth |
| `balance_snapshots` | one balance per account per day | the raw material for net worth history |
| `transactions` | signed amounts | `is_transfer` keeps internal moves out of income/spending |
| `holdings` | investment positions | one row per symbol per account |
| `debt_details` | APR, minimum, due date | separate from `accounts` because most accounts don't need it |
| `bills` | anything recurring with a due date | `auto_detected` + `confidence` mark detector output |
| `tasks` / `projects` | todos and work items | `connection_id` + `external_id` when a connector owns one |
| `health_metrics` | one value per metric per day per source | long/narrow, so a new metric needs no migration |
| `workouts` | activity sessions | |
| `connections` | configured connector instances | secrets in a single encrypted blob |
| `sync_runs` | every sync attempt | |
| `insights` | rules-engine output | `dedupe_key` makes refresh idempotent |
| `audit_events` | who did what | |

### Why health metrics are long, not wide

A wide table (`date, steps, sleep, weight, …`) needs a migration every time a
device starts reporting something new. Long/narrow — one row per
`(metric, day, source)` — means a new metric is just new rows. The unique
constraint on that triple is what makes re-importing an Apple Health export
update rather than multiply.

### Why balance history carries forward

Snapshots are sparse: a connector only writes on the days it syncs. If net
worth summed only the snapshots that exist for a given day, a day when just the
checking account synced would show every other account at zero. So
`net_worth_history` carries each account's last known balance forward.

## Request and sync flow

**Read path.** `GET /dashboard` returns everything the front page renders in
one response. A personal dashboard is read constantly and written rarely; one
wide query beats a dozen round trips.

**Sync path.** `services/sync.py` owns the whole lifecycle — open a `SyncRun`,
decrypt credentials, build a `SyncContext`, call the connector, persist its
cursor state, close the run. Connectors never touch `Connection` rows or write
their own logs, which is why they stay short.

**Scheduler.** APScheduler in-process, one job: sync everything due, roll bill
due dates forward, refresh insights. Not Celery — a personal system shouldn't
need three daemons to tell you a bill is due. If you outgrow it, `run_due_syncs()`
is the entire contract; point a real queue or an external cron at it
(`POST /api/v1/system/run-sync-tick`) and delete the file.

## Schema changes

`init_db()` calls `create_all()`, which is additive only — it creates missing
tables and never alters or drops. That is the right trade while the schema is
still moving and there's one operator.

Once you're storing data you'd be upset to lose, add Alembic:

```bash
cd api && ../.venv/bin/alembic init migrations
# point migrations/env.py at app.models.base:Base.metadata
```

and replace the `create_all()` call in `app/db.py` with `alembic upgrade head`.
The models are already written in the 2.0 typed style Alembic autogenerates
cleanly from.

## Frontend

React + TypeScript + Vite + Tailwind, one page per domain. Data fetching is a
small `useApi` hook — deliberately not a cache layer, because the screens are
small and a refetch is cheaper than reasoning about staleness.

Charts follow a fixed set of rules: one y-axis per chart (never dual), a
legend whenever two or more series share a plot, recessive grid and axes, and a
hover tooltip on everything plotted. Series colors live in CSS custom
properties (`--series-1` … `--series-4`) defined once in `src/index.css`; the
chosen values are validated as colorblind-separable against the dark surface,
so changing the palette means editing those four lines and re-checking, not
hunting through components.

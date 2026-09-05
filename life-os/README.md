# Life OS

A self-hosted system of record for the things you'd otherwise track in six
different apps: money, debt, investments, bills, subscriptions, tasks, work and
health. It runs on your own hardware, holds your own credentials, and is built
so that adding the *next* thing you want to track is a small, obvious change.

Nothing leaves your network except the calls you explicitly configure a
connector to make.

---

## What it actually does

**Money.** Accounts, balances and transactions from banks, cards and loans —
imported from CSV or synced automatically through Plaid. Net worth is tracked
daily, so you get a real history instead of a single number.

**Debt.** APR, minimum payment and due date per account, then a month-by-month
payoff simulation. Avalanche vs snowball side by side, with a slider for extra
payment so you can see what an extra $200/month is actually worth in interest
and in months.

**Investments.** Positions, cost basis and allocation across every brokerage
and retirement account. Fidelity works today through its CSV export — no
credential sharing, no scraping — and through Plaid if you want it automated.

**Bills & subscriptions.** Anything with a due date and a cadence. The part
that earns its keep is the detector: it finds recurring charges in your
transactions on its own, so you don't have to remember that you're still paying
for something. Utilities and insurance are classified as fixed bills, not
subscriptions, so "subscriptions cost you $X/year" means money you could
actually stop spending.

**Tasks & work.** Todos with areas, projects, priorities and due dates, plus
work items pulled in from GitHub and events from any calendar's ICS feed.

**Health.** Steps, sleep, resting heart rate, HRV, weight, workouts — pushed
from your iPhone by the Health Auto Export app or a Shortcuts automation, with
an `export.xml` upload for backfilling years of history in one shot.

**Insights.** A rules engine runs after every sync and surfaces the short list
worth acting on: a bill about to be late, cash that won't cover the next two
weeks, a card past 30% utilization, spending in a category tracking well above
its own average, a connection that has quietly stopped working.

---

## Quick start

### Local, no Docker

```bash
cd life-os
make setup                                   # venv + npm install
make seed EMAIL=you@example.com PASSWORD='a-long-password'   # add --demo data
make api                                     # terminal 1 → :8000
make web                                     # terminal 2 → :5173
```

Open http://localhost:5173. SQLite is the default, so there is nothing else to
install.

### Docker

```bash
cd life-os
cp .env.example .env        # fill in the passwords and keys
docker compose up -d --build
docker compose exec api python -m app.seed --email you@example.com --password '...'
```

Open http://localhost:8080. This runs Postgres, the API and an nginx-served
frontend. **Put a TLS-terminating reverse proxy in front of it before it leaves
your LAN** — see `docs/security.md`.

---

## Connecting your real data

| What you want | How |
|---|---|
| Bank / credit card transactions | Export CSV → **Bank / Card CSV** connector, or Plaid for automatic sync |
| Fidelity holdings | Fidelity → Portfolio → Positions → Download → **Fidelity (CSV export)** |
| Debt terms (APR, minimums) | Debt page, per account — or automatically via Plaid liabilities |
| Apple Health | Add the **Apple Health** connector, then point [Health Auto Export](https://github.com/Lybron/health-auto-export) at the ingest URL shown on the Connections page |
| Calendar | Google/Outlook/iCloud secret ICS URL → **Calendar (ICS feed)** |
| Work items | GitHub personal access token → **GitHub issues & PRs** |
| Anything without an API | **Manual Entry** — still gets daily balance history |

Subscriptions don't need connecting. Import a few months of transactions and
press **Detect recurring**.

---

## Adding your own feature

That's the point of the design. Two starting places:

- **A new data source** → write one connector class. Nothing else changes: the
  API, the scheduler and the setup UI are all driven from the connector's own
  metadata. Worked example in [`docs/connectors.md`](docs/connectors.md).
- **A new thing to notice** → append a function to `RULES` in
  `api/app/services/insights.py`. It shows up on the dashboard automatically.

See [`docs/architecture.md`](docs/architecture.md) for how the pieces fit and
[`docs/roadmap.md`](docs/roadmap.md) for what's deliberately not built yet.

---

## Layout

```
life-os/
├── api/                    FastAPI backend
│   ├── app/
│   │   ├── models/         SQLAlchemy schema
│   │   ├── connectors/     one file per integration
│   │   ├── services/       sync, analytics, debt, bills, insights, scheduler
│   │   ├── api/routes/     HTTP layer
│   │   ├── security.py     hashing, JWT, encrypted credential vault
│   │   └── seed.py         first account + realistic demo data
│   └── tests/              59 tests, incl. real export fixtures
├── web/                    React + TypeScript + Tailwind dashboard
├── docs/
└── docker-compose.yml
```

## Tests

```bash
cd life-os && make test        # API
make typecheck                 # frontend
```

The suite covers the payoff maths, the recurring detector's false-positive
behaviour, every importer against realistic export fixtures, credential
encryption, and cross-user access isolation.

## License

Personal project — use it however you like.

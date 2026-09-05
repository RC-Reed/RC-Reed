"""Bootstrap and demo data.

    python -m app.seed --email you@example.com --password '...'      # account only
    python -m app.seed --email you@example.com --password '...' --demo  # + sample data

The demo data is synthetic but shaped like the real thing: a year of
transactions with genuine recurring charges, so the detector, the insight
rules and the payoff planner all have something true to chew on.
"""

from __future__ import annotations

import argparse
import random
from datetime import date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from app.db import init_db, session_scope
from app.models.bills import Bill, Cadence
from app.models.connections import Connection, ConnectionStatus
from app.models.finance import (
    Account,
    AccountType,
    BalanceSnapshot,
    DebtDetail,
    Holding,
    Transaction,
)
from app.models.health import HealthMetric, Workout
from app.models.tasks import Area, Project, Task, TaskStatus
from app.models.user import User
from app.security import hash_password
from app.services import insights as insights_service
from app.services.bills import detect_recurring
from app.services.upserts import normalize_merchant, record_balance

# (merchant, amount, day-of-month, is_subscription)
RECURRING = [
    ("NETFLIX.COM", 22.99, 4, True),
    ("SPOTIFY USA", 11.99, 9, True),
    ("GITHUB INC", 4.00, 14, True),
    ("ADOBE CREATIVE CLOUD", 59.99, 18, True),
    ("PLANET FITNESS", 24.99, 17, True),
    ("VERIZON WIRELESS", 92.41, 22, False),
    ("PSE&G UTILITY", 148.72, 12, False),
    ("STATE FARM INSURANCE", 137.50, 6, False),
    ("APPLE ICLOUD STORAGE", 9.99, 25, True),
    ("PROGRESSIVE RENTERS", 18.00, 28, True),
]

ONE_OFF = [
    ("WEGMANS FOOD MARKET", 45, 160, "groceries"),
    ("SHELL OIL 574823", 32, 78, "transport"),
    ("CHIPOTLE 2841", 11, 24, "dining"),
    ("AMAZON.COM*RT4G9", 15, 190, "shopping"),
    ("STARBUCKS STORE 8821", 5, 12, "dining"),
    ("CVS PHARMACY #4417", 8, 65, "health"),
    ("HOME DEPOT 6612", 25, 240, "home"),
]


def ensure_user(db, email: str, password: str, display_name: str) -> User:
    user = db.scalars(select(User).where(User.email == email.lower())).first()
    if user:
        print(f"user already exists: {email}")
        return user
    user = User(
        email=email.lower(),
        hashed_password=hash_password(password),
        display_name=display_name or email.split("@")[0],
    )
    db.add(user)
    db.flush()
    print(f"created user: {email}")
    return user


def seed_demo(db, user: User) -> None:
    if db.scalars(select(Account).where(Account.user_id == user.id)).first():
        print("demo data already present — skipping")
        return

    rng = random.Random(20260905)
    today = date.today()

    manual_conn = Connection(
        user_id=user.id,
        connector_slug="manual",
        display_name="Manual Entry",
        status=ConnectionStatus.active,
        config={},
    )
    db.add(manual_conn)
    db.flush()

    # --- accounts ---------------------------------------------------------
    checking = Account(
        user_id=user.id, name="Everyday Checking", institution="Local Credit Union",
        type=AccountType.depository, subtype="checking", mask="4417",
        current_balance=4820.15, available_balance=4720.15, connection_id=manual_conn.id,
    )
    savings = Account(
        user_id=user.id, name="Emergency Fund", institution="Local Credit Union",
        type=AccountType.depository, subtype="savings", mask="9902",
        current_balance=11250.00, connection_id=manual_conn.id,
    )
    card = Account(
        user_id=user.id, name="Rewards Visa", institution="Chase",
        type=AccountType.credit, subtype="credit card", mask="1188",
        current_balance=3145.60, credit_limit=9000.00, connection_id=manual_conn.id,
    )
    auto = Account(
        user_id=user.id, name="Auto Loan", institution="Capital One",
        type=AccountType.loan, subtype="auto", mask="2210",
        current_balance=12480.00, connection_id=manual_conn.id,
    )
    student = Account(
        user_id=user.id, name="Student Loan", institution="Nelnet",
        type=AccountType.loan, subtype="student", mask="7734",
        current_balance=18900.00, connection_id=manual_conn.id,
    )
    brokerage = Account(
        user_id=user.id, name="Fidelity Individual", institution="Fidelity",
        type=AccountType.investment, subtype="brokerage", mask="8820",
        current_balance=0, connection_id=manual_conn.id,
    )
    ira = Account(
        user_id=user.id, name="Fidelity Roth IRA", institution="Fidelity",
        type=AccountType.investment, subtype="ira", mask="5561",
        current_balance=0, connection_id=manual_conn.id,
    )
    accounts = [checking, savings, card, auto, student, brokerage, ira]
    db.add_all(accounts)
    db.flush()

    db.add_all([
        DebtDetail(account_id=card.id, apr=23.99, minimum_payment=95.00,
                   statement_balance=3145.60, next_payment_due=today + timedelta(days=9)),
        DebtDetail(account_id=auto.id, apr=6.49, minimum_payment=389.00,
                   next_payment_due=today + timedelta(days=16), original_principal=27000, term_months=72),
        DebtDetail(account_id=student.id, apr=5.05, minimum_payment=210.00,
                   next_payment_due=today + timedelta(days=3), original_principal=32000, term_months=120),
    ])

    # --- holdings ---------------------------------------------------------
    positions = [
        (brokerage, "FXAIX", "Fidelity 500 Index Fund", "fund", 82.451, 191.34, 12100.00),
        (brokerage, "VTI", "Vanguard Total Stock Market ETF", "fund", 41.0, 288.12, 9400.00),
        (brokerage, "NVDA", "NVIDIA Corp", "equity", 18.0, 172.40, 2210.00),
        (brokerage, "SPAXX", "Fidelity Government Money Market", "cash", 3184.22, 1.00, 3184.22),
        (ira, "FZROX", "Fidelity ZERO Total Market Index", "fund", 410.9, 19.88, 6900.00),
        (ira, "FXNAX", "Fidelity US Bond Index", "bond", 190.0, 10.42, 2050.00),
    ]
    for account, symbol, name, asset_class, quantity, price, cost in positions:
        db.add(Holding(
            account_id=account.id, symbol=symbol, name=name, asset_class=asset_class,
            quantity=quantity, price=price, market_value=round(quantity * price, 2),
            cost_basis=cost, as_of=today,
        ))
    db.flush()
    for account in (brokerage, ira):
        total = sum(
            float(h.market_value)
            for h in db.scalars(select(Holding).where(Holding.account_id == account.id)).all()
        )
        account.current_balance = round(total, 2)

    # --- transactions: 12 months ------------------------------------------
    start = today - timedelta(days=365)
    txn_count = 0
    # Step by calendar month, not 30 days — otherwise two iterations land in
    # the same month and collide on the generated external ids.
    for month_offset in range(13):
        anchor = start.replace(day=1) + relativedelta(months=month_offset)

        for merchant, amount, day, _is_sub in RECURRING:
            try:
                when = anchor.replace(day=day)
            except ValueError:
                continue
            if when > today or when < start:
                continue
            jitter = round(rng.uniform(-0.4, 0.4), 2) if amount > 40 else 0.0
            db.add(Transaction(
                user_id=user.id, account_id=card.id,
                external_id=f"seed-{merchant}-{when.isoformat()}",
                posted_on=when, amount=-(amount + jitter), description=f"{merchant} {when:%m/%d}",
                merchant=normalize_merchant(merchant),
                category="subscriptions" if _is_sub else "bills",
            ))
            txn_count += 1

        # Paycheck twice a month.
        for day in (15, 28):
            try:
                when = anchor.replace(day=day)
            except ValueError:
                continue
            if when > today or when < start:
                continue
            db.add(Transaction(
                user_id=user.id, account_id=checking.id,
                external_id=f"seed-pay-{when.isoformat()}",
                posted_on=when, amount=2740.18, description="ACME CORP PAYROLL DIRECT DEP",
                merchant="payroll", category="income",
            ))
            txn_count += 1

        for merchant, low, high, category in ONE_OFF:
            for _ in range(rng.randint(1, 5)):
                offset = rng.randint(0, 27)
                when = anchor + timedelta(days=offset)
                if when > today or when < start:
                    continue
                db.add(Transaction(
                    user_id=user.id, account_id=card.id,
                    external_id=f"seed-{merchant}-{when.isoformat()}-{rng.random():.6f}",
                    posted_on=when, amount=-round(rng.uniform(low, high), 2),
                    description=f"{merchant} {when:%m/%d}",
                    merchant=normalize_merchant(merchant), category=category,
                ))
                txn_count += 1

    # --- balance history --------------------------------------------------
    for account in accounts:
        balance = float(account.current_balance)
        # Walk backwards from today: assets were smaller, debts were larger.
        for days_back in range(3, 181, 3):
            when = today - timedelta(days=days_back)
            drift = 1 + (days_back / 180) * (0.11 if account.type == AccountType.investment else 0.04)
            historical = balance * (drift if account.is_liability else 1 / drift)
            db.add(BalanceSnapshot(
                account_id=account.id, as_of=when, balance=round(historical, 2)
            ))
        record_balance(db, account)

    # --- bills you'd enter by hand ---------------------------------------
    db.add_all([
        Bill(user_id=user.id, name="Rent", amount=1850.00, cadence=Cadence.monthly,
             next_due_on=today.replace(day=1) + timedelta(days=32), category="housing",
             merchant="rent", autopay=True),
        Bill(user_id=user.id, name="Car Insurance", amount=137.50, cadence=Cadence.monthly,
             next_due_on=today + timedelta(days=6), category="insurance", merchant="state farm insurance"),
        Bill(user_id=user.id, name="Domain renewals", amount=64.00, cadence=Cadence.annual,
             next_due_on=today + timedelta(days=88), category="bills", is_subscription=True),
    ])

    # --- tasks ------------------------------------------------------------
    work = Project(user_id=user.id, name="Work", area=Area.work, color="#0ea5e9")
    home = Project(user_id=user.id, name="Home & Admin", area=Area.home, color="#f59e0b")
    lab = Project(user_id=user.id, name="Home Lab", area=Area.learning, color="#8b5cf6")
    db.add_all([work, home, lab])
    db.flush()

    now = datetime.now(timezone.utc)
    task_specs = [
        ("Review Q4 access recertification", work, Area.work, 1, -1),
        ("Close out incident INC0294412", work, Area.work, 2, 0),
        ("Draft runbook for AD account lockouts", work, Area.work, 3, 3),
        ("Refinance quote on the auto loan", home, Area.finance, 2, 5),
        ("Cancel unused subscriptions", home, Area.finance, 2, 2),
        ("Rebuild pfSense VM", lab, Area.learning, 4, 12),
        ("Schedule annual physical", home, Area.health, 3, 8),
        ("File the HSA receipt", home, Area.finance, 4, None),
    ]
    for title, project, area, priority, due_offset in task_specs:
        db.add(Task(
            user_id=user.id, project_id=project.id, title=title, area=area, priority=priority,
            status=TaskStatus.todo,
            due_at=now + timedelta(days=due_offset) if due_offset is not None else None,
        ))
    db.add(Task(
        user_id=user.id, project_id=work.id, title="Submit timesheet", area=Area.work,
        priority=2, status=TaskStatus.done, completed_at=now - timedelta(days=1),
    ))

    # --- health: 120 days --------------------------------------------------
    for days_back in range(120):
        when = today - timedelta(days=days_back)
        weekday = when.weekday()
        base_steps = 9200 if weekday < 5 else 6400
        db.add_all([
            HealthMetric(user_id=user.id, metric="steps", value=max(1200, int(rng.gauss(base_steps, 2200))),
                         unit="count", recorded_on=when, source="apple_health"),
            HealthMetric(user_id=user.id, metric="sleep_duration", value=round(rng.gauss(418, 42), 1),
                         unit="min", recorded_on=when, source="apple_health"),
            HealthMetric(user_id=user.id, metric="resting_heart_rate", value=round(rng.gauss(58, 3), 1),
                         unit="bpm", recorded_on=when, source="apple_health"),
            HealthMetric(user_id=user.id, metric="exercise_minutes", value=max(0, round(rng.gauss(28, 18))),
                         unit="min", recorded_on=when, source="apple_health"),
            HealthMetric(user_id=user.id, metric="weight", value=round(182 - days_back * 0.02 + rng.gauss(0, 0.6), 1),
                         unit="lb", recorded_on=when, source="apple_health"),
        ])

    # --- workouts ---------------------------------------------------------
    activities = [
        ("Running", 32, 3.1, 385, 152),
        ("Strength Training", 45, None, 310, 121),
        ("Cycling", 55, 12.4, 520, 138),
        ("Walking", 28, 1.6, 130, 98),
    ]
    for week in range(10):
        for index, (activity, minutes, miles, kcal, heart_rate) in enumerate(activities):
            when = today - timedelta(days=week * 7 + index * 2)
            if when > today:
                continue
            db.add(Workout(
                user_id=user.id,
                external_id=f"seed-workout-{when.isoformat()}-{activity}",
                activity=activity,
                started_at=datetime.combine(when, datetime.min.time().replace(hour=6, minute=30)),
                duration_minutes=round(minutes + rng.uniform(-6, 6), 1),
                distance_miles=round(miles + rng.uniform(-0.4, 0.4), 2) if miles else None,
                energy_kcal=round(kcal + rng.uniform(-40, 40)),
                avg_heart_rate=round(heart_rate + rng.uniform(-6, 6)),
                source="apple_health",
            ))

    db.flush()
    print(f"seeded {len(accounts)} accounts, {txn_count} transactions, 120 days of health data")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first Life OS account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--demo", action="store_true", help="Also load realistic sample data.")
    args = parser.parse_args()

    if len(args.password) < 10:
        parser.error("password must be at least 10 characters")

    init_db()
    with session_scope() as db:
        user = ensure_user(db, args.email, args.password, args.name)
        if args.demo:
            seed_demo(db, user)
        db.flush()

    with session_scope() as db:
        user = db.scalars(select(User).where(User.email == args.email.lower())).one()
        if args.demo:
            found = detect_recurring(db, user.id, commit=False)
            print(f"detector found {len(found)} recurring series")
        insights_service.refresh_insights(db, user.id, commit=False)

    print("done — start the API with: uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()

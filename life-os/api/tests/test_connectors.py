"""Connector ingest tests using realistic export fixtures."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.connectors.base import ConnectorError, IngestPayload, SyncContext
from app.connectors.registry import all_connectors, get_connector
from app.models.finance import Account, AccountType, Holding, Transaction
from app.models.health import HealthMetric, Workout


def ctx(db, user, **config) -> SyncContext:
    return SyncContext(
        db=db, user_id=user.id, connection_id=None, config=config, secrets={}, state={}
    )


def test_registry_exposes_every_connector():
    slugs = {c.slug for c in all_connectors()}
    assert {"plaid", "fidelity_csv", "bank_csv", "apple_health", "ics_calendar", "manual"} <= slugs
    # describe() feeds the UI's setup form; it must stay serialisable.
    for connector in all_connectors():
        json.dumps(connector.describe())


def test_fidelity_positions_import(db, user, fixture_text):
    connector = get_connector("fidelity_csv")
    result = connector.ingest(
        ctx(db, user, institution="Fidelity", account_type="investment"),
        IngestPayload(text=fixture_text("fidelity_positions.csv"), filename="p.csv"),
    )
    db.commit()

    accounts = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    assert {a.external_id for a in accounts} == {"X12345678", "Z98765432"}
    assert all(AccountType(a.type) == AccountType.investment for a in accounts)

    individual = next(a for a in accounts if a.external_id == "X12345678")
    holdings = db.scalars(select(Holding).where(Holding.account_id == individual.id)).all()
    # The "Pending Activity" row must not become a holding.
    assert {h.symbol for h in holdings} == {"FXAIX", "NVDA", "SPAXX"}

    fxaix = next(h for h in holdings if h.symbol == "FXAIX")
    assert float(fxaix.quantity) == pytest.approx(82.451)
    assert float(fxaix.market_value) == pytest.approx(15776.17)
    assert float(fxaix.cost_basis) == pytest.approx(12100.00)

    # Money-market sweep is classified as cash, not equity.
    assert next(h for h in holdings if h.symbol == "SPAXX").asset_class == "cash"
    # Account balance is the sum of its positions.
    assert float(individual.current_balance) == pytest.approx(15776.17 + 3103.20 + 3184.22)
    assert result.created > 0


def test_fidelity_import_is_idempotent(db, user, fixture_text):
    connector = get_connector("fidelity_csv")
    payload = IngestPayload(text=fixture_text("fidelity_positions.csv"))
    connector.ingest(ctx(db, user, institution="Fidelity"), payload)
    db.commit()
    first = db.scalars(select(Holding)).all()

    second_result = connector.ingest(ctx(db, user, institution="Fidelity"), payload)
    db.commit()
    second = db.scalars(select(Holding)).all()

    assert len(first) == len(second), "re-import must update, not duplicate"
    assert second_result.created == 0


def test_fidelity_rejects_unknown_file(db, user):
    with pytest.raises(ConnectorError):
        get_connector("fidelity_csv").ingest(
            ctx(db, user), IngestPayload(text="col_a,col_b\n1,2\n")
        )


def test_bank_csv_import_signs_and_categorises(db, user, fixture_text):
    connector = get_connector("bank_csv")
    connector.ingest(
        ctx(db, user, account_name="Everyday Checking", account_type="depository"),
        IngestPayload(text=fixture_text("bank_transactions.csv")),
    )
    db.commit()

    txns = db.scalars(select(Transaction).where(Transaction.user_id == user.id)).all()
    assert len(txns) == 5

    netflix = next(t for t in txns if "NETFLIX" in t.description)
    assert float(netflix.amount) == -22.99, "spending stays negative"
    assert netflix.category == "subscriptions"

    payroll = next(t for t in txns if "PAYROLL" in t.description)
    assert float(payroll.amount) == 2740.18, "income stays positive"
    assert payroll.category == "income"

    # A card payment is an internal transfer, not spending.
    assert next(t for t in txns if "Thank You" in t.description).is_transfer is True


def test_bank_csv_flip_sign_option(db, user):
    csv_text = "Date,Description,Amount\n09/03/2026,COFFEE SHOP,4.75\n"
    get_connector("bank_csv").ingest(
        ctx(db, user, account_name="Card", account_type="credit", flip_sign=True),
        IngestPayload(text=csv_text),
    )
    db.commit()
    txn = db.scalars(select(Transaction).where(Transaction.user_id == user.id)).one()
    assert float(txn.amount) == -4.75


def test_apple_health_json_ingest(db, user, fixture_text):
    payload_text = fixture_text("health_auto_export.json")
    result = get_connector("apple_health").ingest(
        ctx(db, user, weight_unit="kg"),
        IngestPayload(text=payload_text, json=json.loads(payload_text)),
    )
    db.commit()

    metrics = {
        (m.metric, m.recorded_on.isoformat()): float(m.value)
        for m in db.scalars(select(HealthMetric).where(HealthMetric.user_id == user.id)).all()
    }
    # Same-day step samples are summed.
    assert metrics[("steps", "2026-09-04")] == 8630
    assert metrics[("steps", "2026-09-03")] == 11240
    # Heart rate is averaged, not summed.
    assert metrics[("resting_heart_rate", "2026-09-04")] == 58
    # Sleep hours are converted to minutes.
    assert metrics[("sleep_duration", "2026-09-04")] == pytest.approx(435.0)
    # Kilograms are converted to pounds.
    assert metrics[("weight", "2026-09-04")] == pytest.approx(181.0, abs=0.5)

    workout = db.scalars(select(Workout).where(Workout.user_id == user.id)).one()
    assert workout.activity == "Running"
    assert float(workout.duration_minutes) == pytest.approx(35.0)
    assert float(workout.avg_heart_rate) == 148
    assert result.created > 0


def test_apple_health_xml_backfill(db, user, fixture_text):
    get_connector("apple_health").ingest(
        ctx(db, user), IngestPayload(text=fixture_text("apple_export.xml"))
    )
    db.commit()

    metrics = {
        (m.metric, m.recorded_on.isoformat()): float(m.value)
        for m in db.scalars(select(HealthMetric).where(HealthMetric.user_id == user.id)).all()
    }
    assert metrics[("steps", "2026-09-01")] == 5500
    assert metrics[("weight", "2026-09-01")] == pytest.approx(181.4)
    assert metrics[("resting_heart_rate", "2026-09-02")] == 57
    # Sleep spans midnight; it is credited to the night it started.
    assert metrics[("sleep_duration", "2026-09-02")] == pytest.approx(450.0)


def test_apple_health_rejects_garbage(db, user):
    with pytest.raises(ConnectorError):
        get_connector("apple_health").ingest(ctx(db, user), IngestPayload(text="hello"))


def test_pull_connectors_reject_ingest(db, user):
    with pytest.raises(ConnectorError):
        get_connector("plaid").ingest(ctx(db, user), IngestPayload(text="{}"))


def test_push_connectors_reject_scheduled_sync(db, user):
    with pytest.raises(ConnectorError):
        get_connector("fidelity_csv").sync(ctx(db, user))

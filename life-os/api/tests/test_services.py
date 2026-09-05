"""Business-logic tests: net worth signs, payoff maths, recurring detection."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.bills import Bill, Cadence
from app.models.finance import Account, AccountType, DebtDetail, Transaction
from app.services import analytics, bills as bills_service
from app.services import debt as debt_service
from app.services.bills import advance_due_date, mark_paid
from app.services.upserts import normalize_merchant


def make_account(db, user, name, type_, balance, **kw) -> Account:
    account = Account(user_id=user.id, name=name, type=type_, current_balance=balance, **kw)
    db.add(account)
    db.commit()
    return account


# --- net worth -------------------------------------------------------------
def test_liabilities_reduce_net_worth(db, user):
    make_account(db, user, "Checking", AccountType.depository, 5000)
    make_account(db, user, "Visa", AccountType.credit, 1500)
    make_account(db, user, "Auto Loan", AccountType.loan, 10000)

    result = analytics.net_worth(db, user.id)
    assert result["assets"] == 5000
    assert result["liabilities"] == 11500
    assert result["net_worth"] == -6500


def test_excluded_accounts_are_left_out(db, user):
    make_account(db, user, "Checking", AccountType.depository, 5000)
    make_account(db, user, "Shared", AccountType.depository, 9999, include_in_net_worth=False)
    assert analytics.net_worth(db, user.id)["net_worth"] == 5000


# --- debt ------------------------------------------------------------------
def _debt(name, balance, apr, minimum) -> debt_service.DebtLine:
    return debt_service.DebtLine(
        account_id=name, name=name, balance=balance, apr=apr, minimum=minimum,
        account_type="credit",
    )


def test_zero_interest_payoff_is_exact():
    plan = debt_service.simulate([_debt("Card", 1200, 0.0, 100)], extra_payment=0)
    assert plan.months == 12
    assert plan.total_interest == 0
    assert plan.total_paid == pytest.approx(1200, abs=0.01)


def test_extra_payment_shortens_payoff_and_cuts_interest():
    debts = [_debt("Card", 5000, 22.0, 125)]
    base = debt_service.simulate(debts, extra_payment=0)
    boosted = debt_service.simulate(debts, extra_payment=300)
    assert boosted.months < base.months
    assert boosted.total_interest < base.total_interest


def test_avalanche_targets_highest_apr_first():
    debts = [_debt("Low APR big", 8000, 4.0, 100), _debt("High APR small", 2000, 26.0, 50)]
    plan = debt_service.simulate(debts, strategy="avalanche", extra_payment=400)
    assert plan.order[0]["name"] == "High APR small"


def test_snowball_targets_smallest_balance_first():
    debts = [_debt("Big", 8000, 26.0, 100), _debt("Small", 900, 4.0, 25)]
    plan = debt_service.simulate(debts, strategy="snowball", extra_payment=400)
    assert plan.order[0]["name"] == "Small"


def test_avalanche_never_costs_more_interest_than_snowball():
    debts = [
        _debt("Card A", 6000, 24.99, 150),
        _debt("Card B", 1200, 9.99, 35),
        _debt("Loan", 15000, 5.5, 250),
    ]
    avalanche = debt_service.simulate(debts, strategy="avalanche", extra_payment=250)
    snowball = debt_service.simulate(debts, strategy="snowball", extra_payment=250)
    assert avalanche.total_interest <= snowball.total_interest


def test_unpayable_debt_is_reported_not_looped_forever():
    # Minimum payment below the monthly interest can never clear the balance.
    plan = debt_service.simulate([_debt("Trap", 20000, 29.99, 50)], extra_payment=0)
    assert plan.feasible is False
    assert "cannot be paid off" in plan.note


def test_empty_debt_list_returns_empty_plan():
    plan = debt_service.simulate([], extra_payment=100)
    assert plan.months == 0 and plan.payoff_date is None


def test_load_debts_defaults_missing_terms(db, user):
    account = make_account(db, user, "Visa", AccountType.credit, 2000)
    db.add(DebtDetail(account_id=account.id))  # no APR, no minimum
    db.commit()
    line = debt_service.load_debts(db, user.id)[0]
    assert line.apr == 22.0, "a credit card with no APR on file gets a realistic default"
    assert line.minimum == 40.0, "2% of balance"


# --- bills -----------------------------------------------------------------
def test_monthly_cost_normalises_cadences():
    assert Bill(name="a", amount=120, cadence=Cadence.annual).monthly_cost == 10.0
    assert Bill(name="b", amount=30, cadence=Cadence.quarterly).monthly_cost == 10.0
    assert Bill(name="c", amount=10, cadence=Cadence.monthly).monthly_cost == 10.0
    assert Bill(name="d", amount=0, cadence=Cadence.one_time).monthly_cost == 0.0


def test_advance_due_date_rolls_past_today():
    bill = Bill(name="x", amount=10, cadence=Cadence.monthly, next_due_on=date.today() - timedelta(days=95))
    assert advance_due_date(bill) >= date.today()


def test_mark_paid_advances_and_records(db, user):
    bill = Bill(
        user_id=user.id, name="Internet", amount=80, cadence=Cadence.monthly,
        next_due_on=date.today(),
    )
    db.add(bill)
    db.commit()
    original = bill.next_due_on
    mark_paid(db, bill, amount=80)
    db.commit()
    assert bill.last_paid_on == date.today()
    assert bill.next_due_on > original


def test_one_time_bill_closes_when_paid(db, user):
    bill = Bill(
        user_id=user.id, name="DMV fee", amount=90, cadence=Cadence.one_time,
        next_due_on=date.today(),
    )
    db.add(bill)
    db.commit()
    mark_paid(db, bill)
    db.commit()
    assert bill.is_active is False


# --- detection -------------------------------------------------------------
def _txn(db, user, account, when, amount, description):
    db.add(
        Transaction(
            user_id=user.id, account_id=account.id, posted_on=when, amount=amount,
            description=description, merchant=normalize_merchant(description),
            external_id=f"{description}-{when}-{amount}",
        )
    )


def test_detector_finds_a_monthly_subscription(db, user):
    account = make_account(db, user, "Card", AccountType.credit, 500)
    for months_back in range(6):
        when = date.today() - timedelta(days=30 * months_back)
        _txn(db, user, account, when, -15.99, f"NETFLIX.COM {when:%m/%d}")
    db.commit()

    found = bills_service.detect_recurring(db, user.id)
    netflix = next(f for f in found if "netflix" in f["merchant"])
    assert netflix["cadence"] == "monthly"
    assert netflix["amount"] == pytest.approx(15.99)
    assert netflix["is_subscription"] is True
    assert netflix["confidence"] > 0.7
    assert netflix["name"] == "Netflix.Com", "the trailing date is stripped from the label"


def test_detector_ignores_irregular_purchases(db, user):
    """Same merchant, similar amounts, random timing — a habit, not a bill."""
    account = make_account(db, user, "Card", AccountType.credit, 500)
    for offset in (2, 5, 6, 19, 21, 40, 41, 44, 70):
        when = date.today() - timedelta(days=offset)
        _txn(db, user, account, when, -6.25 - offset % 3, f"STARBUCKS 8821 {when:%m/%d}")
    db.commit()

    found = bills_service.detect_recurring(db, user.id)
    assert not any("starbucks" in f["merchant"] for f in found)


def test_detector_ignores_variable_amounts(db, user):
    account = make_account(db, user, "Card", AccountType.credit, 500)
    for index, months_back in enumerate(range(6)):
        when = date.today() - timedelta(days=30 * months_back)
        _txn(db, user, account, when, -(20 + index * 40), f"HOME DEPOT {when:%m/%d}")
    db.commit()
    found = bills_service.detect_recurring(db, user.id)
    assert not any("home depot" in f["merchant"] for f in found)


def test_detector_is_idempotent(db, user):
    account = make_account(db, user, "Card", AccountType.credit, 500)
    for months_back in range(6):
        when = date.today() - timedelta(days=30 * months_back)
        _txn(db, user, account, when, -9.99, f"SPOTIFY USA {when:%m/%d}")
    db.commit()

    first = bills_service.detect_recurring(db, user.id)
    second = bills_service.detect_recurring(db, user.id)
    assert [f["status"] for f in first] == ["created"]
    assert [f["status"] for f in second] == ["updated"]
    assert len(db.query(Bill).filter(Bill.user_id == user.id).all()) == 1


def test_dismissed_bills_are_not_resurrected(db, user):
    account = make_account(db, user, "Card", AccountType.credit, 500)
    for months_back in range(6):
        when = date.today() - timedelta(days=30 * months_back)
        _txn(db, user, account, when, -4.99, f"ICLOUD STORAGE {when:%m/%d}")
    db.commit()

    bills_service.detect_recurring(db, user.id)
    bill = db.query(Bill).filter(Bill.user_id == user.id).one()
    bill.dismissed = True
    bill.amount = 1.0
    db.commit()

    bills_service.detect_recurring(db, user.id)
    db.refresh(bill)
    assert bill.dismissed is True
    assert float(bill.amount) == 1.0, "a dismissed bill is left alone"


def test_normalize_merchant_strips_noise():
    assert normalize_merchant("SQ *NETFLIX.COM 4829 CA 03/14") == "netflix.com ca"
    assert normalize_merchant("POS DEBIT WEGMANS #41") == "wegmans"


def test_recurring_utilities_are_bills_not_subscriptions(db, user):
    """The subscription total must mean "money I could stop spending"."""
    account = make_account(db, user, "Card", AccountType.credit, 500)
    for months_back in range(6):
        when = date.today() - timedelta(days=30 * months_back)
        _txn(db, user, account, when, -148.72, f"PSE&G UTILITY {when:%m/%d}")
        _txn(db, user, account, when, -92.41, f"VERIZON WIRELESS {when:%m/%d}")
        _txn(db, user, account, when, -18.00, f"PROGRESSIVE RENTERS INS {when:%m/%d}")
        _txn(db, user, account, when, -22.99, f"NETFLIX.COM {when:%m/%d}")
    db.commit()

    found = {row["merchant"]: row for row in bills_service.detect_recurring(db, user.id)}
    assert found["netflix.com"]["is_subscription"] is True
    for merchant in ("pse&g utility", "verizon wireless", "progressive renters ins"):
        assert found[merchant]["is_subscription"] is False, merchant

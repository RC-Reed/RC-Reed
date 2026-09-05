from app.connectors._csvutil import parse_date, parse_money, pick, sniff_rows


def test_parse_money_handles_export_formatting():
    assert parse_money("$1,234.56") == 1234.56
    assert parse_money("(45.00)") == -45.0
    assert parse_money("+30.38%") == 30.38
    assert parse_money("--") is None
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money(12.5) == 12.5


def test_parse_date_tries_common_layouts():
    assert parse_date("2026-09-05").isoformat() == "2026-09-05"
    assert parse_date("09/05/2026").isoformat() == "2026-09-05"
    assert parse_date("Sep 05, 2026").isoformat() == "2026-09-05"
    assert parse_date("not a date") is None


def test_sniff_rows_stops_at_footer(fixture_text):
    rows = sniff_rows(fixture_text("fidelity_positions.csv"))
    # Six data rows; the blank line and disclaimer must not become rows.
    assert len(rows) == 6
    assert all("Brokerage services" not in "".join(r.values()) for r in rows)


def test_pick_is_insensitive_to_header_spelling():
    row = {"Account Number": "X1", "Last Price": "$3.00"}
    assert pick(row, "account number") == "X1"
    assert pick(row, "Price", "Last Price") == "$3.00"
    assert pick(row, "missing") == ""

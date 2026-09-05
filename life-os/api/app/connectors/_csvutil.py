"""Shared CSV parsing helpers.

Exported financial CSVs are messy in predictable ways: currency symbols,
thousands separators, parenthesised negatives, percent signs, and a block of
legal boilerplate appended after a blank line. These helpers absorb that.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

_CURRENCY = re.compile(r"[,$%\s]")
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
)


def parse_money(value: str | float | None) -> float | None:
    """'$1,234.56' -> 1234.56 ; '(45.00)' -> -45.0 ; '--' -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text or text in {"--", "-", "n/a", "N/A"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = _CURRENCY.sub("", text.strip("()"))
    if not text or text in {"-", "."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def parse_date(value: str | None, explicit_format: str = "") -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    formats = (explicit_format,) + _DATE_FORMATS if explicit_format else _DATE_FORMATS
    for fmt in formats:
        if not fmt:
            continue
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def sniff_rows(text: str) -> list[dict[str, str]]:
    """Read CSV rows, skipping preamble junk and stopping at the footer.

    Real exports often lead with a title line and trail with disclaimers, so
    we locate the widest header row and stop once rows go blank.
    """
    lines = text.replace("\r\n", "\n").split("\n")

    header_index = 0
    best_columns = 0
    for index, line in enumerate(lines[:15]):
        columns = len(next(csv.reader([line]), []))
        if columns > best_columns and line.strip():
            best_columns, header_index = columns, index
    if best_columns < 2:
        return []

    body: list[str] = [lines[header_index]]
    for line in lines[header_index + 1 :]:
        if not line.strip():
            # A blank line marks the end of the data block in Fidelity exports.
            break
        body.append(line)

    reader = csv.DictReader(io.StringIO("\n".join(body)))
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            (key or "").strip(): (value or "").strip()
            for key, value in raw.items()
            if key is not None
        }
        if any(row.values()):
            rows.append(row)
    return rows


def pick(row: dict[str, str], *candidates: str) -> str:
    """Case/space-insensitive column lookup across likely header spellings."""
    normalized = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in row.items()}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]", "", candidate.lower())
        if key in normalized:
            return normalized[key]
    return ""

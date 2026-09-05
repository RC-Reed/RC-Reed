"""Calendar (ICS) — turns upcoming events into dated tasks.

Works with any calendar that exposes a secret ICS URL: Google Calendar
("Secret address in iCal format"), Outlook/Microsoft 365 ("Publish a
calendar"), Apple iCloud ("Public Calendar" link), Fastmail, and so on.

Events become tasks so that "what is on me today" is one list, not three.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import httpx

from app.connectors.base import (
    Connector,
    ConnectorCategory,
    ConnectorError,
    ConnectorField,
    ConnectorMode,
    FieldType,
    SyncContext,
    SyncResult,
)
from app.connectors.registry import register
from app.models.tasks import Area
from app.services.upserts import upsert_task


@register
class IcsCalendarConnector(Connector):
    slug = "ics_calendar"
    name = "Calendar (ICS feed)"
    category = ConnectorCategory.productivity
    mode = ConnectorMode.pull
    description = (
        "Pulls upcoming events from any iCal/ICS URL — Google, Outlook, iCloud — "
        "and files them alongside your todos."
    )
    provides = ("tasks",)
    fields = (
        ConnectorField(
            key="ics_url",
            label="ICS URL",
            type=FieldType.url,
            secret=True,
            help="The secret iCal address. Treat it like a password — it exposes your calendar.",
        ),
        ConnectorField(
            key="area",
            label="File events under",
            type=FieldType.select,
            required=False,
            default="work",
            options=tuple(a.value for a in Area),
        ),
        ConnectorField(
            key="days_ahead",
            label="Days ahead to import",
            type=FieldType.number,
            required=False,
            default=21,
        ),
    )

    def sync(self, ctx: SyncContext) -> SyncResult:
        url = ctx.secrets.get("ics_url", "")
        if not url:
            raise ConnectorError("No ICS URL configured.")

        try:
            response = httpx.get(url, timeout=30, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Could not fetch calendar: {exc}") from exc

        try:
            from icalendar import Calendar
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ConnectorError("icalendar package is not installed") from exc

        try:
            calendar = Calendar.from_ical(response.text)
        except ValueError as exc:
            raise ConnectorError(f"Feed is not valid iCalendar data: {exc}") from exc

        horizon_days = int(ctx.opt("days_ahead", 21) or 21)
        today = date.today()
        window_end = today + timedelta(days=horizon_days)
        area = Area(ctx.opt("area", "work") or "work")

        result = SyncResult()
        for component in calendar.walk("VEVENT"):
            start = component.get("DTSTART")
            if start is None:
                continue
            start_value = start.dt
            event_date = start_value.date() if isinstance(start_value, datetime) else start_value
            if not (today - timedelta(days=1) <= event_date <= window_end):
                continue

            due = (
                start_value
                if isinstance(start_value, datetime)
                else datetime.combine(event_date, time(9, 0))
            )
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)

            uid = str(component.get("UID") or f"{event_date}-{component.get('SUMMARY')}")
            created = upsert_task(
                ctx.db,
                user_id=ctx.user_id,
                connection_id=ctx.connection_id,
                external_id=f"{uid}:{event_date.isoformat()}",
                defaults={
                    "title": str(component.get("SUMMARY") or "(untitled event)"),
                    "notes": str(component.get("DESCRIPTION") or "")[:2000],
                    "area": area,
                    "source": "calendar",
                    "due_at": due,
                    "start_at": due,
                    "priority": 2,
                    "url": str(component.get("URL") or ""),
                    "tags": ["calendar"],
                },
            )
            result.created += int(created)
            result.updated += int(not created)

        result.message = f"{result.created} new event(s), {result.updated} refreshed"
        return result

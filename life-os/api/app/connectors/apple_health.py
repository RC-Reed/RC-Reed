"""Apple Health (and anything that speaks its vocabulary).

Apple gives no server-side API for Health data — it lives on the device, on
purpose. So this is a push connector with two supported inputs:

1. **Automated (recommended).** The "Health Auto Export" iOS app, or a
   Shortcuts automation, POSTs JSON to::

       POST /api/v1/ingest/health?token=<ingest token>

   Set that as the REST destination, pick your metrics, and let it run on a
   schedule. Your phone talks to your server; nothing goes through a cloud.

2. **Manual backfill.** Health app -> profile -> Export All Health Data
   produces export.zip containing export.xml. Unzip it and upload the XML
   here to load years of history in one shot.

Readings are aggregated to one value per metric per day — sums for counts
(steps, calories, minutes), averages for rates (heart rate, HRV), latest for
point-in-time values (weight). Daily granularity is what a dashboard reads;
storing every raw sample would be millions of rows nobody looks at.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable
from xml.etree import ElementTree

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
from app.services.upserts import upsert_health_metric, upsert_workout

# Health Auto Export metric names -> canonical keys.
HAE_METRICS = {
    "step_count": "steps",
    "active_energy": "active_energy",
    "apple_exercise_time": "exercise_minutes",
    "resting_heart_rate": "resting_heart_rate",
    "heart_rate_variability": "heart_rate_variability",
    "vo2_max": "vo2_max",
    "sleep_analysis": "sleep_duration",
    "weight_body_mass": "weight",
    "body_fat_percentage": "body_fat",
    "mindful_minutes": "mindful_minutes",
    "blood_pressure_systolic": "blood_pressure_systolic",
    "blood_pressure_diastolic": "blood_pressure_diastolic",
}

# HealthKit identifiers from export.xml -> canonical keys.
HK_METRICS = {
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy",
    "HKQuantityTypeIdentifierAppleExerciseTime": "exercise_minutes",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "heart_rate_variability",
    "HKQuantityTypeIdentifierVO2Max": "vo2_max",
    "HKQuantityTypeIdentifierBodyMass": "weight",
    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat",
    "HKQuantityTypeIdentifierBloodPressureSystolic": "blood_pressure_systolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "blood_pressure_diastolic",
}

SUM_METRICS = {"steps", "active_energy", "exercise_minutes", "sleep_duration", "mindful_minutes"}
LATEST_METRICS = {"weight", "body_fat", "vo2_max"}
# Everything else is averaged.

_KG_TO_LB = 2.2046226218


def _parse_when(value: Any) -> date | None:
    """Accept the several date shapes these exports use."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).date()
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # "2024-03-14 06:30:00 -0500" and "2024-03-14 06:30:00 -0500" variants
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return date.fromisoformat(match.group(1))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class _Aggregator:
    """Collects raw readings and reduces them to one value per metric per day."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, date], list[tuple[float, str]]] = defaultdict(list)
        self._units: dict[str, str] = {}

    def add(self, metric: str, when: date, value: float, unit: str = "") -> None:
        self._buckets[(metric, when)].append((value, unit))
        if unit and metric not in self._units:
            self._units[metric] = unit

    def reduce(self) -> Iterable[tuple[str, date, float, str]]:
        for (metric, when), readings in self._buckets.items():
            values = [v for v, _ in readings]
            if metric in SUM_METRICS:
                value = sum(values)
            elif metric in LATEST_METRICS:
                value = values[-1]
            else:
                value = sum(values) / len(values)
            yield metric, when, round(value, 4), self._units.get(metric, "")

    def __len__(self) -> int:
        return len(self._buckets)


@register
class AppleHealthConnector(Connector):
    slug = "apple_health"
    name = "Apple Health"
    category = ConnectorCategory.health
    mode = ConnectorMode.push
    schedulable = False
    description = (
        "Receives health data pushed from your iPhone — via the Health Auto Export "
        "app or a Shortcuts automation — and accepts an export.xml upload for "
        "historical backfill."
    )
    provides = ("health_metrics", "workouts")
    docs_url = "https://github.com/Lybron/health-auto-export"
    fields = (
        ConnectorField(
            key="weight_unit",
            label="Weight unit in source",
            type=FieldType.select,
            required=False,
            default="lb",
            options=("lb", "kg"),
            help="Converted to pounds on the way in so charts stay consistent.",
        ),
    )

    def ingest(self, ctx: SyncContext, payload: IngestPayload) -> SyncResult:
        text = payload.text or ""
        data = payload.json
        if data is None and text.lstrip().startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConnectorError(f"Body is not valid JSON: {exc}") from exc

        if data is not None:
            return self._ingest_json(ctx, data)
        if "<HealthData" in text or text.lstrip().startswith("<?xml"):
            return self._ingest_xml(ctx, text)
        raise ConnectorError(
            "Expected Health Auto Export JSON or an Apple Health export.xml file."
        )

    # ------------------------------------------------------------------
    def _ingest_json(self, ctx: SyncContext, data: Any) -> SyncResult:
        body = data.get("data", data) if isinstance(data, dict) else {}
        metrics = body.get("metrics") or []
        workouts = body.get("workouts") or []
        if not metrics and not workouts:
            raise ConnectorError("Payload contained no metrics or workouts.")

        aggregator = _Aggregator()
        for entry in metrics:
            raw_name = (entry.get("name") or "").lower()
            metric = HAE_METRICS.get(raw_name, raw_name)
            unit = entry.get("units") or ""
            for point in entry.get("data") or []:
                when = _parse_when(point.get("date"))
                if when is None:
                    continue
                value = point.get("qty")
                if value is None:
                    # Sleep payloads report phases instead of a single quantity.
                    value = point.get("asleep") or point.get("totalSleep")
                if value is None:
                    continue
                value = float(value)
                if metric == "sleep_duration" and unit.lower() in {"hr", "hours", ""}:
                    value, unit = value * 60, "min"
                if metric == "weight":
                    value = self._to_pounds(ctx, value, unit)
                    unit = "lb"
                aggregator.add(metric, when, value, unit)

        created = self._write(ctx, aggregator, source="apple_health")
        workout_count = self._write_workouts(ctx, workouts)

        return SyncResult(
            created=created + workout_count,
            updated=max(len(aggregator) - created, 0),
            message=f"{len(aggregator)} metric-day(s), {workout_count} new workout(s)",
        )

    def _write_workouts(self, ctx: SyncContext, workouts: list[dict[str, Any]]) -> int:
        created = 0
        for workout in workouts:
            start = workout.get("start") or workout.get("startDate")
            when = _parse_when(start)
            if when is None:
                continue
            started_at = datetime.combine(when, datetime.min.time())
            external_id = str(workout.get("id") or f"{start}|{workout.get('name', '')}")
            duration = workout.get("duration") or 0
            # Health Auto Export reports duration in seconds.
            minutes = float(duration) / 60 if float(duration) > 300 else float(duration)
            if upsert_workout(
                ctx.db,
                user_id=ctx.user_id,
                external_id=external_id,
                defaults={
                    "activity": workout.get("name") or "workout",
                    "started_at": started_at,
                    "duration_minutes": round(minutes, 2),
                    "distance_miles": _num(workout.get("distance")),
                    "energy_kcal": _num(workout.get("activeEnergyBurned") or workout.get("energy")),
                    "avg_heart_rate": _num((workout.get("avgHeartRate") or {}).get("qty"))
                    if isinstance(workout.get("avgHeartRate"), dict)
                    else _num(workout.get("avgHeartRate")),
                    "source": "apple_health",
                },
            ):
                created += 1
        return created

    # ------------------------------------------------------------------
    def _ingest_xml(self, ctx: SyncContext, text: str) -> SyncResult:
        aggregator = _Aggregator()
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            raise ConnectorError(f"Could not parse export.xml: {exc}") from exc

        for record in root.iter("Record"):
            metric = HK_METRICS.get(record.get("type", ""))
            if not metric:
                continue
            when = _parse_when(record.get("startDate"))
            if when is None:
                continue
            try:
                value = float(record.get("value", ""))
            except (TypeError, ValueError):
                continue
            unit = record.get("unit") or ""
            if metric == "weight":
                value = self._to_pounds(ctx, value, unit)
                unit = "lb"
            aggregator.add(metric, when, value, unit)

        # Sleep lives in Category records with a duration rather than a value.
        for record in root.iter("Record"):
            if record.get("type") != "HKCategoryTypeIdentifierSleepAnalysis":
                continue
            start = _parse_when(record.get("startDate"))
            try:
                begin = datetime.fromisoformat(record.get("startDate", "").replace(" +", "+"))
                end = datetime.fromisoformat(record.get("endDate", "").replace(" +", "+"))
            except ValueError:
                continue
            if start is None:
                continue
            aggregator.add("sleep_duration", start, (end - begin).total_seconds() / 60, "min")

        if not len(aggregator):
            raise ConnectorError("No recognised health records found in that export.")

        created = self._write(ctx, aggregator, source="apple_health_export")
        return SyncResult(
            created=created,
            updated=len(aggregator) - created,
            message=f"Backfilled {len(aggregator)} metric-day(s) from export.xml",
        )

    # ------------------------------------------------------------------
    def _to_pounds(self, ctx: SyncContext, value: float, unit: str) -> float:
        unit = (unit or ctx.opt("weight_unit") or "lb").lower()
        return round(value * _KG_TO_LB, 2) if unit.startswith("kg") else value

    def _write(self, ctx: SyncContext, aggregator: _Aggregator, *, source: str) -> int:
        created = 0
        for metric, when, value, unit in aggregator.reduce():
            if upsert_health_metric(
                ctx.db,
                user_id=ctx.user_id,
                metric=metric,
                recorded_on=when,
                value=value,
                unit=unit,
                source=source,
            ):
                created += 1
        return created


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

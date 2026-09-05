"""Background worker.

One job, run on an interval: sync everything that is due, roll bill due dates
forward, and refresh insights. Kept in-process (APScheduler) rather than
Celery + a broker, because a personal system should not need three daemons to
tell you a bill is due. Swapping in a real queue later means replacing this
file only — `run_due_syncs` is the whole contract.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.models.bills import Bill
from app.models.user import User
from app.services import insights as insights_service
from app.services.bills import advance_due_date
from app.services.sync import due_connections, run_sync

log = logging.getLogger("lifeos.scheduler")
_scheduler: BackgroundScheduler | None = None


def run_due_syncs() -> dict[str, int]:
    """The whole background tick. Safe to call by hand or from a cron."""
    synced = failed = 0
    with session_scope() as db:
        for connection in due_connections(db):
            run = run_sync(db, connection, trigger="scheduled")
            if str(run.status) == "failed":
                failed += 1
                log.warning("scheduled sync failed: %s — %s", connection.display_name, run.message)
            else:
                synced += 1

    with session_scope() as db:
        for bill in db.scalars(select(Bill).where(Bill.is_active.is_(True))).all():
            advance_due_date(bill)

        for user in db.scalars(select(User).where(User.is_active.is_(True))).all():
            insights_service.refresh_insights(db, user.id, commit=False)

    log.info("scheduler tick: %s synced, %s failed", synced, failed)
    return {"synced": synced, "failed": failed}


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("scheduler disabled (set LIFEOS_SCHEDULER_ENABLED=true to turn it on)")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_due_syncs,
        "interval",
        minutes=max(settings.sync_interval_minutes, 5),
        id="lifeos_sync",
        # If the app was asleep, run once rather than replaying every miss.
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    _scheduler.start()
    log.info("scheduler started; tick every %s minutes", settings.sync_interval_minutes)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

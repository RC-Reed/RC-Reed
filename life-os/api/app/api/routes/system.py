"""Operational endpoints: health check, ingest info, manual scheduler tick."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.user import User
from app.services.scheduler import run_due_syncs

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/ingest-info")
def ingest_info(request: Request, user: User = Depends(get_current_user)):
    """Everything needed to point an iPhone automation at this server."""
    base = str(request.base_url).rstrip("/")
    return {
        "endpoint": f"{base}/api/v1/ingest/health",
        "token": settings.ingest_token,
        "header": "X-Ingest-Token",
        "note": (
            "In Health Auto Export choose REST API, set this URL, add the "
            "X-Ingest-Token header, and select JSON. The token can also be "
            "passed as ?token=... if your client can't set headers."
        ),
    }


@router.post("/run-sync-tick")
def run_tick(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Run the scheduler's job once, on demand — handy behind an external cron."""
    return run_due_syncs()

"""Life OS API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    auth,
    bills,
    connections,
    dashboard,
    finance,
    health_routes,
    ingest,
    insights,
    system,
    tasks,
)
from app.config import settings
from app.connectors.base import ConnectorError
from app.db import init_db
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("lifeos")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("%s starting (%s)", settings.app_name, settings.environment)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Life OS API",
    version="0.1.0",
    description=(
        "A self-hosted system of record for money, health, work and everything "
        "else you'd otherwise track in six different apps."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ConnectorError)
async def connector_error_handler(_request: Request, exc: ConnectorError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


@app.get("/healthz", tags=["system"])
def healthz() -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


for module in (
    auth,
    dashboard,
    finance,
    bills,
    tasks,
    health_routes,
    connections,
    insights,
    ingest,
    system,
):
    app.include_router(module.router, prefix=API_PREFIX)

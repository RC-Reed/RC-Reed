"""Application configuration.

Every value can be overridden with an environment variable (or a .env file
sitting next to the api/ directory). Defaults are chosen so that
`uvicorn app.main:app` works on a fresh clone with zero setup: SQLite on disk,
a dev secret, and the scheduler disabled until you opt in.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = API_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(API_DIR / ".env", API_DIR.parent / ".env"),
        env_prefix="LIFEOS_",
        extra="ignore",
    )

    app_name: str = "Life OS"
    environment: str = "development"
    debug: bool = True

    # --- storage -------------------------------------------------------
    # SQLite by default; docker-compose overrides this with Postgres.
    database_url: str = f"sqlite:///{DATA_DIR / 'lifeos.db'}"

    # --- auth ----------------------------------------------------------
    secret_key: str = "dev-only-change-me"
    access_token_ttl_minutes: int = 60 * 12
    # Fernet key used to encrypt connector credentials at rest. Generated on
    # first boot into data/vault.key when unset, so nothing sensitive ever
    # lands in git.
    vault_key: str | None = None

    # --- behaviour -----------------------------------------------------
    scheduler_enabled: bool = False
    sync_interval_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Ingest token for push-style connectors (Apple Health shortcuts, etc).
    # Generated on first boot when unset so the endpoint is never wide open.
    ingest_token: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _read_or_create(path: Path, factory) -> str:
    """Persist a generated secret so it survives restarts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text().strip()
    value = factory()
    path.write_text(value)
    path.chmod(0o600)
    return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not settings.vault_key:
        from cryptography.fernet import Fernet

        settings.vault_key = _read_or_create(
            DATA_DIR / "vault.key", lambda: Fernet.generate_key().decode()
        )
    if not settings.ingest_token:
        settings.ingest_token = _read_or_create(
            DATA_DIR / "ingest.token", lambda: secrets.token_urlsafe(32)
        )
    return settings


settings = get_settings()

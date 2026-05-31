"""
risk_api/app/config.py
Application settings loaded from environment variables.
"""

from __future__ import annotations
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql://fatal_user:password@localhost/fatal_flaw_db"
    async_database_url: str = "postgresql+asyncpg://fatal_user:password@localhost/fatal_flaw_db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: Optional[str] = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 300   # 5 minutes

    # ── Security ─────────────────────────────────────────────────────────────
    api_key: str = "dev-change-in-production"
    allowed_origins: list[str] = ["*"]

    # ── Performance ──────────────────────────────────────────────────────────
    sla_ms: int = 500
    port: int = 8000
    workers: int = 4

    # ── Scoring ──────────────────────────────────────────────────────────────
    # Area limits for submitted site polygons (acres)
    min_site_acres: float = 1.0
    max_site_acres: float = 50_000.0

    # Weight refresh interval (seconds)
    weight_refresh_interval: int = 300

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

"""
risk_api/app/services/database.py
Async PostgreSQL connection pool using asyncpg + SQLAlchemy async engine.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)


class DatabasePool:
    """
    Wraps an asyncpg connection pool alongside an async SQLAlchemy engine.
    Use the raw asyncpg pool for performance-critical spatial queries,
    and the SQLAlchemy engine for ORM/query builder operations.
    """

    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        self._engine: AsyncEngine | None = None

    async def initialize(self) -> None:
        """Create the asyncpg pool and SQLAlchemy engine."""
        # Parse DSN for asyncpg (strip the +asyncpg dialect prefix if present)
        dsn = settings.async_database_url.replace("postgresql+asyncpg://", "postgresql://")

        self._pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=2,
            max_size=settings.db_pool_size,
            command_timeout=60,
            max_inactive_connection_lifetime=300,
            # Register geometry codec so PostGIS EWKB comes back as bytes
            init=self._init_connection,
        )

        self._engine = create_async_engine(
            settings.async_database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            echo=False,
        )
        logger.info(
            "DB pool ready (min=%d, max=%d)", 2, settings.db_pool_size
        )

    @staticmethod
    async def _init_connection(conn: asyncpg.Connection) -> None:
        """Register custom codecs on each new connection."""
        # Tell asyncpg to return geometry columns as hex-encoded WKB strings
        await conn.set_type_codec(
            "geometry",
            encoder=str,
            decoder=str,
            schema="public",
            format="text",
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
        if self._engine:
            await self._engine.dispose()

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DatabasePool not initialized — call initialize() first")
        return self._pool

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("DatabasePool not initialized — call initialize() first")
        return self._engine

    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args) -> str:
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    def session(self) -> AsyncSession:
        """Return an async SQLAlchemy session (for ORM use)."""
        SessionLocal = sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        return SessionLocal()


# ── Singleton instance ────────────────────────────────────────────────────────
engine_pool = DatabasePool()


# ── FastAPI dependency ────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[DatabasePool, None]:
    yield engine_pool

"""
risk_api/app/main.py
Fatal Flaw Risk Assessment API — FastAPI application entry point.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.database import engine_pool
from app.services.risk_engine import RiskEngine
from app.api.v1.endpoints.assess import router as assess_router
from app.api.v1.endpoints.weights import router as weights_router
from app.api.v1.endpoints.health import router as health_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("fatal_flaw_api")

# ── Shared state ─────────────────────────────────────────────────────────────
_risk_engine: RiskEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: init DB pool + load weights. Shutdown: close pool."""
    global _risk_engine
    logger.info("Initializing database connection pool …")
    await engine_pool.initialize()

    logger.info("Loading risk weights from database …")
    _risk_engine = RiskEngine(engine_pool)
    await _risk_engine.load_weights()

    # Expose engine via app state for dependency injection
    app.state.risk_engine = _risk_engine
    app.state.db_pool = engine_pool

    logger.info("Fatal Flaw API ready on port %s", settings.port)
    yield

    logger.info("Shutting down — closing DB pool …")
    await engine_pool.close()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Fatal Flaw Geospatial Risk Assessment API",
    description=(
        "Production-grade site suitability scoring for Solar, Wind, BESS, and Data Center "
        "projects across CONUS. Accepts GeoJSON polygons and returns weighted risk scores "
        "against 15 geospatial constraint layers."
    ),
    version="1.0.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request timing middleware ────────────────────────────────────────────────
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    if elapsed_ms > settings.sla_ms:
        logger.warning(
            "SLA breach: %s %s took %.1fms (SLA: %dms)",
            request.method, request.url.path, elapsed_ms, settings.sla_ms,
        )
    return response

# ── Global exception handler ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(health_router, tags=["Health"])
app.include_router(assess_router, prefix="/api/v1", tags=["Assessment"])
app.include_router(weights_router, prefix="/api/v1", tags=["Weights (Admin)"])

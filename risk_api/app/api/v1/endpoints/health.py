"""
risk_api/app/api/v1/endpoints/health.py
/health and /metrics endpoints.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter()

# ── Simple in-process metrics store ──────────────────────────────────────────
_request_count: int = 0
_error_count: int = 0
_latencies: deque = deque(maxlen=1000)   # last 1000 request latencies (ms)
_metrics_lock = Lock()


def record_request(latency_ms: float, is_error: bool = False) -> None:
    global _request_count, _error_count
    with _metrics_lock:
        _request_count += 1
        _latencies.append(latency_ms)
        if is_error:
            _error_count += 1


@router.get("/health", summary="Health check")
async def health(request: Request) -> dict:
    """Returns 200 when the API is ready and the database is reachable."""
    db = request.app.state.db_pool
    db_ok = False
    db_latency_ms = None
    try:
        t0 = time.perf_counter()
        await db.fetchval("SELECT 1")
        db_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        db_ok = True
    except Exception as exc:
        db_error = str(exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "db_latency_ms": db_latency_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
async def metrics() -> str:
    """Prometheus-style text metrics."""
    import statistics

    with _metrics_lock:
        count = _request_count
        errors = _error_count
        lats = list(_latencies)

    p50 = round(statistics.median(lats), 1) if lats else 0
    p95 = round(sorted(lats)[int(len(lats) * 0.95)] if len(lats) > 20 else (max(lats) if lats else 0), 1)
    p99 = round(sorted(lats)[int(len(lats) * 0.99)] if len(lats) > 100 else (max(lats) if lats else 0), 1)
    avg = round(sum(lats) / len(lats), 1) if lats else 0

    lines = [
        "# HELP fatal_flaw_requests_total Total HTTP requests",
        "# TYPE fatal_flaw_requests_total counter",
        f"fatal_flaw_requests_total {count}",
        "",
        "# HELP fatal_flaw_errors_total Total HTTP errors",
        "# TYPE fatal_flaw_errors_total counter",
        f"fatal_flaw_errors_total {errors}",
        "",
        "# HELP fatal_flaw_latency_ms_p50 Median request latency",
        "# TYPE fatal_flaw_latency_ms_p50 gauge",
        f"fatal_flaw_latency_ms_p50 {p50}",
        "",
        "# HELP fatal_flaw_latency_ms_p95 95th percentile request latency",
        "# TYPE fatal_flaw_latency_ms_p95 gauge",
        f"fatal_flaw_latency_ms_p95 {p95}",
        "",
        "# HELP fatal_flaw_latency_ms_p99 99th percentile request latency",
        "# TYPE fatal_flaw_latency_ms_p99 gauge",
        f"fatal_flaw_latency_ms_p99 {p99}",
        "",
        "# HELP fatal_flaw_latency_ms_avg Average request latency",
        "# TYPE fatal_flaw_latency_ms_avg gauge",
        f"fatal_flaw_latency_ms_avg {avg}",
    ]
    return "\n".join(lines) + "\n"

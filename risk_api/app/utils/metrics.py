"""
risk_api/app/utils/metrics.py
Lightweight in-process metrics collection.
Exposed via GET /metrics in Prometheus text format.
For production, consider integrating prometheus_client.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Optional


class MetricsCollector:
    """Thread-safe metrics collector for request latency and error counts."""

    def __init__(self, window: int = 1000):
        self._lock = Lock()
        self._request_count: int = 0
        self._error_count: int = 0
        self._latencies: deque[float] = deque(maxlen=window)
        self._start_time: float = time.time()

    def record(self, latency_ms: float, is_error: bool = False) -> None:
        with self._lock:
            self._request_count += 1
            self._latencies.append(latency_ms)
            if is_error:
                self._error_count += 1

    def percentile(self, p: float) -> float:
        """Return the p-th percentile latency (e.g., p=0.95 for P95)."""
        with self._lock:
            lats = sorted(self._latencies)
        if not lats:
            return 0.0
        idx = int(len(lats) * p)
        return lats[min(idx, len(lats) - 1)]

    def average(self) -> float:
        with self._lock:
            lats = list(self._latencies)
        return sum(lats) / len(lats) if lats else 0.0

    def snapshot(self) -> dict:
        with self._lock:
            lats = sorted(self._latencies)
            count = self._request_count
            errors = self._error_count

        def pct(p):
            if not lats:
                return 0.0
            return lats[min(int(len(lats) * p), len(lats) - 1)]

        return {
            "request_count": count,
            "error_count": errors,
            "error_rate": errors / count if count else 0.0,
            "p50_ms": pct(0.50),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
            "avg_ms": sum(lats) / len(lats) if lats else 0.0,
            "uptime_seconds": int(time.time() - self._start_time),
        }

    def to_prometheus(self) -> str:
        s = self.snapshot()
        lines = [
            "# HELP fatal_flaw_requests_total Total HTTP requests processed",
            "# TYPE fatal_flaw_requests_total counter",
            f"fatal_flaw_requests_total {s['request_count']}",
            "",
            "# HELP fatal_flaw_errors_total Total HTTP errors",
            "# TYPE fatal_flaw_errors_total counter",
            f"fatal_flaw_errors_total {s['error_count']}",
            "",
            "# HELP fatal_flaw_latency_p50_ms Median request latency in milliseconds",
            "# TYPE fatal_flaw_latency_p50_ms gauge",
            f"fatal_flaw_latency_p50_ms {s['p50_ms']:.1f}",
            "",
            "# HELP fatal_flaw_latency_p95_ms 95th percentile request latency",
            "# TYPE fatal_flaw_latency_p95_ms gauge",
            f"fatal_flaw_latency_p95_ms {s['p95_ms']:.1f}",
            "",
            "# HELP fatal_flaw_latency_p99_ms 99th percentile request latency",
            "# TYPE fatal_flaw_latency_p99_ms gauge",
            f"fatal_flaw_latency_p99_ms {s['p99_ms']:.1f}",
            "",
            "# HELP fatal_flaw_uptime_seconds API uptime in seconds",
            "# TYPE fatal_flaw_uptime_seconds counter",
            f"fatal_flaw_uptime_seconds {s['uptime_seconds']}",
        ]
        return "\n".join(lines) + "\n"


# Singleton
metrics = MetricsCollector()

"""
risk_api/tests/locustfile.py
Locust load test for the Fatal Flaw Risk Assessment API.

Usage:
    # Interactive web UI (open http://localhost:8089)
    locust -f tests/locustfile.py --host http://localhost:8000

    # Headless: 10 users, 2 spawned/sec, run 60s
    locust -f tests/locustfile.py --host http://localhost:8000 \
           --users 10 --spawn-rate 2 --run-time 60s --headless

    # SLA check: fail if p95 > 500ms or error rate > 1%
    locust -f tests/locustfile.py --host http://localhost:8000 \
           --users 10 --spawn-rate 2 --run-time 30s --headless \
           --exit-code-on-error 1
"""

import random
import math
from locust import HttpUser, task, between, events


# ── Test site pool ────────────────────────────────────────────────────────────
# A mix of simple and complex polygons at different CONUS locations.

def _circle_polygon(cx: float, cy: float, radius_deg: float, n: int) -> list:
    """Generate an approximately circular polygon with n vertices."""
    coords = [
        [
            cx + radius_deg * math.cos(2 * math.pi * i / n),
            cy + radius_deg * math.sin(2 * math.pi * i / n),
        ]
        for i in range(n)
    ]
    coords.append(coords[0])   # close ring
    return [coords]


SITE_POOL = [
    # (name, site_type, geometry)
    (
        "Nevada Desert — simple",
        "solar",
        {"type": "Polygon", "coordinates": [[
            [-116.50, 38.80], [-116.45, 38.80],
            [-116.45, 38.85], [-116.50, 38.85],
            [-116.50, 38.80],
        ]]},
    ),
    (
        "Kansas Plains — solar",
        "solar",
        {"type": "Polygon", "coordinates": [[
            [-98.00, 38.50], [-97.90, 38.50],
            [-97.90, 38.60], [-98.00, 38.60],
            [-98.00, 38.50],
        ]]},
    ),
    (
        "Texas Panhandle — wind",
        "wind",
        {"type": "Polygon", "coordinates": [[
            [-101.80, 35.20], [-101.70, 35.20],
            [-101.70, 35.30], [-101.80, 35.30],
            [-101.80, 35.20],
        ]]},
    ),
    (
        "Colorado — BESS",
        "bess",
        {"type": "Polygon", "coordinates": [[
            [-105.00, 39.70], [-104.90, 39.70],
            [-104.90, 39.80], [-105.00, 39.80],
            [-105.00, 39.70],
        ]]},
    ),
    (
        "Virginia — datacenter",
        "datacenter",
        {"type": "Polygon", "coordinates": [[
            [-77.50, 38.90], [-77.40, 38.90],
            [-77.40, 39.00], [-77.50, 39.00],
            [-77.50, 38.90],
        ]]},
    ),
    (
        "Iowa Farmland — solar",
        "solar",
        {"type": "Polygon", "coordinates": [[
            [-93.00, 42.00], [-92.95, 42.00],
            [-92.95, 42.05], [-93.00, 42.05],
            [-93.00, 42.00],
        ]]},
    ),
    (
        "New Mexico — wind (100-vertex circle)",
        "wind",
        {"type": "Polygon", "coordinates": _circle_polygon(-106.5, 34.5, 0.08, 100)},
    ),
    (
        "Wyoming — solar (50-vertex circle)",
        "solar",
        {"type": "Polygon", "coordinates": _circle_polygon(-107.0, 43.0, 0.05, 50)},
    ),
    (
        "Montana — wind",
        "wind",
        {"type": "Polygon", "coordinates": [[
            [-109.50, 46.80], [-109.40, 46.80],
            [-109.40, 46.90], [-109.50, 46.90],
            [-109.50, 46.80],
        ]]},
    ),
    (
        "Arizona — solar (large site)",
        "solar",
        {"type": "Polygon", "coordinates": [[
            [-112.00, 33.00], [-111.80, 33.00],
            [-111.80, 33.20], [-112.00, 33.20],
            [-112.00, 33.00],
        ]]},
    ),
]


# ── Locust user ───────────────────────────────────────────────────────────────

class FatalFlawUser(HttpUser):
    """
    Simulates a user hitting the assess-site endpoint.
    Wait between 0.5s and 2s between requests to model realistic usage.
    """
    wait_time = between(0.5, 2.0)

    @task(10)
    def assess_random_site(self):
        """Main task: POST a random site from the pool."""
        name, site_type, geometry = random.choice(SITE_POOL)
        payload = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "site_name": name,
                "site_type": site_type,
            },
        }
        with self.client.post(
            "/api/v1/assess-site",
            json=payload,
            name="/api/v1/assess-site",   # group all variants under one label
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                proc_ms = data.get("processing_time_ms", 9999)
                if proc_ms > 500:
                    resp.failure(f"SLA breach: processing_time_ms={proc_ms} > 500ms")
                else:
                    resp.success()
            elif resp.status_code == 422:
                # Validation error — site outside CONUS or bad geometry
                resp.failure(f"Validation error: {resp.text[:200]}")
            else:
                resp.failure(f"Unexpected status {resp.status_code}: {resp.text[:200]}")

    @task(2)
    def health_check(self):
        """Lightweight health probe — lower frequency."""
        with self.client.get("/health", name="/health", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    @task(1)
    def assess_complex_polygon(self):
        """Stress test: 200-vertex polygon — must still meet 500ms SLA."""
        geometry = {
            "type": "Polygon",
            "coordinates": _circle_polygon(-105.5, 40.0, 0.10, 200),
        }
        payload = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {"site_name": "Stress Test 200-vertex", "site_type": "solar"},
        }
        with self.client.post(
            "/api/v1/assess-site",
            json=payload,
            name="/api/v1/assess-site [complex]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                proc_ms = resp.json().get("processing_time_ms", 9999)
                if proc_ms > 500:
                    resp.failure(f"SLA breach on complex polygon: {proc_ms}ms")
                else:
                    resp.success()
            else:
                resp.failure(f"Status {resp.status_code}")


# ── Custom pass/fail thresholds ───────────────────────────────────────────────

@events.quitting.add_listener
def check_sla(environment, **kwargs):
    """
    Fail the Locust run if SLA thresholds are breached.
    Triggered at end of headless run.
    """
    stats = environment.runner.stats.total

    p95 = stats.get_response_time_percentile(0.95)
    error_rate = stats.fail_ratio   # 0.0 – 1.0

    failures = []

    if p95 and p95 > 500:
        failures.append(f"P95 latency {p95:.0f}ms exceeds 500ms SLA")

    if error_rate > 0.01:
        failures.append(f"Error rate {error_rate*100:.1f}% exceeds 1% threshold")

    if stats.num_requests < 10:
        failures.append(f"Too few requests completed ({stats.num_requests}) — check API connectivity")

    if failures:
        print("\n❌ SLA FAILURES:")
        for f in failures:
            print(f"   • {f}")
        environment.process_exit_code = 1
    else:
        print(f"\n✅ SLA PASSED — P95: {p95:.0f}ms | Error rate: {error_rate*100:.1f}%")
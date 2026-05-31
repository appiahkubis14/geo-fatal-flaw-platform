"""
fatal_flaw_analyzer/api_client.py
HTTP client for the Fatal Flaw Risk Assessment API.
Uses QThread + requests for non-blocking calls from QGIS.
Implements retry with exponential backoff and result caching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Optional

import requests
from qgis.PyQt.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class ApiClient:
    """
    Synchronous HTTP client for the Fatal Flaw API.
    Wraps requests with retry logic, timeout, and simple in-memory cache.
    """

    def __init__(self, config: dict):
        self.base_url = config.get("api_url", "http://localhost:8000").rstrip("/")
        self.timeout = config.get("api_timeout", 30)
        self.max_retries = 3
        self.backoff_base = 2
        self._cache: dict[str, dict] = {}    # checksum → result

    def assess_site(
        self,
        geometry: dict,
        site_name: str = "Unnamed Site",
        site_type: str = "solar",
    ) -> dict:
        """
        POST /api/v1/assess-site and return the parsed response.
        Raises requests.RequestException on failure after all retries.
        """
        payload = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {"site_name": site_name, "site_type": site_type},
        }

        # Cache lookup
        cache_key = hashlib.sha256(
            json.dumps({"geometry": geometry, "site_type": site_type}, sort_keys=True).encode()
        ).hexdigest()
        if cache_key in self._cache:
            logger.debug("Cache hit for site geometry")
            return self._cache[cache_key]

        url = f"{self.base_url}/api/v1/assess-site"
        last_exc = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                result = resp.json()
                self._cache[cache_key] = result
                return result

            except requests.Timeout as exc:
                last_exc = exc
                logger.warning("API timeout on attempt %d/%d", attempt, self.max_retries)
            except requests.HTTPError as exc:
                # 4xx errors — don't retry (client error)
                if exc.response is not None and exc.response.status_code < 500:
                    detail = exc.response.json().get("detail", str(exc))
                    raise ValueError(f"API validation error: {detail}") from exc
                last_exc = exc
                logger.warning("API HTTP error %d on attempt %d", exc.response.status_code, attempt)
            except requests.ConnectionError as exc:
                last_exc = exc
                logger.warning("Connection error on attempt %d: %s", attempt, exc)

            if attempt < self.max_retries:
                sleep_s = self.backoff_base ** attempt
                logger.info("Retrying in %.0fs …", sleep_s)
                time.sleep(sleep_s)

        raise RuntimeError(
            f"API request failed after {self.max_retries} attempts. "
            f"Last error: {last_exc}. Check API URL: {url}"
        )

    def health_check(self) -> bool:
        """Return True if the API is reachable and healthy."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def get_weights(self, site_type: str = "solar", api_key: str = "") -> Optional[dict]:
        """Retrieve current weights for a site type (requires admin API key)."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/weights",
                params={"site_type": site_type},
                headers={"X-API-Key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Could not fetch weights: %s", exc)
            return None


class AssessmentWorker(QThread):
    """
    QThread worker that runs the API call off the main QGIS thread.
    Emits `finished(dict)` on success or `error(str)` on failure.
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        api_client: ApiClient,
        geometry: dict,
        site_name: str,
        site_type: str,
        parent=None,
    ):
        super().__init__(parent)
        self.api_client = api_client
        self.geometry = geometry
        self.site_name = site_name
        self.site_type = site_type

    def run(self):
        try:
            result = self.api_client.assess_site(
                geometry=self.geometry,
                site_name=self.site_name,
                site_type=self.site_type,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))

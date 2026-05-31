"""
etl_pipeline/base/etl_base.py
Abstract base class for all 15 constraint layer ETL loaders.
Provides: download with retry/checksum, reprojection, PostGIS loading,
          progress tracking, and audit logging.
"""

from __future__ import annotations

import abc
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import geopandas as gpd
import psycopg2
import requests
import yaml
from pyproj import CRS
from shapely.validation import make_valid
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# ── CRS Constants ────────────────────────────────────────────────────────────
CRS_5070 = CRS.from_epsg(5070)   # CONUS Albers — analysis
CRS_4326 = CRS.from_epsg(4326)   # WGS84 — display / QGIS

SQ_M_TO_ACRES = 0.000247105


class ETLBase(abc.ABC):
    """
    Abstract base class for Fatal Flaw constraint layer ETL loaders.

    Subclasses must implement:
        - layer_name (property)
        - download(dest_dir) -> Path
        - process(raw_path) -> gpd.GeoDataFrame
    """

    # ── Subclass contract ────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def layer_name(self) -> str:
        """Matches the layer_name column in constraint_registry."""

    @abc.abstractmethod
    def download(self, dest_dir: Path) -> Path:
        """
        Download raw data to dest_dir.
        Returns path to the downloaded file/directory.
        """

    @abc.abstractmethod
    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        """
        Read raw_path, clean geometry, apply attribute mapping.
        Returns GeoDataFrame in EPSG:5070 with required columns.
        """

    # ── Initialization ───────────────────────────────────────────────────────

    def __init__(self, config: dict, db_url: str):
        self.config = config
        self.db_url = db_url
        self.layer_config: dict = config["layers"].get(self.layer_name, {})
        self.data_dir = Path(config["storage"]["data_dir"]) / self.layer_name
        self.cache_dir = Path(config["storage"]["cache_dir"]) / self.layer_name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.retry_attempts: int = config["processing"]["retry_attempts"]
        self.retry_backoff: int = config["processing"]["retry_backoff_base"]
        self.chunk_size: int = config["processing"]["chunk_size_bytes"]
        self.download_timeout: int = config["processing"]["download_timeout_seconds"]
        self.rate_limit_delay: float = config["processing"]["rate_limit_delay"]

        self._run_id = str(uuid4())
        self._engine = create_engine(db_url, pool_pre_ping=True)

    # ── Public run method ────────────────────────────────────────────────────

    def run(self, force: bool = False) -> dict[str, Any]:
        """
        Full ETL: download → process → load → index.
        Returns a summary dict for the audit log.
        """
        self._log_start()
        summary = {
            "layer_name": self.layer_name,
            "run_id": self._run_id,
            "rows_loaded": 0,
            "rows_failed": 0,
            "status": "failed",
        }

        try:
            # 1. Check cache
            raw_path = self._check_cache(force)
            if raw_path is None:
                logger.info("[%s] Downloading data …", self.layer_name)
                raw_path = self.download(self.data_dir)
                self._cache_checksum(raw_path)
            else:
                logger.info("[%s] Using cached data at %s", self.layer_name, raw_path)

            # 2. Process / reproject
            logger.info("[%s] Processing geometry …", self.layer_name)
            gdf = self.process(raw_path)
            if gdf is None or gdf.empty:
                raise ValueError("process() returned empty GeoDataFrame")

            gdf = self._ensure_schema(gdf)

            # 3. Load into PostGIS
            logger.info("[%s] Loading %d features into PostGIS …", self.layer_name, len(gdf))
            rows_loaded, rows_failed = self._load_to_postgis(gdf, force)
            summary["rows_loaded"] = rows_loaded
            summary["rows_failed"] = rows_failed

            # 4. Refresh spatial indexes (VACUUM ANALYZE)
            self._refresh_index()

            summary["status"] = "success"
            logger.info(
                "[%s] ✓ Loaded %d rows (%d failed)",
                self.layer_name, rows_loaded, rows_failed,
            )

        except Exception as exc:
            summary["error_message"] = str(exc)
            logger.exception("[%s] ETL failed: %s", self.layer_name, exc)
        finally:
            self._log_finish(summary)

        return summary

    # ── Download helpers ─────────────────────────────────────────────────────

    def download_file(
        self,
        url: str,
        dest: Path,
        expected_checksum: Optional[str] = None,
    ) -> Path:
        """
        Download url → dest with retry, progress logging, and optional checksum.
        Supports chunked streaming for large files.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.retry_attempts + 1):
            try:
                logger.info(
                    "[%s] Downloading (attempt %d/%d): %s",
                    self.layer_name, attempt, self.retry_attempts, url,
                )
                with requests.get(
                    url,
                    stream=True,
                    timeout=self.download_timeout,
                    headers={"User-Agent": "FatalFlawETL/1.0 (contact@example.com)"},
                ) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    hasher = hashlib.sha256()
                    with open(dest, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=self.chunk_size):
                            fh.write(chunk)
                            hasher.update(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = downloaded / total * 100
                                if downloaded % (50 * self.chunk_size) == 0:
                                    logger.debug(
                                        "[%s] … %.1f%% (%.1f MB)",
                                        self.layer_name, pct, downloaded / 1e6,
                                    )

                actual_checksum = hasher.hexdigest()
                if expected_checksum and actual_checksum != expected_checksum:
                    raise ValueError(
                        f"Checksum mismatch: expected {expected_checksum}, got {actual_checksum}"
                    )

                logger.info("[%s] Download complete: %s (%.1f MB)", self.layer_name, dest, downloaded / 1e6)
                time.sleep(self.rate_limit_delay)
                return dest

            except (requests.RequestException, ValueError, OSError) as exc:
                logger.warning("[%s] Attempt %d failed: %s", self.layer_name, attempt, exc)
                if dest.exists():
                    dest.unlink()
                if attempt < self.retry_attempts:
                    sleep_s = self.retry_backoff ** attempt
                    logger.info("[%s] Retrying in %.0fs …", self.layer_name, sleep_s)
                    time.sleep(sleep_s)
                else:
                    raise RuntimeError(
                        f"[{self.layer_name}] Download failed after {self.retry_attempts} attempts: {url}"
                    ) from exc

    def extract_zip(self, zip_path: Path, dest_dir: Optional[Path] = None) -> Path:
        """Extract a zip archive, returning the extraction directory."""
        dest_dir = dest_dir or zip_path.parent / zip_path.stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest_dir)
        logger.debug("[%s] Extracted %s → %s", self.layer_name, zip_path.name, dest_dir)
        return dest_dir

    def find_file(self, directory: Path, extensions: list[str]) -> Optional[Path]:
        """Recursively find first file with one of the given extensions."""
        for ext in extensions:
            matches = sorted(directory.rglob(f"*{ext}"))
            if matches:
                return matches[0]
        return None

    # ── Geometry helpers ─────────────────────────────────────────────────────

    def reproject(self, gdf: gpd.GeoDataFrame, target_crs: CRS) -> gpd.GeoDataFrame:
        """Reproject GeoDataFrame to target CRS, handling mixed CRS inputs."""
        if gdf.crs is None:
            logger.warning("[%s] GDF has no CRS — assuming EPSG:4326", self.layer_name)
            gdf = gdf.set_crs(CRS_4326)
        if gdf.crs != target_crs:
            gdf = gdf.to_crs(target_crs)
        return gdf

    def fix_geometries(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Make all geometries valid using Shapely 2.x make_valid().
        Removes null geometries and empty geometries.
        """
        before = len(gdf)
        gdf = gdf[~gdf.geometry.isna()].copy()
        gdf = gdf[~gdf.geometry.is_empty].copy()
        gdf["geometry"] = gdf["geometry"].apply(make_valid)
        gdf = gdf[~gdf.geometry.is_empty].copy()
        removed = before - len(gdf)
        if removed:
            logger.warning("[%s] Removed %d invalid/null geometries", self.layer_name, removed)
        return gdf

    def subdivide_large(self, gdf: gpd.GeoDataFrame, max_vertices: int = 256) -> gpd.GeoDataFrame:
        """
        Use ST_Subdivide via PostGIS for very large multi-part geometries.
        This is a pre-load hint; actual subdivision handled in PostGIS view if needed.
        """
        return gdf  # actual subdivision done in PostGIS for performance

    # ── Schema enforcement ───────────────────────────────────────────────────

    def _ensure_schema(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Ensure required columns exist, add geom_4326 column,
        and validate geometry types.
        """
        # Ensure in EPSG:5070 for storage
        gdf = self.reproject(gdf, CRS_5070)
        gdf = self.fix_geometries(gdf)

        # Add metadata columns if missing
        defaults = {
            "layer_name": self.layer_name,
            "source": self.layer_config.get("download_url", ""),
            "acquisition_date": date.today(),
            "fatal_flag": False,
            "weight_default": self.layer_config.get("weight_default", 0.25),
            "notes": None,
        }
        for col, val in defaults.items():
            if col not in gdf.columns:
                gdf[col] = val

        # Create 4326 geometry column
        gdf_4326 = gdf.to_crs(CRS_4326)
        gdf["geom_4326"] = gdf_4326.geometry

        return gdf

    # ── PostGIS loading ──────────────────────────────────────────────────────

    def _load_to_postgis(
        self,
        gdf: gpd.GeoDataFrame,
        force: bool = False,
    ) -> tuple[int, int]:
        """
        Load GeoDataFrame into the layer's PostGIS table.
        Uses TRUNCATE + INSERT for idempotent operation when force=True.
        Returns (rows_loaded, rows_failed).
        """
        table = self.layer_name
        schema = "constraints"

        if force:
            with self._engine.connect() as conn:
                conn.execute(text(f'TRUNCATE TABLE {schema}."{table}" RESTART IDENTITY CASCADE'))
                conn.commit()
                logger.info("[%s] Truncated existing table", self.layer_name)

        rows_loaded = 0
        rows_failed = 0
        batch_size = 1000

        # Rename geometry column for geopandas to_postgis
        gdf_load = gdf.copy()
        gdf_load = gdf_load.rename_geometry("geom")

        # Drop geom_4326 (stored as WKT, re-inserted via SQL after load)
        geom_4326_wkt = gdf_load["geom_4326"].apply(lambda g: g.wkt if g else None)
        gdf_load = gdf_load.drop(columns=["geom_4326"], errors="ignore")

        try:
            gdf_load.to_postgis(
                table,
                self._engine,
                schema=schema,
                if_exists="append",
                index=False,
                chunksize=batch_size,
            )
            rows_loaded = len(gdf_load)
        except Exception as exc:
            logger.error("[%s] to_postgis failed: %s", self.layer_name, exc)
            rows_failed = len(gdf_load)
            raise

        # Back-fill geom_4326 using PostGIS ST_Transform
        with self._engine.connect() as conn:
            conn.execute(text(
                f"""
                UPDATE {schema}."{table}"
                SET geom_4326 = ST_Transform(geom, 4326)
                WHERE geom_4326 IS NULL
                """
            ))
            conn.commit()

        return rows_loaded, rows_failed

    # ── Index management ─────────────────────────────────────────────────────

    def _refresh_index(self) -> None:
        """VACUUM ANALYZE the layer table to update planner statistics."""
        with psycopg2.connect(self.db_url) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'VACUUM ANALYZE constraints."{self.layer_name}"')
        logger.debug("[%s] VACUUM ANALYZE complete", self.layer_name)

    # ── Cache management ─────────────────────────────────────────────────────

    def _check_cache(self, force: bool) -> Optional[Path]:
        """Return cached raw file path if valid and not forced re-download."""
        if force:
            return None
        checksum_file = self.cache_dir / f"{self.layer_name}.sha256"
        data_marker = self.cache_dir / f"{self.layer_name}.downloaded"
        if checksum_file.exists() and data_marker.exists():
            cached_path_str = data_marker.read_text().strip()
            cached_path = Path(cached_path_str)
            if cached_path.exists():
                logger.info("[%s] Cache hit: %s", self.layer_name, cached_path)
                return cached_path
        return None

    def _cache_checksum(self, file_path: Path) -> None:
        """Write a cache marker and checksum for a downloaded file."""
        marker = self.cache_dir / f"{self.layer_name}.downloaded"
        marker.write_text(str(file_path))
        # Write checksum only for files < 500MB (avoid hashing huge rasters)
        if file_path.is_file() and file_path.stat().st_size < 500_000_000:
            checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
            (self.cache_dir / f"{self.layer_name}.sha256").write_text(checksum)

    # ── Audit logging ────────────────────────────────────────────────────────

    def _log_start(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(text(
                """
                INSERT INTO audit.etl_log (layer_name, run_id, status, source_url)
                VALUES (:layer, :run_id, 'running', :url)
                """
            ), {"layer": self.layer_name, "run_id": self._run_id,
                "url": self.layer_config.get("download_url", "")})
            conn.commit()

    def _log_finish(self, summary: dict) -> None:
        with self._engine.connect() as conn:
            conn.execute(text(
                """
                UPDATE audit.etl_log
                SET finished_at   = NOW(),
                    status        = :status,
                    rows_loaded   = :rows_loaded,
                    rows_failed   = :rows_failed,
                    error_message = :error
                WHERE run_id = :run_id
                """
            ), {
                "status": summary.get("status", "failed"),
                "rows_loaded": summary.get("rows_loaded", 0),
                "rows_failed": summary.get("rows_failed", 0),
                "error": summary.get("error_message"),
                "run_id": self._run_id,
            })
            conn.commit()


# ── Config loader utility ────────────────────────────────────────────────────

def load_config(config_path: Optional[str] = None) -> dict:
    """Load and expand environment variables in config.yaml."""
    import re

    path = config_path or Path(__file__).parent.parent / "config.yaml"
    with open(path) as fh:
        raw = fh.read()

    # Expand ${VAR:-default} patterns
    def expand(match: re.Match) -> str:
        var, _, default = match.group(1).partition(":-")
        return os.environ.get(var, default)

    expanded = re.sub(r"\$\{([^}]+)\}", expand, raw)
    return yaml.safe_load(expanded)

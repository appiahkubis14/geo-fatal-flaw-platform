"""
risk_api/app/services/risk_engine.py
Weighted risk scoring engine.
Converts raw spatial query results into a normalized 0-100 risk score
with fatal flag detection, layer contribution scores, and top-5 risk ranking.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.models.site import (
    LayerResult,
    SiteAssessmentResponse,
    TopRisk,
)
from app.services.database import DatabasePool
from app.services.spatial_queries import (
    LayerQueryResult,
    SQ_M_TO_ACRES,
    check_fatal_quick,
    get_site_area_m2,
    query_all_layers,
    reproject_geojson_to_5070,
)

logger = logging.getLogger(__name__)

# Maximum search radius for proximity layers (meters). Beyond this = 0 risk contribution.
PROXIMITY_MAX_RADIUS_M = 8046.0   # 5 miles


class RiskEngine:
    """
    Loads weights from DB, runs spatial queries, computes risk scores.
    Thread-safe via asyncio; weights cached in memory and refreshed periodically.
    """

    def __init__(self, db: DatabasePool):
        self._db = db
        self._weights: dict[tuple[str, str], float] = {}  # (layer_name, site_type) → weight
        self._weights_loaded_at: Optional[datetime] = None
        self._refresh_lock = asyncio.Lock()

    # ── Weight management ────────────────────────────────────────────────────

    async def load_weights(self) -> None:
        """Load all weights from DB into memory."""
        rows = await self._db.fetch(
            "SELECT layer_name, site_type, weight FROM constraints.risk_weights"
        )
        self._weights = {(r["layer_name"], r["site_type"]): r["weight"] for r in rows}
        self._weights_loaded_at = datetime.now(timezone.utc)
        logger.info("Loaded %d weight entries from DB", len(self._weights))

    async def maybe_refresh_weights(self, max_age_seconds: int = 300) -> None:
        """Refresh weights if stale (non-blocking; skips if lock held)."""
        if self._weights_loaded_at is None:
            await self.load_weights()
            return
        age = (datetime.now(timezone.utc) - self._weights_loaded_at).total_seconds()
        if age > max_age_seconds:
            if self._refresh_lock.locked():
                return  # another coroutine is refreshing
            async with self._refresh_lock:
                await self.load_weights()

    def get_weight(self, layer_name: str, site_type: str) -> float:
        """Get weight for layer+site_type, falling back to 'default' profile."""
        key = (layer_name, site_type)
        if key in self._weights:
            return self._weights[key]
        default_key = (layer_name, "default")
        if default_key in self._weights:
            return self._weights[default_key]
        logger.warning("No weight found for (%s, %s) — using 0.25", layer_name, site_type)
        return 0.25

    # ── Main assessment pipeline ─────────────────────────────────────────────

    async def assess_site(
        self,
        geojson_geometry: dict,
        site_name: str,
        site_type: str,
    ) -> SiteAssessmentResponse:
        """
        Full assessment pipeline:
        1. Reproject GeoJSON to EPSG:5070
        2. Compute site area
        3. Quick fatal check (materialized view)
        4. Full per-layer spatial queries (concurrent)
        5. Score calculation
        6. Assemble response
        """
        t_start = time.perf_counter()
        await self.maybe_refresh_weights()

        import json
        geojson_str = json.dumps(geojson_geometry)

        # Step 1: Reproject to EPSG:5070
        site_wkb = await reproject_geojson_to_5070(self._db, geojson_str)

        # Step 2: Site area
        site_area_m2 = await get_site_area_m2(self._db, site_wkb)
        site_area_acres = site_area_m2 * SQ_M_TO_ACRES

        # Step 3: Quick fatal check
        is_fatal_quick, fatal_layer_names = await check_fatal_quick(self._db, site_wkb)

        # Step 4: Full layer queries (all 15 concurrent)
        layer_results_raw = await query_all_layers(self._db, site_wkb, site_area_m2)

        # Step 5: Score
        layer_results, overall_score, fatal_flag, fatal_layers = self._compute_scores(
            layer_results_raw, site_area_m2, site_type
        )

        # Top 5 by contribution score
        sorted_results = sorted(layer_results, key=lambda r: r.contribution_score, reverse=True)
        top_risks = [
            TopRisk(
                layer_name=r.layer_name,
                category=r.category,
                impact_area_acres=r.intersection_area_acres,
                percentage_of_site=r.percentage_of_site,
                contribution_score=r.contribution_score,
                weight=r.weight,
                is_fatal=r.is_fatal,
                min_distance_meters=r.min_distance_meters,
            )
            for r in sorted_results[:5]
            if r.contribution_score > 0
        ]

        processing_time_ms = int((time.perf_counter() - t_start) * 1000)

        return SiteAssessmentResponse(
            assessment_id=uuid4(),
            site_name=site_name,
            site_type=site_type,
            assessment_timestamp=datetime.now(timezone.utc),
            overall_risk_score=round(overall_score, 2),
            fatal_flag=fatal_flag,
            fatal_layers=fatal_layers,
            top_risks=top_risks,
            all_layer_results=layer_results,
            site_area_acres=round(site_area_acres, 2),
            processing_time_ms=processing_time_ms,
        )

    # ── Scoring logic ────────────────────────────────────────────────────────

    def _compute_scores(
        self,
        raw_results: list[LayerQueryResult],
        site_area_m2: float,
        site_type: str,
    ) -> tuple[list[LayerResult], float, bool, list[str]]:
        """
        Compute contribution score for each layer and aggregate to overall score.

        Scoring model:
        - Intersect layers:   score = weight * (intersection_area / site_area)
                              Capped at weight (100% overlap = full weight contribution).
        - Proximity layers:   score = weight * (1 - distance/max_radius)
                              Inverted: closer = higher score for grid layers (favorable proximity)
                              OR: farther = higher score for contaminated sites (hazard proximity)
        - Buffer layers:      score = weight * (buffer_overlap_area / site_area)

        Overall risk = sum(scores) / sum(max_possible_scores) * 100, normalized 0-100.
        Fatal flag automatically pushes score >= 75.
        """
        site_area_m2 = max(site_area_m2, 1.0)  # avoid division by zero

        layer_results: list[LayerResult] = []
        total_weighted_score = 0.0
        max_possible_score = 0.0
        fatal_flag = False
        fatal_layers: list[str] = []

        for r in raw_results:
            weight = self.get_weight(r.layer_name, site_type)
            max_possible_score += weight

            intersection_area_acres = r.intersection_area_m2 * SQ_M_TO_ACRES
            pct_of_site = min((r.intersection_area_m2 / site_area_m2) * 100, 100.0)

            # ── Contribution score ────────────────────────────────────────
            if r.analysis_type == "intersect" and r.intersects:
                impact_ratio = min(r.intersection_area_m2 / site_area_m2, 1.0)
                contribution = weight * impact_ratio

            elif r.analysis_type == "proximity":
                # Grid infrastructure (transmission, substations): invert — closer = lower risk
                # Contaminated sites: closer = higher risk (not inverted)
                is_favorable_proximity = r.layer_name in ("transmission_lines", "substations")
                if r.min_distance_m is not None:
                    dist_ratio = min(r.min_distance_m / PROXIMITY_MAX_RADIUS_M, 1.0)
                    if is_favorable_proximity:
                        # Farther from grid = higher risk
                        contribution = weight * dist_ratio
                    else:
                        # Closer to hazard = higher risk
                        contribution = weight * (1.0 - dist_ratio)
                else:
                    # Beyond search radius
                    contribution = weight if is_favorable_proximity else 0.0

            elif r.analysis_type == "buffer" and r.intersects:
                impact_ratio = min(r.intersection_area_m2 / site_area_m2, 1.0)
                contribution = weight * max(impact_ratio, 0.5)  # buffer hit = at least 50% weight

            else:
                contribution = 0.0

            total_weighted_score += contribution

            # ── Fatal flag ────────────────────────────────────────────────
            layer_triggered_fatal = r.intersects and r.fatal_flag
            if layer_triggered_fatal:
                fatal_flag = True
                fatal_layers.append(r.layer_name)

            layer_results.append(LayerResult(
                layer_name=r.layer_name,
                category=r.category,
                analysis_type=r.analysis_type,
                intersects=r.intersects,
                intersection_area_acres=round(intersection_area_acres, 3),
                percentage_of_site=round(pct_of_site, 2),
                min_distance_meters=round(r.min_distance_m, 1) if r.min_distance_m is not None else None,
                contribution_score=round(contribution * 100, 2),   # scale to 0-100
                weight=weight,
                is_fatal=r.fatal_flag,
                fatal_triggered=layer_triggered_fatal,
            ))

        # ── Normalize overall score 0-100 ────────────────────────────────
        if max_possible_score > 0:
            overall_score = (total_weighted_score / max_possible_score) * 100
        else:
            overall_score = 0.0

        overall_score = min(overall_score, 100.0)

        # Fatal sites: ensure score >= 75
        if fatal_flag and overall_score < 75.0:
            overall_score = 75.0

        return layer_results, overall_score, fatal_flag, fatal_layers

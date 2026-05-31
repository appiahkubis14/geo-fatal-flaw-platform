"""
risk_api/app/services/validation.py
GeoJSON input validation — geometry, bounds, and area checks.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException
from shapely.geometry import shape, mapping
from shapely.validation import make_valid, explain_validity

from app.config import settings

logger = logging.getLogger(__name__)

# CONUS bounding box (approx)
CONUS_BBOX = (-125.0, 24.0, -66.0, 50.0)   # (west, south, east, north)

SQ_M_TO_ACRES = 0.000247105


def validate_geojson_geometry(geometry: dict) -> dict:
    """
    Validate and normalize input GeoJSON geometry.
    Returns cleaned geometry dict or raises HTTPException.
    """
    try:
        shp = shape(geometry)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid GeoJSON geometry: {exc}",
        )

    if shp.is_empty:
        raise HTTPException(status_code=422, detail="Geometry is empty")

    # Attempt repair
    if not shp.is_valid:
        validity_reason = explain_validity(shp)
        logger.warning("Repairing invalid geometry: %s", validity_reason)
        shp = make_valid(shp)
        if not shp.is_valid or shp.is_empty:
            raise HTTPException(
                status_code=422,
                detail=f"Geometry could not be repaired: {validity_reason}",
            )

    # Type check
    allowed_types = {"Polygon", "MultiPolygon"}
    if shp.geom_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"Geometry must be Polygon or MultiPolygon, got {shp.geom_type}",
        )

    # CONUS bounds check
    minx, miny, maxx, maxy = shp.bounds
    if not (
        CONUS_BBOX[0] <= minx and maxx <= CONUS_BBOX[2]
        and CONUS_BBOX[1] <= miny and maxy <= CONUS_BBOX[3]
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Site geometry is outside CONUS bounds "
                f"({CONUS_BBOX[0]}W, {CONUS_BBOX[1]}N, {CONUS_BBOX[2]}E, {CONUS_BBOX[3]}N). "
                f"Got bbox: ({minx:.4f}, {miny:.4f}, {maxx:.4f}, {maxy:.4f})"
            ),
        )

    # Area estimate in acres (approximate using geographic degrees — precise calc in PostGIS)
    # 1 degree latitude ≈ 111km; use centroid latitude for correction
    centroid_lat = shp.centroid.y
    import math
    lat_m_per_deg = 111_132.0
    lon_m_per_deg = 111_132.0 * math.cos(math.radians(centroid_lat))
    area_m2_approx = shp.area * lat_m_per_deg * lon_m_per_deg
    area_acres_approx = area_m2_approx * SQ_M_TO_ACRES

    if area_acres_approx < settings.min_site_acres:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Site area ({area_acres_approx:.2f} acres) is below minimum "
                f"({settings.min_site_acres} acres)"
            ),
        )

    if area_acres_approx > settings.max_site_acres:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Site area (~{area_acres_approx:,.0f} acres) exceeds maximum "
                f"({settings.max_site_acres:,.0f} acres)"
            ),
        )

    # Return potentially repaired geometry
    return mapping(shp)

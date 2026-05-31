"""
risk_api/app/utils/geojson_helpers.py
Utility functions for GeoJSON manipulation and reprojection.
"""

from __future__ import annotations

import json
from typing import Any

from shapely.geometry import mapping, shape
from shapely.ops import transform
from pyproj import Transformer

# Pre-build transformers (reusable, thread-safe)
_T_4326_to_5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
_T_5070_to_4326 = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)

SQ_M_TO_ACRES = 0.000247105


def geojson_to_wkt_5070(geojson_geometry: dict) -> str:
    """Convert a GeoJSON geometry dict (EPSG:4326) to WKT in EPSG:5070."""
    shp = shape(geojson_geometry)
    projected = transform(_T_4326_to_5070.transform, shp)
    return projected.wkt


def estimate_area_acres(geojson_geometry: dict) -> float:
    """
    Estimate polygon area in acres by projecting to EPSG:5070.
    Uses Shapely locally — exact area computed in PostGIS during assessment.
    """
    shp = shape(geojson_geometry)
    projected = transform(_T_4326_to_5070.transform, shp)
    return projected.area * SQ_M_TO_ACRES


def geojson_to_json_str(geometry: dict) -> str:
    """Serialize a geometry dict to a compact JSON string for PostGIS."""
    return json.dumps(geometry, separators=(",", ":"))


def bbox_from_geojson(geometry: dict) -> tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) bounding box of a GeoJSON geometry."""
    shp = shape(geometry)
    return shp.bounds   # (minx, miny, maxx, maxy)

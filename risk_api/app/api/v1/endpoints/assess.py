"""
risk_api/app/api/v1/endpoints/assess.py
POST /api/v1/assess-site — main risk assessment endpoint.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.models.site import SiteAssessmentRequest, SiteAssessmentResponse
from app.services.risk_engine import RiskEngine
from app.services.validation import validate_geojson_geometry

logger = logging.getLogger(__name__)

router = APIRouter()


def get_risk_engine(request: Request) -> RiskEngine:
    return request.app.state.risk_engine


@router.post(
    "/assess-site",
    response_model=SiteAssessmentResponse,
    summary="Assess site risk",
    description=(
        "Submit a GeoJSON polygon or multipolygon representing a candidate project site. "
        "Returns a risk score (0-100), fatal flag, and per-layer breakdown across 15 "
        "geospatial constraint layers. Response time target: <500ms."
    ),
    responses={
        200: {"description": "Risk assessment complete"},
        400: {"description": "Invalid request"},
        422: {"description": "Validation error (bad geometry, out of bounds, area limits)"},
        500: {"description": "Internal error"},
    },
)
async def assess_site(
    request_body: SiteAssessmentRequest,
    engine: RiskEngine = Depends(get_risk_engine),
) -> SiteAssessmentResponse:
    """
    Assess a project site against all 15 constraint layers.

    **Request:** GeoJSON Feature with Polygon or MultiPolygon geometry.

    **Properties:**
    - `site_name`: Optional human-readable name
    - `site_type`: `solar` | `wind` | `bess` | `datacenter` (affects weight profile)

    **Response:**
    - `overall_risk_score`: 0–100 (higher = riskier)
    - `fatal_flag`: true if any fatal constraint is intersected
    - `top_risks`: top 5 constraints by contribution score
    - `all_layer_results`: full per-layer breakdown
    - `processing_time_ms`: server-side processing time
    """
    # Validate and clean geometry
    cleaned_geometry = validate_geojson_geometry(request_body.geometry.model_dump())

    result = await engine.assess_site(
        geojson_geometry=cleaned_geometry,
        site_name=request_body.site_name,
        site_type=request_body.site_type,
    )
    return result

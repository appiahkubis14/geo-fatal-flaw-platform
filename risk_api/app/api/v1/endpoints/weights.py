"""
risk_api/app/api/v1/endpoints/weights.py
Admin endpoints for reading and updating risk weights.
Secured via API key header: X-API-Key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings
from app.models.site import WeightEntry, WeightsResponse, WeightUpdateRequest
from app.services.risk_engine import RiskEngine

logger = logging.getLogger(__name__)

router = APIRouter()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def require_api_key(api_key: str = Security(api_key_header)) -> str:
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


def get_risk_engine(request: Request) -> RiskEngine:
    return request.app.state.risk_engine


def get_db(request: Request):
    return request.app.state.db_pool


@router.get(
    "/weights",
    response_model=WeightsResponse,
    summary="Get risk weights (admin)",
    description="Retrieve the current weight profile for a given site type.",
)
async def get_weights(
    site_type: str = "default",
    engine: RiskEngine = Depends(get_risk_engine),
    _key: str = Depends(require_api_key),
) -> WeightsResponse:
    weights = {
        layer: engine.get_weight(layer, site_type)
        for (l, s), w in engine._weights.items()
        for layer in [l]
        if s == site_type
    }
    # Build clean dict
    weights_out = {}
    seen = set()
    for (layer, st), w in engine._weights.items():
        if st == site_type and layer not in seen:
            weights_out[layer] = w
            seen.add(layer)

    return WeightsResponse(
        site_type=site_type,
        weights=weights_out,
        last_updated=engine._weights_loaded_at,
    )


@router.put(
    "/weights",
    summary="Update risk weights (admin)",
    description=(
        "Update one or more risk weight entries. "
        "Changes take effect immediately (in-memory) and are persisted to the database. "
        "Requires X-API-Key header."
    ),
)
async def update_weights(
    body: WeightUpdateRequest,
    engine: RiskEngine = Depends(get_risk_engine),
    db=Depends(get_db),
    _key: str = Depends(require_api_key),
) -> dict:
    from sqlalchemy import text

    updated = []
    async with engine._db.pool.acquire() as conn:
        for entry in body.updates:
            await conn.execute(
                """
                INSERT INTO constraints.risk_weights (layer_name, site_type, weight, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (layer_name, site_type)
                DO UPDATE SET weight = EXCLUDED.weight, updated_at = NOW()
                """,
                entry.layer_name, entry.site_type, entry.weight,
            )
            # Update in-memory cache immediately
            engine._weights[(entry.layer_name, entry.site_type)] = entry.weight
            updated.append(f"{entry.layer_name}/{entry.site_type}={entry.weight}")

    logger.info("Weights updated: %s", updated)
    return {"updated": updated, "count": len(updated)}

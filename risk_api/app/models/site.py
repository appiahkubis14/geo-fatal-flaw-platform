"""
risk_api/app/models/site.py
Pydantic request/response models for the assessment endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# ── GeoJSON Input ─────────────────────────────────────────────────────────────

class GeoJSONGeometry(BaseModel):
    type: str
    coordinates: Any

    @field_validator("type")
    @classmethod
    def must_be_polygon(cls, v: str) -> str:
        allowed = {"Polygon", "MultiPolygon"}
        if v not in allowed:
            raise ValueError(f"Geometry type must be Polygon or MultiPolygon, got '{v}'")
        return v


class SiteProperties(BaseModel):
    site_name: Optional[str] = Field(None, max_length=255)
    site_type: Optional[str] = Field("solar", pattern=r"^(solar|wind|bess|datacenter)$")

    @field_validator("site_type", mode="before")
    @classmethod
    def default_site_type(cls, v):
        if v is None:
            return "solar"
        return v.lower()


class SiteAssessmentRequest(BaseModel):
    """
    GeoJSON Feature with Polygon or MultiPolygon geometry.

    Example::

        {
          "type": "Feature",
          "geometry": {
            "type": "Polygon",
            "coordinates": [[[-100, 40], [-99, 40], [-99, 41], [-100, 41], [-100, 40]]]
          },
          "properties": {
            "site_name": "My Solar Site",
            "site_type": "solar"
          }
        }
    """

    type: str = Field("Feature", pattern="^Feature$")
    geometry: GeoJSONGeometry
    properties: Optional[SiteProperties] = None

    @model_validator(mode="after")
    def validate_coordinates(self) -> "SiteAssessmentRequest":
        geom = self.geometry
        if geom.type == "Polygon":
            rings = geom.coordinates
            if not rings or len(rings[0]) < 4:
                raise ValueError("Polygon must have at least 4 coordinate pairs (closed ring)")
        elif geom.type == "MultiPolygon":
            for poly in geom.coordinates:
                if not poly or len(poly[0]) < 4:
                    raise ValueError("Each polygon in MultiPolygon must have ≥4 coordinate pairs")
        return self

    @property
    def site_name(self) -> str:
        if self.properties and self.properties.site_name:
            return self.properties.site_name
        return "Unnamed Site"

    @property
    def site_type(self) -> str:
        if self.properties and self.properties.site_type:
            return self.properties.site_type
        return "solar"


# ── Assessment Response ───────────────────────────────────────────────────────

class LayerResult(BaseModel):
    layer_name: str
    category: str
    analysis_type: str                    # intersect | proximity | buffer
    intersects: bool
    intersection_area_acres: float = 0.0
    percentage_of_site: float = 0.0
    min_distance_meters: Optional[float] = None
    contribution_score: float = 0.0
    weight: float
    is_fatal: bool
    fatal_triggered: bool = False         # True if this layer triggered the fatal flag


class TopRisk(BaseModel):
    layer_name: str
    category: str
    impact_area_acres: float
    percentage_of_site: float
    contribution_score: float
    weight: float
    is_fatal: bool
    min_distance_meters: Optional[float] = None


class SiteAssessmentResponse(BaseModel):
    assessment_id: UUID
    site_name: str
    site_type: str
    assessment_timestamp: datetime
    overall_risk_score: float = Field(ge=0.0, le=100.0)
    fatal_flag: bool
    fatal_layers: list[str] = Field(default_factory=list)
    top_risks: list[TopRisk]
    all_layer_results: list[LayerResult]
    site_area_acres: float
    processing_time_ms: int

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


# ── Weights ───────────────────────────────────────────────────────────────────

class WeightEntry(BaseModel):
    layer_name: str
    site_type: str
    weight: float = Field(ge=0.0, le=1.0)


class WeightsResponse(BaseModel):
    site_type: str
    weights: dict[str, float]
    last_updated: Optional[datetime] = None


class WeightUpdateRequest(BaseModel):
    updates: list[WeightEntry]

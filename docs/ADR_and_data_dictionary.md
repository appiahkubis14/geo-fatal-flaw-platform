# Architecture Decision Records (ADR)

## ADR-001: CRS Selection Strategy

**Status:** Accepted  
**Date:** 2025-01

### Context
Spatial analysis requires an accurate equal-area projection for area calculations. Display in QGIS and web mapping requires WGS84. The system must serve both needs.

### Decision
Dual-projection strategy:
- **EPSG:5070** (CONUS Albers Equal Area Conic, NAD83) — all analysis geometry stored and queried in this CRS. Metric units (meters). Accurate area calculation across CONUS without distortion.
- **EPSG:4326** (WGS84 Geographic) — display geometry stored as `geom_4326` column. API accepts and returns GeoJSON in 4326. QGIS displays in 4326.

All 15 constraint layer tables store both `geom` (5070) and `geom_4326` (4326). The `geom_4326` column is populated via `ST_Transform` after load.

### Rationale
- EPSG:5070 is the US standard for CONUS equal-area analysis (USGS, EPA use it)
- Dual storage avoids expensive per-query reprojection
- GIST indexes on both CRS enable fast queries in both contexts
- Trade-off: ~2x storage per layer (acceptable given total dataset size)

---

## ADR-002: Async Database Access Pattern

**Status:** Accepted

### Decision
Use **asyncpg** raw connection pool for performance-critical spatial queries, with SQLAlchemy async engine available for ORM operations.

### Rationale
- asyncpg is 2–5x faster than psycopg2 for PostgreSQL in async Python
- Spatial query results are custom types (geometry) — asyncpg codec registration handles WKB decoding
- SQLAlchemy provides schema migration and ORM convenience; asyncpg provides raw performance
- 15 concurrent spatial queries per request require a connection pool of ≥10

---

## ADR-003: Risk Scoring Normalization

**Status:** Accepted

### Decision
Weighted average normalization:
```
overall_score = (Σ contribution_i / Σ max_weight_i) × 100
```
Where `contribution_i = weight_i × impact_ratio_i`.

Impact ratios:
- **Intersect layers:** `min(intersection_area / site_area, 1.0)`
- **Proximity (grid):** `distance / max_radius` (inverted — farther = higher risk for grid layers)
- **Proximity (hazard):** `1 - distance / max_radius` (closer = higher risk)
- **Buffer:** `min(buffer_overlap_area / site_area, 1.0)` with 50% floor on any hit

Fatal flag automatically enforces `score ≥ 75`.

### Rationale
- Normalization by max possible score ensures the scale is 0–100 regardless of which layers are active
- Per-site-type weight profiles allow different scoring for solar vs. wind vs. BESS vs. datacenter
- Fatal floor at 75 prevents a fatally-flawed site from appearing as low risk due to few other constraints

---

## ADR-004: Materialized View for Fatal-Flag Fast Path

**Status:** Accepted

### Decision
Pre-union all fatal-flag geometries into `constraints.fatal_union` materialized view. The API checks this view first before running full 15-layer analysis.

### Rationale
- Fatal sites are a common case (many sites in sensitive areas)
- Quick pre-check using a single GIST-indexed union can return in <50ms
- Avoids running 15 concurrent queries when a site is obviously fatal
- Materialized view must be refreshed after any fatal-layer reload (handled in ETL)

---

## ADR-005: Table-Driven Layer Registration

**Status:** Accepted

### Decision
`constraints.constraint_registry` table is the single source of truth for all layer metadata. The API queries this table to discover active layers. Adding a layer = INSERT a row + CREATE TABLE.

### Rationale
- No code changes needed to add a new constraint layer
- ETL, API, and QGIS plugin all read from the same registry
- Enables runtime enable/disable of individual layers without redeployment
- Supports future per-client layer customization (different registries per tenant)

---

# Data Dictionary

| Layer | Source | Source URL | Weight (default) | Fatal Flag | Update Frequency | Geometry | Analysis |
|-------|--------|------------|-----------------|------------|------------------|----------|----------|
| wetlands | USFWS NWI | https://www.fws.gov/wetlands/downloads/Conus/ | 0.25 | No | Periodic | Polygon | Intersect |
| protected_areas | USGS PAD-US | https://www.sciencebase.gov/catalog/item/652ebcb1d34ee8d4aad95b8d | 0.40 | GAP 1 & 2 | Annual | Polygon | Intersect |
| critical_habitat | USFWS ECOS | https://ecos.fws.gov/crithab/crithab_all/crithab_all_sf.zip | 0.45 | Always | Quarterly | Polygon | Intersect |
| floodplains | FEMA NFHL | https://hazards.fema.gov/nhdplusdata/NFHL/NATIONAL/ | 0.20 | No | Quarterly | Polygon | Intersect |
| wilderness_areas | USFS/BLM | https://data.fs.usda.gov/geodata/edw/edw_resources/shp/ | 0.50 | Always | Annual | Polygon | Intersect |
| transmission_lines | HIFLD/DHS | https://opendata.arcgis.com/api/v3/datasets/70592bc3... | 0.30 | No | Annual | LineString | Proximity (5mi) |
| substations | HIFLD/DHS | https://opendata.arcgis.com/api/v3/datasets/e7c16e6b... | 0.35 | No | Annual | Point | Proximity (5mi) |
| pipeline_corridors | HIFLD/DHS | https://opendata.arcgis.com/api/v3/datasets/e5b09bdb... | 0.15 | No | Annual | LineString | Buffer (500ft) |
| agricultural_preserves | USDA NRCS | https://www.nrcs.usda.gov/sites/default/files/ | 0.28 | No | Decadal | Polygon | Intersect |
| federal_lands | BLM/DOI | https://gbp-blm-egis.hub.arcgis.com/datasets/BLM-EGIS:: | 0.35 | NPS/DOD | Annual | Polygon | Intersect |
| tribal_lands | US Census | https://www2.census.gov/geo/tiger/TIGER2023/AIANNH/ | 0.42 | Always | Annual | Polygon | Intersect |
| urban_areas | USGS MRLC | https://s3-us-west-2.amazonaws.com/mrlc/nlcd_2021_... | 0.18 | No | Biennial | Polygon (derived) | Intersect |
| steep_slopes | USGS 3DEP | https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/ | 0.22 | No | As-updated | Polygon (derived) | Intersect |
| high_elevation | USGS 3DEP | (same DEM as steep_slopes) | 0.12 | No | As-updated | Polygon (derived) | Intersect |
| contaminated_sites | US EPA | https://www.epa.gov/sites/default/files/2016-05/npl_geojson.json | 0.48 | NPL/Superfund | Quarterly | Point | Proximity (1320ft) |

### Weight Profile Comparison

| Layer | default | solar | wind | bess | datacenter |
|-------|---------|-------|------|------|------------|
| wetlands | 0.25 | 0.20 | 0.20 | 0.22 | 0.18 |
| protected_areas | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 |
| critical_habitat | 0.45 | 0.45 | 0.45 | 0.45 | 0.45 |
| floodplains | 0.20 | 0.22 | 0.15 | **0.35** | 0.30 |
| wilderness_areas | 0.50 | 0.50 | 0.50 | 0.50 | 0.50 |
| transmission_lines | 0.30 | 0.38 | 0.35 | 0.42 | **0.45** |
| substations | 0.35 | **0.42** | 0.38 | **0.45** | **0.48** |
| pipeline_corridors | 0.15 | 0.12 | 0.12 | 0.25 | 0.12 |
| agricultural_preserves | 0.28 | 0.30 | 0.25 | 0.28 | 0.20 |
| federal_lands | 0.35 | 0.35 | 0.35 | 0.35 | 0.35 |
| tribal_lands | 0.42 | 0.42 | 0.42 | 0.42 | 0.42 |
| urban_areas | 0.18 | 0.15 | 0.22 | 0.20 | **0.10** |
| steep_slopes | 0.22 | 0.25 | **0.15** | 0.28 | 0.30 |
| high_elevation | 0.12 | 0.10 | **0.08** | 0.18 | 0.20 |
| contaminated_sites | 0.48 | 0.48 | 0.48 | **0.50** | 0.45 |

Bold = notable adjustment from default for that site type.

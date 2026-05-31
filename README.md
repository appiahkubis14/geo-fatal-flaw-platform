# Fatal Flaw Geospatial Risk Assessment Platform

**Production-grade site suitability screening for Solar, Wind, BESS, and Data Center projects across CONUS.**

Assess candidate project sites against 15 authoritative geospatial constraint layers — in under 500ms — with automated fatal-flag detection, weighted risk scoring, and professional PDF reports.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Quick Start](#quick-start)
5. [Data Pipeline](#data-pipeline)
6. [API Usage](#api-usage)
7. [QGIS Plugin Installation](#qgis-plugin-installation)
8. [Configuration](#configuration)
9. [Adding New Layers](#adding-new-layers)
10. [Testing](#testing)
11. [Performance Tuning](#performance-tuning)
12. [Troubleshooting](#troubleshooting)

---

## Overview

The Fatal Flaw Platform screens renewable energy project sites against 15 geospatial constraint datasets:

| # | Layer | Category | Analysis | Fatal? | Default Weight |
|---|-------|----------|----------|--------|----------------|
| 1 | Wetlands (NWI) | Environmental | Intersect | No | 0.25 |
| 2 | Protected Areas (PAD-US) | Environmental | Intersect | GAP 1&2 | 0.40 |
| 3 | Critical Habitat (USFWS) | Environmental | Intersect | **Yes** | 0.45 |
| 4 | Floodplains (FEMA NFHL) | Environmental | Intersect | No | 0.20 |
| 5 | Wilderness Areas (USFS/BLM) | Environmental | Intersect | **Yes** | 0.50 |
| 6 | Transmission Lines (HIFLD) | Grid | Proximity | No | 0.30 |
| 7 | Substations (HIFLD) | Grid | Proximity | No | 0.35 |
| 8 | Pipeline Corridors (HIFLD) | Grid | Buffer | No | 0.15 |
| 9 | Agricultural Preserves (NRCS) | Land Use | Intersect | No | 0.28 |
| 10 | Federal Lands (BLM) | Land Use | Intersect | NPS/DOD | 0.35 |
| 11 | Tribal Lands (Census) | Land Use | Intersect | **Yes** | 0.42 |
| 12 | Urban Areas (NLCD) | Land Use | Intersect | No | 0.18 |
| 13 | Steep Slopes >15% (3DEP) | Physical | Intersect | No | 0.22 |
| 14 | High Elevation >2500m (3DEP) | Physical | Intersect | No | 0.12 |
| 15 | Contaminated Sites (EPA) | Physical | Proximity | Superfund | 0.48 |

**Risk Score:** 0–100 normalized weighted score. Fatal flag automatically pushes score ≥ 75.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Docker Compose                        │
│                                                           │
│  ┌──────────────┐    ┌──────────────┐   ┌─────────────┐ │
│  │  ETL Runner  │───▶│   PostGIS    │◀──│  FastAPI    │ │
│  │  (one-shot)  │    │  (15 layers) │   │  Risk API   │ │
│  └──────────────┘    └──────────────┘   └──────┬──────┘ │
│                             ▲                   │        │
│                      ┌──────┘            ┌──────▼──────┐ │
│                       Redis Cache        │    QGIS     │ │
│                                          │   Plugin    │ │
└──────────────────────────────────────────┴─────────────┘
```

**CRS Strategy:**
- `EPSG:5070` (CONUS Albers Equal Area) — all area calculations and spatial analysis
- `EPSG:4326` (WGS84) — display in QGIS, API input/output

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker | ≥ 24 | With Docker Compose v2 |
| RAM | 16 GB recommended | Constraint layers are large |
| Disk | 50 GB free | CONUS datasets |
| QGIS | ≥ 3.28 LTR | For the plugin only |
| Python | 3.11 | Only if running outside Docker |

---

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/yourorg/fatal-flaw-platform.git
cd fatal-flaw-platform

# 2. Copy and configure environment
cp .env.example .env
# Edit .env — change POSTGRES_PASSWORD and API_KEY at minimum

# 3. Start core services (PostGIS + Redis + FastAPI)
docker-compose up -d postgis redis fastapi

# 4. Wait for health check to pass (~30 seconds)
docker-compose ps   # fastapi should show "healthy"

# 5. Load constraint data (ETL — takes 20-60 min depending on bandwidth)
docker-compose --profile etl run --rm etl_runner \
    python -m etl_pipeline.scripts.load_all --force

# 6. Run acceptance tests
./tests/run_acceptance.sh http://localhost:8000

# 7. Open Swagger UI
open http://localhost:8000/docs
```

---

## Data Pipeline

### Download & Load All Layers

```bash
# Full ETL (download + load all 15 layers)
docker-compose --profile etl run --rm etl_runner \
    python -m etl_pipeline.scripts.load_all --force

# Download only (no DB load)
docker-compose --profile etl run --rm etl_runner \
    python -m etl_pipeline.scripts.download_all

# Load from already-downloaded files
docker-compose --profile etl run --rm etl_runner \
    python -m etl_pipeline.scripts.load_all --skip-download --force
```

### Refresh a Single Layer

```bash
# Refresh wetlands layer (downloads if not cached)
docker-compose --profile etl run --rm etl_runner \
    python -m etl_pipeline.scripts.refresh_layers --layer wetlands --force

# List layer ETL status (last run, row count)
docker-compose --profile etl run --rm etl_runner \
    python -m etl_pipeline.scripts.refresh_layers --list
```

### Layer ETL Notes

| Layer | Size | Notes |
|-------|------|-------|
| Wetlands | ~2 GB | CONUS composite; per-state also available |
| Floodplains | ~4 GB | National GDB; largest single file |
| NLCD Urban | ~2 GB | Raster; vectorized in ETL |
| DEM (Slopes/Elevation) | ~30 GB | Tiled; ETL downloads by state |
| Others | 10–300 MB | Standard shapefiles |

**Tips:**
- Run ETL on a fast connection; datasets are large
- Use `--skip-download` to reload from cached files after any processing failure
- DEM tiles are cached; if ETL fails mid-way, resume without re-downloading

---

## API Usage

### Assess a Site

```bash
curl -X POST http://localhost:8000/api/v1/assess-site \
  -H "Content-Type: application/json" \
  -d '{
    "type": "Feature",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[
        [-100.0, 40.0], [-99.0, 40.0],
        [-99.0, 41.0], [-100.0, 41.0],
        [-100.0, 40.0]
      ]]
    },
    "properties": {
      "site_name": "Example Solar Site",
      "site_type": "solar"
    }
  }'
```

**Response:**
```json
{
  "assessment_id": "550e8400-e29b-41d4-a716-446655440000",
  "site_name": "Example Solar Site",
  "site_type": "solar",
  "overall_risk_score": 34.2,
  "fatal_flag": false,
  "fatal_layers": [],
  "top_risks": [
    {
      "layer_name": "wetlands",
      "impact_area_acres": 12.4,
      "percentage_of_site": 18.2,
      "contribution_score": 22.5,
      "weight": 0.25,
      "is_fatal": false
    }
  ],
  "all_layer_results": [...],
  "site_area_acres": 68.2,
  "processing_time_ms": 312
}
```

### Site Types

| Value | Use Case | Notable Weight Changes |
|-------|----------|----------------------|
| `solar` | Utility-scale PV | Grid proximity weighted higher |
| `wind` | Wind farm | Slope weight reduced (ridgelines OK) |
| `bess` | Battery storage | Flood and pipeline weights increased |
| `datacenter` | Data center | Substation weight highest |

### Admin Endpoints

```bash
# Get current weights (requires API key)
curl http://localhost:8000/api/v1/weights?site_type=solar \
  -H "X-API-Key: your-api-key"

# Update a weight (takes effect immediately, persisted to DB)
curl -X PUT http://localhost:8000/api/v1/weights \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"updates": [{"layer_name": "wetlands", "site_type": "solar", "weight": 0.30}]}'

# Health check
curl http://localhost:8000/health

# Prometheus metrics
curl http://localhost:8000/metrics
```

**Documentation:** Swagger UI at `http://localhost:8000/docs` | ReDoc at `http://localhost:8000/redoc`

---

## QGIS Plugin Installation

### Method 1: Manual Install (Recommended for Development)

```bash
# Find your QGIS plugin directory
# Linux:   ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
# macOS:   ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/
# Windows: %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\

PLUGIN_DIR="$HOME/.local/share/QGIS/QGIS3/profiles/default/python/plugins"
cp -r qgis_plugin/fatal_flaw_analyzer "$PLUGIN_DIR/"
```

Then in QGIS:
1. **Plugins → Manage and Install Plugins → Installed**
2. Check the box next to **Fatal Flaw Analyzer**
3. Click **Close**

The Fatal Flaw toolbar icon (⚡ shield) appears in the QGIS toolbar.

### Method 2: Plugin ZIP

```bash
cd qgis_plugin
zip -r fatal_flaw_analyzer_v1.0.0.zip fatal_flaw_analyzer/
```

In QGIS: **Plugins → Install from ZIP**

### Plugin Usage

1. Load your candidate site polygons into QGIS (any polygon layer)
2. Click the **⚡ Fatal Flaw Analyzer** toolbar button to open the dock panel
3. Select your polygon layer from the dropdown
4. Select site type (solar/wind/bess/datacenter)
5. Select features in the layer (or choose "All features")
6. Click **🔍 Analyze Site**
7. View the color-coded risk score in the dock panel
8. Click **📄 Generate PDF** to export the full report

**Risk Color Key:**
- 🟢 Green (0–25): Low Risk
- 🟡 Yellow (26–50): Moderate Risk
- 🟠 Orange (51–75): High Risk
- 🔴 Red (76–100 or Fatal): Fatal / Very High Risk

### Plugin Settings

Go to **Plugins → Fatal Flaw Analyzer → Settings…**

| Setting | Default | Description |
|---------|---------|-------------|
| API URL | `http://localhost:8000` | Fatal Flaw API endpoint |
| Timeout | 30 seconds | Request timeout |
| Default Site Type | solar | Pre-selected site type |
| Output Directory | `~/fatal_flaw_reports` | Default PDF save location |

---

## Configuration

### Changing Risk Weights

Weights are stored in `constraints.risk_weights` and loaded into the API at startup. To change a weight:

**Via API (live, no restart):**
```bash
curl -X PUT http://localhost:8000/api/v1/weights \
  -H "X-API-Key: your-key" \
  -d '{"updates": [{"layer_name": "wetlands", "site_type": "solar", "weight": 0.35}]}'
```

**Via SQL (persistent):**
```sql
UPDATE constraints.risk_weights
SET weight = 0.35
WHERE layer_name = 'wetlands' AND site_type = 'solar';
```

**Via environment:** Set `weight_refresh_interval` in `.env` to control how often the API re-reads weights from DB (default 300 seconds).

### Adjusting Area Limits

In `.env`:
```bash
# Minimum site area (acres)
MIN_SITE_ACRES=1.0

# Maximum site area (acres)
MAX_SITE_ACRES=50000.0
```

---

## Adding New Layers

The system is designed so adding a new constraint layer requires **no code changes** — only configuration:

### Step 1: Register the Layer

```sql
INSERT INTO constraints.constraint_registry (
    layer_name, table_name, category, geometry_type, analysis_type,
    proximity_meters, fatal_flag, weight_default,
    data_source, source_url, source_agency, file_format
) VALUES (
    'solar_exclusion_zones',
    'constraints.solar_exclusion_zones',
    'land_use',
    'polygon',
    'intersect',
    NULL,
    FALSE,
    0.30,
    'State Solar Siting Rules',
    'https://example.com/solar-exclusions.shp',
    'State PUC',
    'shapefile'
);
```

### Step 2: Create the Table

```sql
CREATE TABLE constraints.solar_exclusion_zones (
    gid SERIAL PRIMARY KEY,
    geom GEOMETRY(MultiPolygon, 5070),
    geom_4326 GEOMETRY(Geometry, 4326),
    layer_name TEXT DEFAULT 'solar_exclusion_zones',
    source TEXT,
    acquisition_date DATE,
    fatal_flag BOOLEAN DEFAULT FALSE,
    weight_default FLOAT DEFAULT 0.30,
    notes TEXT
);
CREATE INDEX ON constraints.solar_exclusion_zones USING GIST(geom);
CREATE INDEX ON constraints.solar_exclusion_zones USING GIST(geom_4326);
```

### Step 3: Add to config.yaml

```yaml
layers:
  solar_exclusion_zones:
    enabled: true
    download_url: "https://example.com/solar-exclusions.zip"
    file_format: shapefile
```

### Step 4: Add Risk Weights

```sql
INSERT INTO constraints.risk_weights (layer_name, site_type, weight)
VALUES
    ('solar_exclusion_zones', 'default', 0.30),
    ('solar_exclusion_zones', 'solar', 0.45);
```

### Step 5: Load Data

```bash
docker-compose --profile etl run --rm etl_runner \
    python -m etl_pipeline.scripts.refresh_layers --layer solar_exclusion_zones
```

**The API auto-discovers the new layer immediately** — no restart needed.

---

## Testing

```bash
# Unit tests only (no DB required)
cd risk_api
pytest tests/test_suite.py -v -k "unit"

# Integration tests (requires running stack)
pytest tests/test_suite.py -v -k "integration" --tb=short

# Acceptance tests (requires loaded data)
./tests/run_acceptance.sh http://localhost:8000

# Performance tests
pytest tests/test_suite.py -v -k "performance"

# All tests
pytest tests/test_suite.py -v
```

---

## Performance Tuning

### Index Strategy

All 15 constraint layer tables have GIST indexes on both `geom` (EPSG:5070) and `geom_4326`. The API queries in EPSG:5070 exclusively for analysis.

```sql
-- Check index usage for a layer
EXPLAIN ANALYZE
SELECT COUNT(*) FROM constraints.wetlands
WHERE ST_Intersects(geom, ST_GeomFromText('POLYGON(...)', 5070));
```

### fatal_union Materialized View

The `constraints.fatal_union` view pre-unions all fatal-flag geometries. Refresh it after any fatal-layer reload:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY constraints.fatal_union;
```

### PostgreSQL Tuning (recommended for 16GB RAM server)

```sql
-- Add to postgresql.conf or as ALTER SYSTEM:
ALTER SYSTEM SET shared_buffers = '4GB';
ALTER SYSTEM SET work_mem = '256MB';
ALTER SYSTEM SET maintenance_work_mem = '1GB';
ALTER SYSTEM SET effective_cache_size = '12GB';
ALTER SYSTEM SET max_parallel_workers_per_gather = 4;
SELECT pg_reload_conf();
```

### Redis Caching

Identical site+site_type combinations are cached in Redis for `CACHE_TTL_SECONDS` (default 300s). Useful for repeated screening of the same polygon under different configurations.

---

## Troubleshooting

### API returns 500 — "relation does not exist"

The PostGIS schema hasn't been initialized. Ensure `sql/init_schema.sql` ran on startup:
```bash
docker-compose exec postgis psql -U fatal_user -d fatal_flaw_db -c "\dt constraints.*"
```
If empty, restart the postgis container (init scripts only run on first start against an empty volume):
```bash
docker-compose down -v   # ⚠️ destroys data
docker-compose up postgis
```

### ETL fails with SSL or 403 errors

Some HIFLD and FWS URLs require accepting terms or may have changed. Check `etl_pipeline/utils/data_sources.py` for alt_urls, or download manually and place in the ETL data directory.

### API response time > 500ms

1. Check `EXPLAIN ANALYZE` on the slowest layer query
2. Verify GIST indexes exist: `\di constraints.*`
3. Run `VACUUM ANALYZE constraints.<layer>` manually
4. Ensure `fatal_union` materialized view is populated

### QGIS plugin not appearing

1. Confirm plugin is in the correct QGIS plugin directory
2. Enable in **Plugins → Manage and Install → Installed**
3. Check QGIS Python console for import errors: `import fatal_flaw_analyzer`

### PDF generation fails in QGIS

Ensure the QGIS project has at least one loaded layer. The map page requires an active canvas extent. For headless use, export via API + custom reporting tool instead.

---

## Conda Environment (Alternative to Docker)

```bash
conda env create -f environment.yml
conda activate fatal_flaw
# Start PostGIS separately (Docker or local install)
export DATABASE_URL="postgresql://fatal_user:password@localhost/fatal_flaw_db"
uvicorn risk_api.app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

*Fatal Flaw Geospatial Risk Assessment Platform v1.0.0*
*Built for renewable energy developers screening Solar, Wind, BESS, and Data Center sites across CONUS.*

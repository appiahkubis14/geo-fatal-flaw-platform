-- ============================================================
-- Fatal Flaw Geospatial Risk Assessment Platform
-- Database Schema Initialization
-- PostgreSQL 15 / PostGIS 3.4
-- SRID Strategy: EPSG:5070 (CONUS Albers) for analysis,
--                EPSG:4326 (WGS84) for display/QGIS
-- ============================================================

-- ── Extensions ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fast text search on layer names

-- ── Schemas ─────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS constraints;
CREATE SCHEMA IF NOT EXISTS sites;
CREATE SCHEMA IF NOT EXISTS audit;

-- ── Constraint Registry ─────────────────────────────────────────────────────
-- Single source of truth for all constraint layer metadata.
-- The ETL and API both read from here — add a layer here and both systems pick it up.
CREATE TABLE IF NOT EXISTS constraints.constraint_registry (
    id               SERIAL PRIMARY KEY,
    layer_name       TEXT        NOT NULL UNIQUE,
    table_name       TEXT        NOT NULL UNIQUE,    -- e.g. constraints.wetlands
    category         TEXT        NOT NULL,           -- environmental | grid | land_use | physical
    geometry_type    TEXT        NOT NULL,           -- polygon | linestring | point | raster_derived
    analysis_type    TEXT        NOT NULL,           -- intersect | proximity | buffer
    proximity_meters FLOAT       DEFAULT NULL,       -- for proximity analysis layers
    fatal_flag       BOOLEAN     NOT NULL DEFAULT FALSE,
    fatal_condition  TEXT        DEFAULT NULL,       -- SQL fragment or 'always' or 'gap1_gap2'
    weight_default   FLOAT       NOT NULL CHECK (weight_default BETWEEN 0 AND 1),
    data_source      TEXT        NOT NULL,
    source_url       TEXT        NOT NULL,
    source_agency    TEXT        NOT NULL,
    file_format      TEXT        NOT NULL,           -- shapefile | gpkg | geojson | tiff
    expected_crs     TEXT        NOT NULL DEFAULT 'EPSG:4326',
    typical_size_mb  FLOAT       DEFAULT NULL,
    update_frequency TEXT        NOT NULL DEFAULT 'annual',
    notes            TEXT,
    is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE constraints.constraint_registry IS
    'Master registry of all 15 constraint layers. Add a row here and the ETL/API auto-discover the layer.';

-- ── Risk Weights Table ───────────────────────────────────────────────────────
-- Weights are keyed by (layer_name, site_type). The API loads these at startup
-- and refreshes periodically. Update here without redeploying.
CREATE TABLE IF NOT EXISTS constraints.risk_weights (
    id          SERIAL PRIMARY KEY,
    layer_name  TEXT  NOT NULL REFERENCES constraints.constraint_registry(layer_name),
    site_type   TEXT  NOT NULL,   -- solar | wind | bess | datacenter | default
    weight      FLOAT NOT NULL CHECK (weight BETWEEN 0 AND 1),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by  TEXT DEFAULT 'system',
    UNIQUE (layer_name, site_type)
);

-- ── ETL Audit Log ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit.etl_log (
    id             SERIAL PRIMARY KEY,
    layer_name     TEXT        NOT NULL,
    run_id         UUID        NOT NULL DEFAULT uuid_generate_v4(),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ,
    status         TEXT        NOT NULL DEFAULT 'running',  -- running | success | failed
    rows_loaded    INTEGER     DEFAULT 0,
    rows_failed    INTEGER     DEFAULT 0,
    source_url     TEXT,
    file_checksum  TEXT,
    error_message  TEXT,
    notes          TEXT
);

-- ── Sites Schema ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sites.submitted_sites (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_name       TEXT,
    site_type       TEXT        DEFAULT 'solar',
    geom_4326       GEOMETRY(Geometry, 4326)  NOT NULL,
    geom_5070       GEOMETRY(Geometry, 5070)  NOT NULL,
    area_acres      FLOAT,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_by    TEXT        DEFAULT 'anonymous'
);

CREATE INDEX IF NOT EXISTS idx_submitted_sites_geom_4326 ON sites.submitted_sites USING GIST(geom_4326);
CREATE INDEX IF NOT EXISTS idx_submitted_sites_geom_5070 ON sites.submitted_sites USING GIST(geom_5070);

-- ── Assessment Results ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sites.assessments (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_id             UUID        REFERENCES sites.submitted_sites(id),
    site_name           TEXT,
    overall_risk_score  FLOAT,
    fatal_flag          BOOLEAN     NOT NULL DEFAULT FALSE,
    site_area_acres     FLOAT,
    processing_time_ms  INTEGER,
    assessed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    layer_results       JSONB,      -- full per-layer breakdown
    top_risks           JSONB       -- top-5 summary
);

CREATE INDEX IF NOT EXISTS idx_assessments_site_id ON sites.assessments(site_id);
CREATE INDEX IF NOT EXISTS idx_assessments_fatal_flag ON sites.assessments(fatal_flag);

-- ── Helper function: auto-update updated_at ──────────────────────────────────
CREATE OR REPLACE FUNCTION audit.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_constraint_registry_updated_at
    BEFORE UPDATE ON constraints.constraint_registry
    FOR EACH ROW EXECUTE FUNCTION audit.set_updated_at();

CREATE TRIGGER trg_risk_weights_updated_at
    BEFORE UPDATE ON constraints.risk_weights
    FOR EACH ROW EXECUTE FUNCTION audit.set_updated_at();

-- ── Template for all 15 constraint layer tables ──────────────────────────────
-- Each layer follows this exact pattern. Generated tables are created here
-- so PostGIS indexes and constraints are set correctly.

-- ─────────────────────── ENVIRONMENTAL LAYERS ────────────────────────────────

CREATE TABLE IF NOT EXISTS constraints.wetlands (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'wetlands',
    source           TEXT    NOT NULL DEFAULT 'USFWS NWI',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.25,
    wetland_type     TEXT,   -- layer-specific attribute
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.protected_areas (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'protected_areas',
    source           TEXT    NOT NULL DEFAULT 'USGS PAD-US',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,  -- set per-feature based on gap_sts
    weight_default   FLOAT   NOT NULL DEFAULT 0.40,
    gap_status       INTEGER,   -- 1=strict, 2=strict, 3=managed, 4=unprotected
    unit_name        TEXT,
    manager_type     TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.critical_habitat (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'critical_habitat',
    source           TEXT    NOT NULL DEFAULT 'USFWS ECOS',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT TRUE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.45,
    common_name      TEXT,
    scientific_name  TEXT,
    status           TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.floodplains (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'floodplains',
    source           TEXT    NOT NULL DEFAULT 'FEMA NFHL',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.20,
    flood_zone       TEXT,   -- AE, AH, AO, VE, etc.
    dfirm_id         TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.wilderness_areas (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'wilderness_areas',
    source           TEXT    NOT NULL DEFAULT 'USFS/BLM',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT TRUE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.50,
    wilderness_name  TEXT,
    agency           TEXT,
    notes            TEXT
);

-- ─────────────────────── GRID INFRASTRUCTURE LAYERS ─────────────────────────

CREATE TABLE IF NOT EXISTS constraints.transmission_lines (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiLineString, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'transmission_lines',
    source           TEXT    NOT NULL DEFAULT 'HIFLD',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.30,
    voltage_kv       FLOAT,
    owner            TEXT,
    type             TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.substations (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(Point, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'substations',
    source           TEXT    NOT NULL DEFAULT 'HIFLD',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.35,
    substation_name  TEXT,
    voltage_kv       FLOAT,
    owner            TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.pipeline_corridors (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiLineString, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'pipeline_corridors',
    source           TEXT    NOT NULL DEFAULT 'HIFLD',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.15,
    pipeline_type    TEXT,
    operator         TEXT,
    notes            TEXT
);

-- ─────────────────────── LAND USE / ZONING LAYERS ────────────────────────────

CREATE TABLE IF NOT EXISTS constraints.agricultural_preserves (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'agricultural_preserves',
    source           TEXT    NOT NULL DEFAULT 'USDA NRCS',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.28,
    land_cap_class   TEXT,   -- prime, unique, statewide importance
    state_fips       TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.federal_lands (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'federal_lands',
    source           TEXT    NOT NULL DEFAULT 'BLM/USGS',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,  -- set per-feature (NPS/DOD = TRUE)
    weight_default   FLOAT   NOT NULL DEFAULT 0.35,
    agency           TEXT,   -- USFS, BLM, NPS, DOD, etc.
    unit_name        TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.tribal_lands (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'tribal_lands',
    source           TEXT    NOT NULL DEFAULT 'Census TIGER',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT TRUE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.42,
    tribe_name       TEXT,
    aiannha_name     TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.urban_areas (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'urban_areas',
    source           TEXT    NOT NULL DEFAULT 'NLCD',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.18,
    nlcd_class       INTEGER, -- 21=dev open, 22=low, 23=med, 24=high intensity
    nlcd_year        INTEGER,
    notes            TEXT
);

-- ─────────────────────── PHYSICAL CONSTRAINT LAYERS ──────────────────────────

CREATE TABLE IF NOT EXISTS constraints.steep_slopes (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'steep_slopes',
    source           TEXT    NOT NULL DEFAULT 'USGS 3DEP',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.22,
    slope_class      TEXT,   -- '>15%' or '>20%' etc.
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.high_elevation (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(MultiPolygon, 5070),
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'high_elevation',
    source           TEXT    NOT NULL DEFAULT 'USGS 3DEP',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    weight_default   FLOAT   NOT NULL DEFAULT 0.12,
    elev_threshold_m FLOAT   NOT NULL DEFAULT 2500,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS constraints.contaminated_sites (
    gid              SERIAL PRIMARY KEY,
    geom             GEOMETRY(Point, 5070),   -- EPA sites are points; buffer for polygon analysis
    geom_4326        GEOMETRY(Geometry, 4326),
    layer_name       TEXT    NOT NULL DEFAULT 'contaminated_sites',
    source           TEXT    NOT NULL DEFAULT 'EPA',
    acquisition_date DATE,
    fatal_flag       BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE for NPL (Superfund) sites
    weight_default   FLOAT   NOT NULL DEFAULT 0.48,
    site_type        TEXT,   -- NPL (Superfund), Brownfield, RCRA
    site_name        TEXT,
    site_id          TEXT,
    status           TEXT,
    notes            TEXT
);

-- ── Spatial Indexes (all layers) ─────────────────────────────────────────────
-- Created AFTER table creation for load performance.
-- GIST indexes on both CRS for each layer.

CREATE INDEX IF NOT EXISTS idx_wetlands_geom         ON constraints.wetlands          USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_wetlands_geom_4326    ON constraints.wetlands          USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_protarea_geom         ON constraints.protected_areas   USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_protarea_geom_4326    ON constraints.protected_areas   USING GIST(geom_4326);
CREATE INDEX IF NOT EXISTS idx_protarea_gap          ON constraints.protected_areas   (gap_status);

CREATE INDEX IF NOT EXISTS idx_crithab_geom          ON constraints.critical_habitat  USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_crithab_geom_4326     ON constraints.critical_habitat  USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_flood_geom            ON constraints.floodplains       USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_flood_geom_4326       ON constraints.floodplains       USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_wild_geom             ON constraints.wilderness_areas  USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_wild_geom_4326        ON constraints.wilderness_areas  USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_trans_geom            ON constraints.transmission_lines USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_trans_geom_4326       ON constraints.transmission_lines USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_subs_geom             ON constraints.substations       USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_subs_geom_4326        ON constraints.substations       USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_pipe_geom             ON constraints.pipeline_corridors USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_pipe_geom_4326        ON constraints.pipeline_corridors USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_agpres_geom           ON constraints.agricultural_preserves USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_agpres_geom_4326      ON constraints.agricultural_preserves USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_fedland_geom          ON constraints.federal_lands     USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_fedland_geom_4326     ON constraints.federal_lands     USING GIST(geom_4326);
CREATE INDEX IF NOT EXISTS idx_fedland_agency        ON constraints.federal_lands     USING GIN(to_tsvector('english', coalesce(agency,'')));

CREATE INDEX IF NOT EXISTS idx_tribal_geom           ON constraints.tribal_lands      USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_tribal_geom_4326      ON constraints.tribal_lands      USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_urban_geom            ON constraints.urban_areas       USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_urban_geom_4326       ON constraints.urban_areas       USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_slope_geom            ON constraints.steep_slopes      USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_slope_geom_4326       ON constraints.steep_slopes      USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_elev_geom             ON constraints.high_elevation    USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_elev_geom_4326        ON constraints.high_elevation    USING GIST(geom_4326);

CREATE INDEX IF NOT EXISTS idx_contam_geom           ON constraints.contaminated_sites USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_contam_geom_4326      ON constraints.contaminated_sites USING GIST(geom_4326);

-- ── Materialized view: pre-union fatal layers ─────────────────────────────────
-- Used by the API for quick fatal-flag checks before running full scoring.
CREATE MATERIALIZED VIEW IF NOT EXISTS constraints.fatal_union AS
    SELECT 'protected_areas' AS layer, geom FROM constraints.protected_areas  WHERE fatal_flag = TRUE
    UNION ALL
    SELECT 'critical_habitat',                  geom FROM constraints.critical_habitat
    UNION ALL
    SELECT 'wilderness_areas',                  geom FROM constraints.wilderness_areas
    UNION ALL
    SELECT 'tribal_lands',                      geom FROM constraints.tribal_lands
    UNION ALL
    SELECT 'federal_lands',                     geom FROM constraints.federal_lands   WHERE fatal_flag = TRUE
    UNION ALL
    SELECT 'contaminated_sites',
           ST_Buffer(geom, 200)                       FROM constraints.contaminated_sites WHERE fatal_flag = TRUE
WITH DATA;

CREATE INDEX IF NOT EXISTS idx_fatal_union_geom ON constraints.fatal_union USING GIST(geom);

COMMENT ON MATERIALIZED VIEW constraints.fatal_union IS
    'Pre-unioned fatal-flag geometries for rapid disqualification queries. REFRESH MATERIALIZED VIEW constraints.fatal_union after any fatal-layer reload.';

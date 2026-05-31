-- ============================================================
-- Seed: Constraint Registry + Risk Weights
-- All 15 layers registered with metadata and per-site-type weights
-- ============================================================

-- ── Constraint Registry ──────────────────────────────────────────────────────
INSERT INTO constraints.constraint_registry (
    layer_name, table_name, category, geometry_type, analysis_type,
    proximity_meters, fatal_flag, fatal_condition, weight_default,
    data_source, source_url, source_agency, file_format, expected_crs,
    typical_size_mb, update_frequency, notes
) VALUES
-- ENVIRONMENTAL (5)
(
    'wetlands', 'constraints.wetlands', 'environmental', 'polygon', 'intersect',
    NULL, FALSE, NULL, 0.25,
    'USFWS National Wetlands Inventory (NWI)',
    'https://www.fws.gov/wetlands/Data/State-Downloads.html',
    'USFWS', 'shapefile', 'EPSG:4326', 2000, 'periodic',
    'Download by state zip; CONUS composite ~2GB. Mitigation possible; not auto-fatal.'
),
(
    'protected_areas', 'constraints.protected_areas', 'environmental', 'polygon', 'intersect',
    NULL, FALSE, 'gap_status IN (1,2)', 0.40,
    'USGS Protected Areas Database of the US (PAD-US)',
    'https://www.sciencebase.gov/catalog/item/652ebcb1d34ee8d4aad95b8d',
    'USGS GAP', 'geodatabase', 'EPSG:4326', 800, 'annual',
    'GAP Status 1 & 2 = fatal. Use Combined Feature Class from latest PAD-US release.'
),
(
    'critical_habitat', 'constraints.critical_habitat', 'environmental', 'polygon', 'intersect',
    NULL, TRUE, 'always', 0.45,
    'USFWS Designated Critical Habitat',
    'https://ecos.fws.gov/ecp/report/table/critical-habitat.html',
    'USFWS ECOS', 'shapefile', 'EPSG:4326', 250, 'quarterly',
    'Download all critical habitat from ECOS. Any intersection = fatal (ESA Section 7).'
),
(
    'floodplains', 'constraints.floodplains', 'environmental', 'polygon', 'intersect',
    NULL, FALSE, NULL, 0.20,
    'FEMA National Flood Hazard Layer (NFHL)',
    'https://hazards.fema.gov/nhdplusdata/NFHL/NATIONAL/NFHL_National_20240101.zip',
    'FEMA', 'geodatabase', 'EPSG:4326', 4000, 'quarterly',
    '100-yr floodplain (Zone AE, AH, AO, VE). Engineering solutions possible; not auto-fatal.'
),
(
    'wilderness_areas', 'constraints.wilderness_areas', 'environmental', 'polygon', 'intersect',
    NULL, TRUE, 'always', 0.50,
    'USFS/BLM Wilderness Areas',
    'https://data.fs.usda.gov/geodata/edw/edw_resources/shp/S_USA.Wilderness.zip',
    'USFS / BLM', 'shapefile', 'EPSG:4326', 50, 'annual',
    'Wilderness Act prohibits development. Use USFS national layer + supplement with BLM wilderness.'
),
-- GRID INFRASTRUCTURE (3)
(
    'transmission_lines', 'constraints.transmission_lines', 'grid', 'linestring', 'proximity',
    8046, FALSE, NULL, 0.30,
    'HIFLD Electric Power Transmission Lines',
    'https://opendata.arcgis.com/api/v3/datasets/70592bc3bd894320aed315d814f0ead7_0/downloads/data?format=shp&spatialRefId=4326',
    'HIFLD / DHS', 'shapefile', 'EPSG:4326', 120, 'annual',
    'Filter voltage_kv > 100. Proximity = favorable (5 mile = 8046m search radius). CLOSER = LOWER RISK.'
),
(
    'substations', 'constraints.substations', 'grid', 'point', 'proximity',
    8046, FALSE, NULL, 0.35,
    'HIFLD Electric Substations',
    'https://opendata.arcgis.com/api/v3/datasets/e7c16e6be24c4b8f9c12f5fde74c4e45_0/downloads/data?format=shp&spatialRefId=4326',
    'HIFLD / DHS', 'shapefile', 'EPSG:4326', 15, 'annual',
    'Within 5 miles = favorable for interconnection cost. CLOSER = LOWER RISK.'
),
(
    'pipeline_corridors', 'constraints.pipeline_corridors', 'grid', 'linestring', 'buffer',
    152, FALSE, NULL, 0.15,
    'HIFLD Natural Gas Transmission Pipelines',
    'https://opendata.arcgis.com/api/v3/datasets/e5b09bdb86f44c229bec1e5a028bf01f_0/downloads/data?format=shp&spatialRefId=4326',
    'HIFLD / DHS', 'shapefile', 'EPSG:4326', 80, 'annual',
    '500ft (152m) buffer. Safety setback concern. Intersection with buffer = risk.'
),
-- LAND USE / ZONING (4)
(
    'agricultural_preserves', 'constraints.agricultural_preserves', 'land_use', 'polygon', 'intersect',
    NULL, FALSE, NULL, 0.28,
    'USDA NRCS Prime Farmland / Important Farmland',
    'https://www.nrcs.usda.gov/wps/portal/nrcs/detail/soils/use/?cid=nrcs142p2_054028',
    'USDA NRCS', 'shapefile', 'EPSG:4326', 500, 'decadal',
    'State-level data. Prime/Unique soils. fatal_flag depends on state policy; default FALSE.'
),
(
    'federal_lands', 'constraints.federal_lands', 'land_use', 'polygon', 'intersect',
    NULL, FALSE, 'agency IN (''NPS'',''DOD'')', 0.35,
    'BLM National Surface Management Agency Area',
    'https://gbp-blm-egis.hub.arcgis.com/datasets/BLM-EGIS::blm-natl-surface-management-agency-area-polygon/about',
    'BLM / DOI', 'shapefile', 'EPSG:4326', 300, 'annual',
    'NPS and DOD = fatal. USFS/BLM = permittable (high risk, not fatal). Supplement with USFS National Forest layer.'
),
(
    'tribal_lands', 'constraints.tribal_lands', 'land_use', 'polygon', 'intersect',
    NULL, TRUE, 'always', 0.42,
    'US Census TIGER American Indian / Alaska Native / Native Hawaiian Areas',
    'https://www2.census.gov/geo/tiger/TIGER2023/AIANNH/tl_2023_us_aiannh.zip',
    'US Census Bureau', 'shapefile', 'EPSG:4326', 30, 'annual',
    'Sovereign nation; formal consultation required. Any intersection = fatal for initial screening.'
),
(
    'urban_areas', 'constraints.urban_areas', 'land_use', 'polygon', 'intersect',
    NULL, FALSE, NULL, 0.18,
    'NLCD National Land Cover Database — Developed Classes',
    'https://s3-us-west-2.amazonaws.com/mrlc/nlcd_2021_land_cover_l48_20230630.img',
    'USGS MRLC', 'tiff', 'EPSG:5070', 2000, 'biennial',
    'Raster→vector derived. Classes 21-24 (developed). Pre-process in ETL to vectorize threshold.'
),
-- PHYSICAL CONSTRAINTS (3)
(
    'steep_slopes', 'constraints.steep_slopes', 'physical', 'polygon', 'intersect',
    NULL, FALSE, NULL, 0.22,
    'USGS 3DEP 30m Digital Elevation Model',
    'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/TIFF/USGS_Seamless_DEM_1.tif',
    'USGS 3DEP', 'tiff', 'EPSG:4269', 5000, 'as_needed',
    'DEM→slope calculation→threshold >15%. Pre-process in ETL using GDAL/numpy to vectorize.'
),
(
    'high_elevation', 'constraints.high_elevation', 'physical', 'polygon', 'intersect',
    NULL, FALSE, NULL, 0.12,
    'USGS 3DEP 30m Digital Elevation Model',
    'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/TIFF/USGS_Seamless_DEM_1.tif',
    'USGS 3DEP', 'tiff', 'EPSG:4269', 5000, 'as_needed',
    'Same DEM as steep slopes. Threshold >2500m. Logistical constraints at high elevation.'
),
(
    'contaminated_sites', 'constraints.contaminated_sites', 'physical', 'point', 'proximity',
    402, FALSE, 'site_type = ''NPL''', 0.48,
    'EPA Superfund NPL + ECHO Facility Data',
    'https://www.epa.gov/sites/default/files/2016-05/npl_geojson.json',
    'US EPA', 'geojson', 'EPSG:4326', 10, 'quarterly',
    'NPL (Superfund) sites = fatal. Brownfields = high risk. 1320ft (402m) buffer for proximity.'
)
ON CONFLICT (layer_name) DO UPDATE SET
    source_url       = EXCLUDED.source_url,
    typical_size_mb  = EXCLUDED.typical_size_mb,
    updated_at       = NOW();

-- ── Risk Weights: Default Profile ────────────────────────────────────────────
INSERT INTO constraints.risk_weights (layer_name, site_type, weight) VALUES
-- default weights (identical to constraint_registry defaults)
('wetlands',               'default', 0.25),
('protected_areas',        'default', 0.40),
('critical_habitat',       'default', 0.45),
('floodplains',            'default', 0.20),
('wilderness_areas',       'default', 0.50),
('transmission_lines',     'default', 0.30),
('substations',            'default', 0.35),
('pipeline_corridors',     'default', 0.15),
('agricultural_preserves', 'default', 0.28),
('federal_lands',          'default', 0.35),
('tribal_lands',           'default', 0.42),
('urban_areas',            'default', 0.18),
('steep_slopes',           'default', 0.22),
('high_elevation',         'default', 0.12),
('contaminated_sites',     'default', 0.48),

-- solar: transmission/substations more important (grid proximity critical)
('wetlands',               'solar', 0.20),
('protected_areas',        'solar', 0.40),
('critical_habitat',       'solar', 0.45),
('floodplains',            'solar', 0.22),
('wilderness_areas',       'solar', 0.50),
('transmission_lines',     'solar', 0.38),
('substations',            'solar', 0.42),
('pipeline_corridors',     'solar', 0.12),
('agricultural_preserves', 'solar', 0.30),
('federal_lands',          'solar', 0.35),
('tribal_lands',           'solar', 0.42),
('urban_areas',            'solar', 0.15),
('steep_slopes',           'solar', 0.25),
('high_elevation',         'solar', 0.10),
('contaminated_sites',     'solar', 0.48),

-- wind: elevation and slope more impactful; grid proximity still important
('wetlands',               'wind', 0.20),
('protected_areas',        'wind', 0.40),
('critical_habitat',       'wind', 0.45),
('floodplains',            'wind', 0.15),
('wilderness_areas',       'wind', 0.50),
('transmission_lines',     'wind', 0.35),
('substations',            'wind', 0.38),
('pipeline_corridors',     'wind', 0.12),
('agricultural_preserves', 'wind', 0.25),
('federal_lands',          'wind', 0.35),
('tribal_lands',           'wind', 0.42),
('urban_areas',            'wind', 0.22),
('steep_slopes',           'wind', 0.15),   -- wind favors ridgelines; steep=good
('high_elevation',         'wind', 0.08),   -- high elevation can be good for wind
('contaminated_sites',     'wind', 0.48),

-- bess: safety critical; contaminated sites and pipelines higher
('wetlands',               'bess', 0.22),
('protected_areas',        'bess', 0.40),
('critical_habitat',       'bess', 0.45),
('floodplains',            'bess', 0.35),   -- flooding = BESS fire risk
('wilderness_areas',       'bess', 0.50),
('transmission_lines',     'bess', 0.42),
('substations',            'bess', 0.45),
('pipeline_corridors',     'bess', 0.25),   -- explosion risk proximity
('agricultural_preserves', 'bess', 0.28),
('federal_lands',          'bess', 0.35),
('tribal_lands',           'bess', 0.42),
('urban_areas',            'bess', 0.20),
('steep_slopes',           'bess', 0.28),
('high_elevation',         'bess', 0.18),
('contaminated_sites',     'bess', 0.50),

-- datacenter: power and connectivity critical; urban proximity favorable
('wetlands',               'datacenter', 0.18),
('protected_areas',        'datacenter', 0.40),
('critical_habitat',       'datacenter', 0.45),
('floodplains',            'datacenter', 0.30),
('wilderness_areas',       'datacenter', 0.50),
('transmission_lines',     'datacenter', 0.45),
('substations',            'datacenter', 0.48),
('pipeline_corridors',     'datacenter', 0.12),
('agricultural_preserves', 'datacenter', 0.20),
('federal_lands',          'datacenter', 0.35),
('tribal_lands',           'datacenter', 0.42),
('urban_areas',            'datacenter', 0.10),  -- urban = good for datacenter
('steep_slopes',           'datacenter', 0.30),
('high_elevation',         'datacenter', 0.20),
('contaminated_sites',     'datacenter', 0.45)

ON CONFLICT (layer_name, site_type) DO UPDATE SET
    weight     = EXCLUDED.weight,
    updated_at = NOW();

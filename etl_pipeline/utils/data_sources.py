"""
etl_pipeline/utils/data_sources.py
Central registry of all 15 constraint data sources.
Provides verified URLs, formats, and update guidance.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DataSource:
    layer_name: str
    display_name: str
    category: str
    primary_url: str
    alt_urls: list[str]
    file_format: str          # shapefile | geodatabase | geojson | tiff | wfs
    expected_crs: str
    typical_size_mb: float
    update_frequency: str
    agency: str
    notes: str
    fatal_flag: bool
    weight_default: float
    geometry_type: str        # polygon | linestring | point | raster
    analysis_type: str        # intersect | proximity | buffer


REGISTRY: dict[str, DataSource] = {

    # ── ENVIRONMENTAL ────────────────────────────────────────────────────────

    "wetlands": DataSource(
        layer_name="wetlands",
        display_name="National Wetlands Inventory (NWI)",
        category="environmental",
        primary_url=(
            "https://www.fws.gov/wetlands/downloads/Conus/"
            "conus_shapefile_wetlands.zip"
        ),
        alt_urls=[
            "https://www.fws.gov/wetlands/Data/State-Downloads.html",
            # Per-state pattern: replace {ST} with 2-letter state abbreviation
            "https://www.fws.gov/wetlands/downloads/State/{ST}_shapefile_wetlands.zip",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=2000.0,
        update_frequency="Periodic (every 3–5 years per region)",
        agency="USFWS",
        notes=(
            "CONUS composite is ~2 GB unzipped. "
            "Per-state downloads are more manageable. "
            "Key attribute: WETLAND_TY (wetland classification code). "
            "Mitigation possible; not automatically fatal."
        ),
        fatal_flag=False,
        weight_default=0.25,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "protected_areas": DataSource(
        layer_name="protected_areas",
        display_name="Protected Areas Database of the US (PAD-US)",
        category="environmental",
        primary_url=(
            "https://www.sciencebase.gov/catalog/file/get/"
            "652ebcb1d34ee8d4aad95b8d"
            "?facets=PADUS4_0Combined_Proclamation_Marine_Fee_Designation_Easement_Shapefile.zip"
        ),
        alt_urls=[
            "https://www.sciencebase.gov/catalog/item/652ebcb1d34ee8d4aad95b8d",
            "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-download",
            # GDB version
            "https://www.sciencebase.gov/catalog/file/get/652ebcb1d34ee8d4aad95b8d"
            "?facets=PADUS4_0Combined_Proclamation_Marine_Fee_Designation_Easement_GDB.zip",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=800.0,
        update_frequency="Annual (PAD-US 4.0 released 2023)",
        agency="USGS Gap Analysis Project",
        notes=(
            "Use 'Combined' feature class. "
            "GAP_Sts field: 1=strict protection (fatal), 2=strict (fatal), "
            "3=managed, 4=unprotected. "
            "Filter GAP_Sts IN (1,2) and set fatal_flag=TRUE."
        ),
        fatal_flag=False,  # per-feature based on GAP status
        weight_default=0.40,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "critical_habitat": DataSource(
        layer_name="critical_habitat",
        display_name="USFWS Designated Critical Habitat",
        category="environmental",
        primary_url="https://ecos.fws.gov/crithab/crithab_all/crithab_all_sf.zip",
        alt_urls=[
            "https://ecos.fws.gov/ecp/report/table/critical-habitat.html",
            # AGOL service
            "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/"
            "CriticalHabitat/FeatureServer/0/query?where=1%3D1&outFields=*&f=json",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=250.0,
        update_frequency="Quarterly",
        agency="USFWS ECOS",
        notes=(
            "Any intersection triggers ESA Section 7 consultation. "
            "Always fatal for initial site screening. "
            "Key attributes: comname, sciname, status."
        ),
        fatal_flag=True,
        weight_default=0.45,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "floodplains": DataSource(
        layer_name="floodplains",
        display_name="FEMA National Flood Hazard Layer (NFHL)",
        category="environmental",
        primary_url=(
            "https://hazards.fema.gov/nhdplusdata/NFHL/NATIONAL/"
            "NFHL_National_20240101.zip"
        ),
        alt_urls=[
            "https://msc.fema.gov/portal/downloadProduct?productTypeID=NFHL_NATIONAL",
            "https://www.fema.gov/flood-maps/products-tools",
            # AGOL REST service for on-demand query
            "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
            "USA_Flood_Hazard_Reduced_Set_gdb/FeatureServer/0",
        ],
        file_format="geodatabase",
        expected_crs="EPSG:4326",
        typical_size_mb=4000.0,
        update_frequency="Quarterly (FEMA Q-updates)",
        agency="FEMA",
        notes=(
            "Filter to S_FLD_HAZ_AR layer, zones A, AE, AH, AO, VE. "
            "The national GDB is ~4 GB. Consider county-level downloads "
            "via MSC API for incremental updates. Not auto-fatal (engineering solutions exist)."
        ),
        fatal_flag=False,
        weight_default=0.20,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "wilderness_areas": DataSource(
        layer_name="wilderness_areas",
        display_name="National Wilderness Areas (USFS + BLM)",
        category="environmental",
        primary_url=(
            "https://data.fs.usda.gov/geodata/edw/edw_resources/shp/"
            "S_USA.Wilderness.zip"
        ),
        alt_urls=[
            # BLM supplement
            "https://gbp-blm-egis.hub.arcgis.com/datasets/"
            "BLM-EGIS::blm-natl-wilderness-area-polygon/"
            "downloads/data?format=shp&spatialRefId=4326",
            "https://www.blm.gov/maps/gis-data-download",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=50.0,
        update_frequency="Annual",
        agency="USFS / BLM",
        notes=(
            "Wilderness Act (1964) prohibits all development. Always fatal. "
            "Merge USFS national layer with BLM wilderness for complete coverage. "
            "NPS wilderness is included in PAD-US."
        ),
        fatal_flag=True,
        weight_default=0.50,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    # ── GRID INFRASTRUCTURE ──────────────────────────────────────────────────

    "transmission_lines": DataSource(
        layer_name="transmission_lines",
        display_name="HIFLD Electric Power Transmission Lines (>100kV)",
        category="grid",
        primary_url=(
            "https://opendata.arcgis.com/api/v3/datasets/"
            "70592bc3bd894320aed315d814f0ead7_0/downloads/data"
            "?format=shp&spatialRefId=4326"
        ),
        alt_urls=[
            "https://hifld-geoplatform.hub.arcgis.com/datasets/"
            "geoplatform::electric-power-transmission-lines/about",
            # Direct AGOL feature service
            "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
            "Electric_Power_Transmission_Lines/FeatureServer/0",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=120.0,
        update_frequency="Annual",
        agency="HIFLD / DHS",
        notes=(
            "Filter VOLT_CLASS NOT IN ('UNDER 100') to keep >100kV lines. "
            "PROXIMITY analysis: within 8046m (5 miles) = favorable. "
            "Scoring inverted: CLOSER = LOWER RISK (grid proximity is good). "
            "Key attributes: VOLTAGE, OWNER, TYPE."
        ),
        fatal_flag=False,
        weight_default=0.30,
        geometry_type="linestring",
        analysis_type="proximity",
    ),

    "substations": DataSource(
        layer_name="substations",
        display_name="HIFLD Electric Substations",
        category="grid",
        primary_url=(
            "https://opendata.arcgis.com/api/v3/datasets/"
            "e7c16e6be24c4b8f9c12f5fde74c4e45_0/downloads/data"
            "?format=shp&spatialRefId=4326"
        ),
        alt_urls=[
            "https://hifld-geoplatform.hub.arcgis.com/datasets/"
            "geoplatform::electric-substations/about",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=15.0,
        update_frequency="Annual",
        agency="HIFLD / DHS",
        notes=(
            "Point layer. Proximity search radius: 8046m (5 miles). "
            "Closer is better for interconnection cost. "
            "Key attributes: NAME, MAX_VOLT, OWNER."
        ),
        fatal_flag=False,
        weight_default=0.35,
        geometry_type="point",
        analysis_type="proximity",
    ),

    "pipeline_corridors": DataSource(
        layer_name="pipeline_corridors",
        display_name="HIFLD Natural Gas Transmission Pipelines",
        category="grid",
        primary_url=(
            "https://opendata.arcgis.com/api/v3/datasets/"
            "e5b09bdb86f44c229bec1e5a028bf01f_0/downloads/data"
            "?format=shp&spatialRefId=4326"
        ),
        alt_urls=[
            "https://hifld-geoplatform.hub.arcgis.com/datasets/"
            "geoplatform::natural-gas-interstate-and-intrastate-pipelines/about",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=80.0,
        update_frequency="Annual",
        agency="HIFLD / DHS",
        notes=(
            "Buffer analysis: 152m (~500ft) safety setback. "
            "Site intersecting buffer = elevated risk. "
            "Key attributes: TYPICALDIA, OPERATOR."
        ),
        fatal_flag=False,
        weight_default=0.15,
        geometry_type="linestring",
        analysis_type="buffer",
    ),

    # ── LAND USE / ZONING ────────────────────────────────────────────────────

    "agricultural_preserves": DataSource(
        layer_name="agricultural_preserves",
        display_name="USDA NRCS Important Farmland (Prime / Unique / Statewide)",
        category="land_use",
        primary_url=(
            "https://www.nrcs.usda.gov/sites/default/files/2022-10/"
            "important_farmland_conus.zip"
        ),
        alt_urls=[
            # SSURGO Web Soil Survey WFS endpoint
            "https://sdmdataaccess.nrcs.usda.gov/Spatial/SDM.wfs"
            "?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetFeature"
            "&TYPENAME=farmlandpolyrestricted&SRSNAME=EPSG:4326",
            "https://www.nrcs.usda.gov/wps/portal/nrcs/detail/soils/use/"
            "?cid=nrcs142p2_054028",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=500.0,
        update_frequency="Decadal (Census of Ag cycle)",
        agency="USDA NRCS",
        notes=(
            "farmlndcl codes: 'P'=Prime, 'U'=Unique, 'S'=Statewide, "
            "'L'=Local importance. State policy varies on restrictions. "
            "Default fatal_flag=FALSE but high weight."
        ),
        fatal_flag=False,
        weight_default=0.28,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "federal_lands": DataSource(
        layer_name="federal_lands",
        display_name="BLM National Surface Management Agency Areas",
        category="land_use",
        primary_url=(
            "https://opendata.arcgis.com/datasets/"
            "3d4e5b628e9a47fbb062f0b2060d998e_0.zip"
        ),
        alt_urls=[
            "https://gbp-blm-egis.hub.arcgis.com/datasets/"
            "BLM-EGIS::blm-natl-surface-management-agency-area-polygon/"
            "downloads/data?format=shp&spatialRefId=4326",
            "https://www.sciencebase.gov/catalog/item/4fb5cfece4b04cb9379ce19c",
            # USFS National Forest supplement
            "https://data.fs.usda.gov/geodata/edw/edw_resources/shp/"
            "S_USA.AdministrativeForest.zip",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=300.0,
        update_frequency="Annual",
        agency="BLM / DOI",
        notes=(
            "Adm_Code / agency field: NPS and DOD (Army, USMC, Navy, USAF) = fatal. "
            "BLM and USFS = high risk but permitttable. "
            "Supplement with USFS National Forest boundary for complete USFS coverage."
        ),
        fatal_flag=False,  # per-feature based on agency
        weight_default=0.35,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "tribal_lands": DataSource(
        layer_name="tribal_lands",
        display_name="US Census TIGER American Indian / Alaska Native Areas",
        category="land_use",
        primary_url=(
            "https://www2.census.gov/geo/tiger/TIGER2023/AIANNH/"
            "tl_2023_us_aiannh.zip"
        ),
        alt_urls=[
            "https://www.census.gov/cgi-bin/geo/shapefiles/index.php"
            "?year=2023&layergroup=American+Indian+Area+Geography",
            "https://www.bia.gov/bia/ots/dpme/download/national_indian_land_area.zip",
        ],
        file_format="shapefile",
        expected_crs="EPSG:4326",
        typical_size_mb=30.0,
        update_frequency="Annual (TIGER release cycle)",
        agency="US Census Bureau / BIA",
        notes=(
            "Federally recognized tribes are sovereign nations. "
            "Any intersection = fatal for initial screening. "
            "Formal government-to-government consultation required. "
            "Key attributes: NAME, NAMELSAD."
        ),
        fatal_flag=True,
        weight_default=0.42,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "urban_areas": DataSource(
        layer_name="urban_areas",
        display_name="NLCD 2021 Developed Land Cover (Classes 21–24)",
        category="land_use",
        primary_url=(
            "https://s3-us-west-2.amazonaws.com/mrlc/"
            "nlcd_2021_land_cover_l48_20230630.img"
        ),
        alt_urls=[
            "https://www.mrlc.gov/data/nlcd-2021-land-cover-conus",
            # MRLC bulk download tool
            "https://www.mrlc.gov/viewer/",
        ],
        file_format="tiff",
        expected_crs="EPSG:5070",
        typical_size_mb=2000.0,
        update_frequency="Biennial",
        agency="USGS MRLC",
        notes=(
            "Raster → vector in ETL. Classes: 21=Open Developed, 22=Low Intensity, "
            "23=Medium Intensity, 24=High Intensity. "
            "Vectorize threshold and simplify to 30m tolerance. "
            "Not fatal; high urban density = lower project viability."
        ),
        fatal_flag=False,
        weight_default=0.18,
        geometry_type="polygon",  # after raster→vector conversion
        analysis_type="intersect",
    ),

    # ── PHYSICAL CONSTRAINTS ─────────────────────────────────────────────────

    "steep_slopes": DataSource(
        layer_name="steep_slopes",
        display_name="USGS 3DEP 30m DEM — Slopes >15%",
        category="physical",
        primary_url=(
            "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/"
            "TIFF/current/USGS_1_arc_second_n48w100_20230703.tif"
        ),
        alt_urls=[
            # TNM API for bbox-based DEM download
            "https://tnmaccess.nationalmap.gov/api/v1/products"
            "?datasets=National+Elevation+Dataset+(NED)+1+arc-second"
            "&bbox={west},{south},{east},{north}&outputFormat=JSON",
            "https://www.usgs.gov/3dep-products-services",
        ],
        file_format="tiff",
        expected_crs="EPSG:4269",  # NAD83 geographic — typical for 3DEP
        typical_size_mb=5000.0,
        update_frequency="As-updated (continuous improvement program)",
        agency="USGS 3DEP",
        notes=(
            "CONUS seamless DEM is ~30 GB total. Use TNM API to download tiles "
            "intersecting CONUS by state or bbox. "
            "ETL: GDAL gdaldem → slope raster → threshold >15% → vectorize → simplify. "
            "Grading is possible; not auto-fatal."
        ),
        fatal_flag=False,
        weight_default=0.22,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "high_elevation": DataSource(
        layer_name="high_elevation",
        display_name="USGS 3DEP 30m DEM — Elevation >2500m",
        category="physical",
        primary_url=(
            "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/"
            "TIFF/current/USGS_1_arc_second_n48w100_20230703.tif"
        ),
        alt_urls=[
            "https://tnmaccess.nationalmap.gov/api/v1/products"
            "?datasets=National+Elevation+Dataset+(NED)+1+arc-second"
            "&outputFormat=JSON",
        ],
        file_format="tiff",
        expected_crs="EPSG:4269",
        typical_size_mb=5000.0,
        update_frequency="As-updated",
        agency="USGS 3DEP",
        notes=(
            "Reuses the same DEM downloaded for steep_slopes (no duplicate download). "
            "Threshold: >2500m MSL (~8200 ft). "
            "Logistical constraints: access roads, equipment delivery, cold temps, "
            "O&M challenges. Not auto-fatal."
        ),
        fatal_flag=False,
        weight_default=0.12,
        geometry_type="polygon",
        analysis_type="intersect",
    ),

    "contaminated_sites": DataSource(
        layer_name="contaminated_sites",
        display_name="EPA Superfund NPL + Brownfields",
        category="physical",
        primary_url=(
            "https://www.epa.gov/sites/default/files/2016-05/npl_geojson.json"
        ),
        alt_urls=[
            # ECHO facility query for brownfields
            "https://echodata.epa.gov/echo/rest/services/ECHO_Facilities/"
            "MapServer/0/query?where=FAC_ACTIVE_FLAG%3D'Y'"
            "&outFields=REGISTRY_ID,FAC_NAME,FAC_LAT,FAC_LONG"
            "&f=json&resultRecordCount=2000",
            "https://www.epa.gov/superfund/search-superfund-sites-where-you-live",
            # EPA ATTAINS / WATERS
            "https://www.epa.gov/enviro/facts-envirofacts-data-service-api",
        ],
        file_format="geojson",
        expected_crs="EPSG:4326",
        typical_size_mb=10.0,
        update_frequency="Quarterly",
        agency="US EPA",
        notes=(
            "NPL (National Priorities List) = Superfund = fatal_flag=TRUE. "
            "Brownfields = high risk but potentially developable. "
            "Point layer; ETL creates 402m (~1320ft) buffer for polygon analysis. "
            "Key attributes: Site_Name, EPA_ID, Status."
        ),
        fatal_flag=False,  # per-feature: NPL = fatal
        weight_default=0.48,
        geometry_type="point",
        analysis_type="proximity",
    ),
}


def get_source(layer_name: str) -> DataSource:
    """Retrieve DataSource by layer name. Raises KeyError if not found."""
    if layer_name not in REGISTRY:
        raise KeyError(f"No data source registered for layer '{layer_name}'")
    return REGISTRY[layer_name]


def list_sources() -> list[str]:
    """Return all registered layer names."""
    return list(REGISTRY.keys())


def get_by_category(category: str) -> list[DataSource]:
    """Return all sources for a given category."""
    return [s for s in REGISTRY.values() if s.category == category]

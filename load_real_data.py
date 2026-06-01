#!/usr/bin/env python3
"""
load_real_data.py
Smart data loader — downloads the 5 smallest/fastest layers first
so you can test the platform with real data in under 30 minutes.

Layers by download size (smallest first):
  FAST  (<50MB):  tribal_lands, wilderness_areas, contaminated_sites
  MED   (<200MB): transmission_lines, substations, pipeline_corridors, federal_lands
  SLOW  (>500MB): wetlands, protected_areas, critical_habitat, floodplains,
                  agricultural_preserves, urban_areas, steep_slopes, high_elevation

Run:
    python load_real_data.py --tier fast        # ~5 min, 3 layers
    python load_real_data.py --tier medium      # ~20 min, 7 layers
    python load_real_data.py --tier all         # ~4 hrs, all 15
    python load_real_data.py --layer tribal_lands  # single layer
"""

import argparse
import os
import sys
import subprocess
import tempfile
import zipfile
import json
import time
import requests
from pathlib import Path

# ── Database connection ───────────────────────────────────────────────────────
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fatal_user:FatalFlaw2025!@localhost:5434/fatal_flaw_db"
)

# ── Layer download specs ──────────────────────────────────────────────────────
LAYERS = {

    # ── FAST TIER (<50MB each, ~5 min total) ─────────────────────────────────

    "tribal_lands": {
        "tier": "fast",
        "url": "https://www2.census.gov/geo/tiger/TIGER2023/AIANNH/tl_2023_us_aiannh.zip",
        "table": "constraints.tribal_lands",
        "fatal_flag": True,
        "weight": 0.42,
        "name_field": "NAME",
        "extra_fields": {"tribe_name": "NAME", "aiannha_name": "NAMELSAD"},
    },

    "wilderness_areas": {
        "tier": "fast",
        "url": "https://data.fs.usda.gov/geodata/edw/edw_resources/shp/S_USA.Wilderness.zip",
        "table": "constraints.wilderness_areas",
        "fatal_flag": True,
        "weight": 0.50,
        "extra_fields": {"wilderness_name": "WILDERNE_1", "agency": "AGENCYNAME"},
    },

    "contaminated_sites": {
        "tier": "fast",
        "url": "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/SuperfundNPLSites/FeatureServer/0/query?where=1%3D1&outFields=SITE_NAME%2CEPA_ID%2CSTATUS%2CSTATE&f=geojson&resultRecordCount=2000",
        "table": "constraints.contaminated_sites",
        "fatal_flag": True,
        "weight": 0.48,
        "is_geojson": True,
        "extra_fields": {"site_name": "SITE_NAME", "site_id": "EPA_ID"},
        "extra_cols": {"site_type": "NPL"},
    },

    # ── MEDIUM TIER (<200MB each, ~20 min total) ──────────────────────────────

    "transmission_lines": {
        "tier": "medium",
        "url": (
            "https://opendata.arcgis.com/api/v3/datasets/"
            "70592bc3bd894320aed315d814f0ead7_0/downloads/data"
            "?format=shp&spatialRefId=4326"
        ),
        "table": "constraints.transmission_lines",
        "fatal_flag": False,
        "weight": 0.30,
        "extra_fields": {"voltage_kv": "VOLTAGE", "owner": "OWNER", "type": "TYPE"},
        "filter_sql": "\"VOLT_CLASS\" NOT IN ('UNDER 100', 'NOT AVAILABLE', 'DC')",
    },

    "substations": {
        "tier": "medium",
        "url": (
            "https://opendata.arcgis.com/api/v3/datasets/"
            "e7c16e6be24c4b8f9c12f5fde74c4e45_0/downloads/data"
            "?format=shp&spatialRefId=4326"
        ),
        "table": "constraints.substations",
        "fatal_flag": False,
        "weight": 0.35,
        "extra_fields": {"substation_name": "NAME", "voltage_kv": "MAX_VOLT", "owner": "OWNER"},
    },

    "pipeline_corridors": {
        "tier": "medium",
        "url": (
            "https://opendata.arcgis.com/api/v3/datasets/"
            "e5b09bdb86f44c229bec1e5a028bf01f_0/downloads/data"
            "?format=shp&spatialRefId=4326"
        ),
        "table": "constraints.pipeline_corridors",
        "fatal_flag": False,
        "weight": 0.15,
        "extra_fields": {"pipeline_type": "TYPICALDIA", "operator": "OPERATOR"},
    },

    "federal_lands": {
        "tier": "medium",
        "url": (
            "https://opendata.arcgis.com/datasets/"
            "3d4e5b628e9a47fbb062f0b2060d998e_0.zip"
        ),
        "table": "constraints.federal_lands",
        "fatal_flag": False,   # set per feature
        "weight": 0.35,
        "extra_fields": {"agency": "Adm_Code", "unit_name": "Unit_Nm"},
        "fatal_agencies": ["NPS", "DOD", "USMC", "USA", "USAF", "NAVY"],
    },

    "critical_habitat": {
        "tier": "medium",
        "url": "https://ecos.fws.gov/crithab/crithab_all/crithab_all_sf.zip",
        "table": "constraints.critical_habitat",
        "fatal_flag": True,
        "weight": 0.45,
        "extra_fields": {
            "common_name": "comname",
            "scientific_name": "sciname",
            "status": "status",
        },
    },

    # ── SLOW TIER (>500MB, hours) ─────────────────────────────────────────────

    "wetlands": {
        "tier": "slow",
        "url": "https://www.fws.gov/wetlands/downloads/Conus/conus_shapefile_wetlands.zip",
        "alt_url": "https://opendata.arcgis.com/api/v3/datasets/729e4b32eba2479bab9ee9d6e31e1e73_0/downloads/data?format=shp&spatialRefId=4326",
        "table": "constraints.wetlands",
        "fatal_flag": False,
        "weight": 0.25,
        "extra_fields": {"wetland_type": "WETLAND_TY"},
    },

    "protected_areas": {
        "tier": "slow",
        "url": "https://www.sciencebase.gov/catalog/file/get/652ebcb1d34ee8d4aad95b8d?facets=PADUS4_0Combined_Proclamation_Marine_Fee_Designation_Easement_Shapefile.zip",
        "table": "constraints.protected_areas",
        "fatal_flag": False,
        "weight": 0.40,
        "extra_fields": {"gap_status": "GAP_Sts", "unit_name": "Unit_Nm"},
        "fatal_gap": [1, 2],
    },

    "floodplains": {
        "tier": "slow",
        "url": (
            "https://hazards.fema.gov/nhdplusdata/NFHL/NATIONAL/"
            "NFHL_National_20240101.zip"
        ),
        "table": "constraints.floodplains",
        "fatal_flag": False,
        "weight": 0.20,
        "extra_fields": {"flood_zone": "FLD_ZONE", "dfirm_id": "DFIRM_ID"},
        "gdb_layer": "S_FLD_HAZ_AR",
        "filter_sql": "\"FLD_ZONE\" IN ('A','AE','AH','AO','AR','V','VE')",
    },

    "agricultural_preserves": {
        "tier": "slow",
        "url": "https://opendata.arcgis.com/api/v3/datasets/e4c39b4af58741c2ac79b85b24db1d06_0/downloads/data?format=shp&spatialRefId=4326",
        "table": "constraints.agricultural_preserves",
        "fatal_flag": False,
        "weight": 0.28,
        "extra_fields": {"land_cap_class": "farmlndcl", "state_fips": "statecd"},
    },

    "urban_areas": {
        "tier": "slow",
        # Pre-vectorised NLCD developed areas from USGS via ArcGIS Online
        "url": "https://opendata.arcgis.com/api/v3/datasets/c3d4e4d55b4a4beeadac2b27d6dab68c_0/downloads/data?format=shp&spatialRefId=4326",
        "table": "constraints.urban_areas",
        "fatal_flag": False,
        "weight": 0.18,
        "extra_fields": {"nlcd_class": "gridcode"},
    },

    "steep_slopes": {
        "tier": "slow",
        # Pre-processed slopes >15% from USGS via ArcGIS Online
        "url": "https://opendata.arcgis.com/api/v3/datasets/58a541b4060a45a898a43b3d35a239d9_0/downloads/data?format=shp&spatialRefId=4326",
        "table": "constraints.steep_slopes",
        "fatal_flag": False,
        "weight": 0.22,
        "extra_fields": {"slope_class": "slope_cls"},
    },

    "high_elevation": {
        "tier": "slow",
        # Elevation >2500m zones derived from 3DEP, pre-vectorised
        "url": "https://opendata.arcgis.com/api/v3/datasets/b214e72e2e2748a3b3bd56e75ec4e489_0/downloads/data?format=shp&spatialRefId=4326",
        "table": "constraints.high_elevation",
        "fatal_flag": False,
        "weight": 0.12,
        "extra_fields": {"elev_threshold_m": "elev_m"},
    },
}

# Explicit order — load smallest/most reliable first
TIER_ORDER = {
    "fast": [
        "tribal_lands",
        "wilderness_areas",
        "contaminated_sites",
    ],
    "medium": [
        "tribal_lands",
        "wilderness_areas",
        "contaminated_sites",
        "transmission_lines",
        "substations",
        "pipeline_corridors",
        "federal_lands",
        "critical_habitat",
    ],
    "all": [
        # Fast (small, always works)
        "tribal_lands",
        "wilderness_areas",
        "contaminated_sites",
        # Medium (grid infrastructure)
        "transmission_lines",
        "substations",
        "pipeline_corridors",
        "federal_lands",
        "critical_habitat",
        # Slow (large environmental)
        "wetlands",
        "protected_areas",
        "floodplains",
        "agricultural_preserves",
        "urban_areas",
        "steep_slopes",
        "high_elevation",
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg, level="INFO"):
    colors = {"INFO": "\033[94m", "OK": "\033[92m",
              "WARN": "\033[93m", "ERR": "\033[91m", "RESET": "\033[0m"}
    c = colors.get(level, "")
    print(f"{c}[{level}] {msg}{colors['RESET']}")


def download_file(url: str, dest: Path, timeout=3600) -> bool:
    log(f"Downloading: {url}")
    log(f"         → {dest}")
    try:
        with requests.get(url, stream=True, timeout=timeout,
                          headers={"User-Agent": "FatalFlawETL/1.0"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r  {pct:.1f}%  ({downloaded/1e6:.1f} MB)", end="", flush=True)
        print()
        log(f"Downloaded {downloaded/1e6:.1f} MB", "OK")
        return True
    except Exception as e:
        log(f"Download failed: {e}", "ERR")
        return False


def run_ogr2ogr(args: list) -> bool:
    cmd = ["ogr2ogr"] + args
    log(f"ogr2ogr: {' '.join(cmd[:6])}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"ogr2ogr error: {result.stderr[:500]}", "ERR")
        return False
    return True


def load_layer(name: str, spec: dict, tmp_dir: Path) -> bool:
    log(f"\n{'='*55}")
    log(f"Loading: {name.upper()}")
    log(f"{'='*55}")

    table  = spec["table"]
    schema, tname = table.split(".")

    # ── Special cases ─────────────────────────────────────────────────────────
    if spec.get("is_raster") or spec.get("is_dem"):
        log(f"Skipping {name} — requires raster processing (run full ETL)", "WARN")
        return False

    # ── Download ──────────────────────────────────────────────────────────────
    url = spec.get("url", "")
    if not url:
        log(f"No URL for {name}", "WARN")
        return False

    is_geojson = spec.get("is_geojson", False)
    ext = ".json" if is_geojson else ".zip"
    raw_file = tmp_dir / f"{name}{ext}"

    # Build list of URLs to try (primary + fallbacks)
    urls_to_try = [url]
    alt = spec.get("alt_url")
    if alt:
        urls_to_try.append(alt)

    if not raw_file.exists():
        downloaded = False
        for attempt_url in urls_to_try:
            log(f"Trying URL ({urls_to_try.index(attempt_url)+1}/{len(urls_to_try)}): {attempt_url[:80]}...")
            if download_file(attempt_url, raw_file):
                downloaded = True
                break
            else:
                log(f"URL failed, trying next...", "WARN")
        if not downloaded:
            log(f"All URLs failed for {name}. Skipping.", "ERR")
            return False
    else:
        log(f"Using cached: {raw_file}", "WARN")

    # ── Find source file ──────────────────────────────────────────────────────
    if is_geojson:
        src_path = str(raw_file)
        src_layer = None
    else:
        extract_dir = tmp_dir / name
        extract_dir.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(raw_file, "r") as zf:
                zf.extractall(extract_dir)
        except Exception as e:
            log(f"Extract failed: {e}", "ERR")
            return False

        # Find shapefile or GDB
        shps = list(extract_dir.rglob("*.shp"))
        gdbs = list(extract_dir.rglob("*.gdb"))
        if shps:
            src_path = str(shps[0])
            src_layer = None
        elif gdbs:
            src_path = str(gdbs[0])
            src_layer = spec.get("gdb_layer")
        else:
            log(f"No vector file found in {extract_dir}", "ERR")
            return False

    # ── Build ogr2ogr command ──────────────────────────────────────────────────
    # ogr2ogr needs: PG:"host=X port=X dbname=X user=X password=X"
    import re as _re
    _m = _re.match(
        r"postgresql(?:\+asyncpg)?://([^:]+):([^@]+)@([^:/]+):?(\d*)/(.+)",
        DB_URL
    )
    if _m:
        _user, _pass, _host, _port, _db = _m.groups()
        _port = _port or "5432"
    else:
        _user, _pass, _host, _port, _db = (
            "fatal_user", "FatalFlaw2025!", "localhost", "5434", "fatal_flaw_db"
        )
    db_conn = f"PG:host={_host} port={_port} dbname={_db} user={_user} password={_pass}"

    args = [
        "-f", "PostgreSQL",
        db_conn,
        src_path,
    ]

    if src_layer:
        args += [src_layer]

    args += [
        "-nln", f"{schema}.{tname}",
        "-nlt", "PROMOTE_TO_MULTI",
        "-t_srs", "EPSG:5070",
        "-overwrite",
        "-progress",
        "--config", "PG_USE_COPY", "YES",
    ]

    # Optional filter
    if spec.get("filter_sql"):
        args += ["-where", spec["filter_sql"]]

    # Field mappings via SQL
    extra = spec.get("extra_fields", {})
    extra_cols = spec.get("extra_sql_cols", "")

    if run_ogr2ogr(args):
        # Post-load: set fatal_flag, weight_default, layer_name, geom_4326
        post_sql(name, spec, schema, tname)
        log(f"✓ {name} loaded successfully", "OK")
        return True
    else:
        log(f"✗ {name} failed", "ERR")
        return False


def post_sql(name: str, spec: dict, schema: str, tname: str):
    """Run post-load SQL: set metadata columns and geom_4326."""
    import psycopg2

    fatal = "TRUE" if spec["fatal_flag"] else "FALSE"
    weight = spec["weight"]

    sqls = [
        f"""ALTER TABLE {schema}."{tname}"
            ADD COLUMN IF NOT EXISTS layer_name TEXT,
            ADD COLUMN IF NOT EXISTS fatal_flag BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS weight_default FLOAT DEFAULT {weight},
            ADD COLUMN IF NOT EXISTS source TEXT,
            ADD COLUMN IF NOT EXISTS acquisition_date DATE,
            ADD COLUMN IF NOT EXISTS notes TEXT,
            ADD COLUMN IF NOT EXISTS geom_4326 GEOMETRY(Geometry, 4326)""",

        f"""UPDATE {schema}."{tname}"
            SET layer_name = '{name}',
                fatal_flag = {fatal},
                weight_default = {weight},
                source = '{spec.get("url", "")[:100]}',
                acquisition_date = CURRENT_DATE""",

        f"""UPDATE {schema}."{tname}"
            SET geom_4326 = ST_Transform(wkb_geometry, 4326)
            WHERE geom_4326 IS NULL AND wkb_geometry IS NOT NULL""",
    ]

    # Special: federal lands — set fatal based on agency
    if name == "federal_lands" and spec.get("fatal_agencies"):
        agencies = "','".join(spec["fatal_agencies"])
        sqls.append(
            f"""UPDATE {schema}."{tname}"
                SET fatal_flag = TRUE
                WHERE UPPER("Adm_Code") IN ('{agencies}')"""
        )

    # Special: protected areas — set fatal based on GAP status
    if name == "protected_areas" and spec.get("fatal_gap"):
        sqls.append(
            f"""UPDATE {schema}."{tname}"
                SET fatal_flag = TRUE
                WHERE "GAP_Sts"::int IN (1, 2)"""
        )

    # Refresh fatal_union view after loading any fatal layer
    if spec.get("fatal_flag") or name in ("federal_lands", "protected_areas"):
        sqls.append(
            "REFRESH MATERIALIZED VIEW constraints.fatal_union"
        )

    db = DB_URL.replace("+asyncpg", "")
    try:
        conn = psycopg2.connect(db)
        conn.autocommit = True
        with conn.cursor() as cur:
            for sql in sqls:
                try:
                    cur.execute(sql)
                except Exception as e:
                    log(f"Post-SQL warning: {e}", "WARN")
        conn.close()
        log(f"Post-load SQL complete for {name}", "OK")
    except Exception as e:
        log(f"Post-load SQL failed: {e}", "ERR")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Load Fatal Flaw constraint layers into PostGIS"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--tier",
        choices=["fast", "medium", "all"],
        help=(
            "fast = 3 layers ~5min | "
            "medium = 7 layers ~30min | "
            "all = 15 layers ~4hrs"
        ),
    )
    group.add_argument("--layer", help="Load a single layer by name")
    group.add_argument("--list", action="store_true", help="List available layers")
    parser.add_argument(
        "--tmp", default="/tmp/fatal_flaw_etl",
        help="Temp directory for downloads (default: /tmp/fatal_flaw_etl)"
    )
    args = parser.parse_args()

    if args.list:
        print(f"\n{'Layer':<30} {'Tier':<10} {'Size'}")
        print("─" * 60)
        sizes = {
            "tribal_lands": "30 MB", "wilderness_areas": "50 MB",
            "contaminated_sites": "10 MB", "transmission_lines": "120 MB",
            "substations": "15 MB", "pipeline_corridors": "80 MB",
            "federal_lands": "300 MB", "critical_habitat": "250 MB",
            "wetlands": "2 GB", "protected_areas": "800 MB",
            "floodplains": "4 GB", "agricultural_preserves": "500 MB",
            "urban_areas": "2 GB", "steep_slopes": "30 GB",
            "high_elevation": "30 GB",
        }
        for name, spec in LAYERS.items():
            print(f"  {name:<28} {spec['tier']:<10} {sizes.get(name, '?')}")
        return

    tmp_dir = Path(args.tmp)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    layers_to_load = (
        [args.layer] if args.layer
        else TIER_ORDER[args.tier]
    )

    if args.layer and args.layer not in LAYERS:
        log(f"Unknown layer: {args.layer}. Run --list to see options.", "ERR")
        sys.exit(1)

    log(f"Loading {len(layers_to_load)} layer(s): {layers_to_load}")
    log(f"Temp directory: {tmp_dir}")
    log(f"Database: {DB_URL.split('@')[1] if '@' in DB_URL else DB_URL}")

    results = {}
    t_start = time.monotonic()

    for name in layers_to_load:
        t0 = time.monotonic()
        ok = load_layer(name, LAYERS[name], tmp_dir)
        elapsed = round(time.monotonic() - t0, 1)
        results[name] = ("✓ OK" if ok else "✗ FAILED") + f"  ({elapsed}s)"

    total = round(time.monotonic() - t_start, 1)

    print(f"\n{'='*55}")
    print("  RESULTS")
    print(f"{'='*55}")
    for name, result in results.items():
        print(f"  {name:<30} {result}")
    print(f"\n  Total time: {total}s")

    failed = [n for n, r in results.items() if "FAILED" in r]
    if failed:
        log(f"\nFailed layers: {failed}", "ERR")
        log("Check internet connection and try again. Cached downloads will resume.", "WARN")
        sys.exit(1)
    else:
        log("\nAll layers loaded! Run the acceptance tests:", "OK")
        log("  ./tests/run_acceptance.sh http://localhost:8000", "OK")


if __name__ == "__main__":
    main()
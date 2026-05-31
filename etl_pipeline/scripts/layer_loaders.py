"""
etl_pipeline/scripts/layer_loaders.py
Concrete ETL loader for each of the 15 constraint layers.
Each class inherits ETLBase and implements download() + process().
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import box, mapping
from shapely.ops import unary_union

from etl_pipeline.base.etl_base import ETLBase, CRS_5070, CRS_4326

logger = logging.getLogger(__name__)

# ── Utility: run ogr2ogr ─────────────────────────────────────────────────────

def _ogr2ogr(args: list[str]) -> None:
    cmd = ["ogr2ogr"] + args
    logger.debug("ogr2ogr: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ogr2ogr failed: {result.stderr}")


# ════════════════════════════════════════════════════════════════════════════
# ENVIRONMENTAL LAYERS
# ════════════════════════════════════════════════════════════════════════════

class WetlandsLoader(ETLBase):
    """NWI Wetlands — national polygon download."""

    @property
    def layer_name(self) -> str:
        return "wetlands"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get(
            "conus_download_url",
            "https://www.fws.gov/wetlands/downloads/Conus/conus_shapefile_wetlands.zip",
        )
        dest = dest_dir / "wetlands.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        if shp is None:
            raise FileNotFoundError(f"No shapefile in {extract_dir}")
        gdf = gpd.read_file(shp)
        # Rename attribute
        if "WETLAND_TY" in gdf.columns:
            gdf = gdf.rename(columns={"WETLAND_TY": "wetland_type"})
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.25
        return gdf[["geometry", "wetland_type", "fatal_flag", "weight_default"]]


class ProtectedAreasLoader(ETLBase):
    """PAD-US Protected Areas — set fatal_flag based on GAP status."""

    @property
    def layer_name(self) -> str:
        return "protected_areas"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("download_url")
        dest = dest_dir / "padus.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp", ".gdb"])
        if shp is None:
            raise FileNotFoundError(f"No vector file in {extract_dir}")

        gdf = gpd.read_file(str(shp))

        # Normalize GAP status
        gap_col = next((c for c in gdf.columns if "gap" in c.lower()), None)
        if gap_col:
            gdf["gap_status"] = pd.to_numeric(gdf[gap_col], errors="coerce")
        else:
            gdf["gap_status"] = None

        gdf["fatal_flag"] = gdf["gap_status"].isin([1, 2])
        gdf["unit_name"] = gdf.get("Unit_Nm", gdf.get("UNIT_NM", ""))
        gdf["manager_type"] = gdf.get("Mang_Type", gdf.get("MANG_TYPE", ""))
        gdf["weight_default"] = 0.40
        return gdf[["geometry", "gap_status", "unit_name", "manager_type",
                     "fatal_flag", "weight_default"]]


class CriticalHabitatLoader(ETLBase):
    """USFWS Critical Habitat — all intersections are fatal."""

    @property
    def layer_name(self) -> str:
        return "critical_habitat"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get(
            "download_url",
            "https://ecos.fws.gov/crithab/crithab_all/crithab_all_sf.zip",
        )
        dest = dest_dir / "critical_habitat.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        if shp is None:
            raise FileNotFoundError(f"No shapefile in {extract_dir}")
        gdf = gpd.read_file(shp)
        col_map = {"comname": "common_name", "sciname": "scientific_name", "status": "status"}
        for src, dst in col_map.items():
            if src in gdf.columns:
                gdf = gdf.rename(columns={src: dst})
        gdf["fatal_flag"] = True
        gdf["weight_default"] = 0.45
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["common_name", "scientific_name", "status"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


class FloodplainsLoader(ETLBase):
    """FEMA NFHL 100-year floodplains."""

    @property
    def layer_name(self) -> str:
        return "floodplains"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("alt_url",
            "https://hazards.fema.gov/nhdplusdata/NFHL/NATIONAL/NFHL_National_20240101.zip")
        dest = dest_dir / "fema_nfhl.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        # Try GDB first, then shapefile
        gdb = self.find_file(extract_dir, [".gdb"])
        shp = self.find_file(extract_dir, [".shp"])
        source = str(gdb or shp)
        if gdb:
            gdf = gpd.read_file(source, layer="S_FLD_HAZ_AR")
        else:
            gdf = gpd.read_file(source)
        # Filter to 100-year zones
        if "FLD_ZONE" in gdf.columns:
            gdf = gdf[gdf["FLD_ZONE"].isin(["A", "AE", "AH", "AO", "AR", "V", "VE"])]
            gdf = gdf.rename(columns={"FLD_ZONE": "flood_zone"})
        if "DFIRM_ID" in gdf.columns:
            gdf = gdf.rename(columns={"DFIRM_ID": "dfirm_id"})
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.20
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["flood_zone", "dfirm_id"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


class WildernessAreasLoader(ETLBase):
    """USFS + BLM Wilderness Areas — always fatal."""

    @property
    def layer_name(self) -> str:
        return "wilderness_areas"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get(
            "download_url",
            "https://data.fs.usda.gov/geodata/edw/edw_resources/shp/S_USA.Wilderness.zip",
        )
        dest = dest_dir / "wilderness.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        if shp is None:
            raise FileNotFoundError(f"No shapefile in {extract_dir}")
        gdf = gpd.read_file(shp)
        name_col = next((c for c in gdf.columns if "WILDERNE" in c.upper()), None)
        if name_col:
            gdf = gdf.rename(columns={name_col: "wilderness_name"})
        agency_col = next((c for c in gdf.columns if "ADMIN" in c.upper()), None)
        if agency_col:
            gdf = gdf.rename(columns={agency_col: "agency"})
        gdf["fatal_flag"] = True
        gdf["weight_default"] = 0.50
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["wilderness_name", "agency"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


# ════════════════════════════════════════════════════════════════════════════
# GRID INFRASTRUCTURE LAYERS
# ════════════════════════════════════════════════════════════════════════════

class TransmissionLinesLoader(ETLBase):
    """HIFLD Transmission Lines >100kV."""

    @property
    def layer_name(self) -> str:
        return "transmission_lines"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("download_url")
        dest = dest_dir / "transmission_lines.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        gdf = gpd.read_file(shp)
        # Filter >100kV
        if "VOLT_CLASS" in gdf.columns:
            gdf = gdf[~gdf["VOLT_CLASS"].isin(["UNDER 100", "NOT AVAILABLE", "DC"])]
        col_map = {"VOLTAGE": "voltage_kv", "OWNER": "owner", "TYPE": "type"}
        for src, dst in col_map.items():
            if src in gdf.columns:
                gdf = gdf.rename(columns={src: dst})
        if "voltage_kv" in gdf.columns:
            gdf["voltage_kv"] = pd.to_numeric(gdf["voltage_kv"], errors="coerce")
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.30
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["voltage_kv", "owner", "type"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


class SubstationsLoader(ETLBase):
    """HIFLD Electric Substations."""

    @property
    def layer_name(self) -> str:
        return "substations"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("download_url")
        dest = dest_dir / "substations.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        gdf = gpd.read_file(shp)
        col_map = {"NAME": "substation_name", "MAX_VOLT": "voltage_kv", "OWNER": "owner"}
        for src, dst in col_map.items():
            if src in gdf.columns:
                gdf = gdf.rename(columns={src: dst})
        if "voltage_kv" in gdf.columns:
            gdf["voltage_kv"] = pd.to_numeric(gdf["voltage_kv"], errors="coerce")
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.35
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["substation_name", "voltage_kv", "owner"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


class PipelineCorridorsLoader(ETLBase):
    """HIFLD Natural Gas Pipelines."""

    @property
    def layer_name(self) -> str:
        return "pipeline_corridors"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("download_url")
        dest = dest_dir / "pipeline_corridors.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        gdf = gpd.read_file(shp)
        col_map = {"TYPICALDIA": "pipeline_type", "OPERATOR": "operator"}
        for src, dst in col_map.items():
            if src in gdf.columns:
                gdf = gdf.rename(columns={src: dst})
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.15
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["pipeline_type", "operator"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


# ════════════════════════════════════════════════════════════════════════════
# LAND USE / ZONING LAYERS
# ════════════════════════════════════════════════════════════════════════════

class AgriculturalPreservesLoader(ETLBase):
    """USDA NRCS Important Farmland."""

    @property
    def layer_name(self) -> str:
        return "agricultural_preserves"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("download_url")
        dest = dest_dir / "agricultural_preserves.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        gdf = gpd.read_file(shp)
        col_map = {"farmlndcl": "land_cap_class", "statecd": "state_fips"}
        for src, dst in col_map.items():
            if src in gdf.columns:
                gdf = gdf.rename(columns={src: dst})
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.28
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["land_cap_class", "state_fips"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


class FederalLandsLoader(ETLBase):
    """BLM Surface Management Areas — NPS/DOD = fatal."""

    @property
    def layer_name(self) -> str:
        return "federal_lands"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("alt_url")
        dest = dest_dir / "federal_lands.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        gdf = gpd.read_file(shp)
        agency_col = next(
            (c for c in gdf.columns if c.upper() in ["ADM_CODE", "AGENCY", "AGENCYCODE"]), None
        )
        if agency_col:
            gdf = gdf.rename(columns={agency_col: "agency"})
        name_col = next((c for c in gdf.columns if "UNIT" in c.upper() and "NM" in c.upper()), None)
        if name_col:
            gdf = gdf.rename(columns={name_col: "unit_name"})
        fatal_agencies = {"NPS", "DOD", "USMC", "USA", "USAF", "NAVY", "DOD-ARMY"}
        if "agency" in gdf.columns:
            gdf["fatal_flag"] = gdf["agency"].str.upper().isin(fatal_agencies)
        else:
            gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.35
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["agency", "unit_name"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


class TribalLandsLoader(ETLBase):
    """Census TIGER Tribal Lands — always fatal."""

    @property
    def layer_name(self) -> str:
        return "tribal_lands"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get(
            "download_url",
            "https://www2.census.gov/geo/tiger/TIGER2023/AIANNH/tl_2023_us_aiannh.zip",
        )
        dest = dest_dir / "tribal_lands.zip"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        extract_dir = self.extract_zip(raw_path)
        shp = self.find_file(extract_dir, [".shp"])
        gdf = gpd.read_file(shp)
        col_map = {"NAME": "tribe_name", "NAMELSAD": "aiannha_name"}
        for src, dst in col_map.items():
            if src in gdf.columns:
                gdf = gdf.rename(columns={src: dst})
        gdf["fatal_flag"] = True
        gdf["weight_default"] = 0.42
        keep = ["geometry", "fatal_flag", "weight_default"]
        for c in ["tribe_name", "aiannha_name"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


class UrbanAreasLoader(ETLBase):
    """NLCD Developed classes — raster to vector conversion."""

    @property
    def layer_name(self) -> str:
        return "urban_areas"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get("download_url")
        dest = dest_dir / "nlcd_landcover.img"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        """
        Vectorize NLCD developed classes (21-24) using GDAL.
        Returns polygon GeoDataFrame in EPSG:5070.
        """
        try:
            import rasterio
            from rasterio.features import shapes
            from rasterio.mask import mask as rio_mask
        except ImportError:
            raise ImportError("rasterio required for NLCD processing: pip install rasterio")

        developed_classes = self.layer_config.get("developed_classes", [21, 22, 23, 24])
        simplify_tol = self.layer_config.get("simplify_tolerance_m", 30)

        logger.info("[urban_areas] Vectorizing NLCD raster — this may take several minutes …")

        with rasterio.open(str(raw_path)) as src:
            data = src.read(1)
            transform = src.transform
            crs = src.crs

            # Create binary mask for developed classes
            mask = np.isin(data, developed_classes).astype(np.uint8)

            geom_list = []
            class_list = []
            for geom, value in shapes(mask, transform=transform):
                if value == 1:
                    geom_list.append(geom)
                    # Determine dominant NLCD class
                    class_list.append(21)  # simplified; detailed class mapping omitted

        if not geom_list:
            logger.warning("[urban_areas] No developed pixels found in raster")
            return gpd.GeoDataFrame(geometry=[], crs=crs)

        from shapely.geometry import shape
        geometries = [shape(g) for g in geom_list]
        gdf = gpd.GeoDataFrame({"geometry": geometries, "nlcd_class": class_list}, crs=crs)
        gdf["geometry"] = gdf["geometry"].simplify(simplify_tol, preserve_topology=True)
        gdf = gdf[~gdf.geometry.is_empty].copy()
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.18
        gdf["nlcd_year"] = 2021
        return gdf[["geometry", "nlcd_class", "nlcd_year", "fatal_flag", "weight_default"]]


# ════════════════════════════════════════════════════════════════════════════
# PHYSICAL CONSTRAINT LAYERS
# ════════════════════════════════════════════════════════════════════════════

class SteepSlopesLoader(ETLBase):
    """USGS 3DEP DEM → slope >15% → vectorized polygons."""

    @property
    def layer_name(self) -> str:
        return "steep_slopes"

    def download(self, dest_dir: Path) -> Path:
        """Download DEM tiles via TNM API or staged product URL."""
        url = self.layer_config.get("download_url")
        dest = dest_dir / "dem_conus.tif"
        # Note: full CONUS DEM is ~30GB. Production use should tile by state.
        # For the MVP, download a representative staged product.
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        """DEM → gdaldem slope → threshold → vectorize."""
        try:
            import rasterio
            from rasterio.features import shapes
            import numpy as np
        except ImportError:
            raise ImportError("rasterio required: pip install rasterio")

        slope_path = raw_path.parent / "slope.tif"
        threshold_pct = self.layer_config.get("slope_threshold_pct", 15)
        simplify_tol = self.layer_config.get("simplify_tolerance_m", 30)

        # Compute slope raster using GDAL
        subprocess.run(
            ["gdaldem", "slope", str(raw_path), str(slope_path), "-p", "-compute_edges"],
            check=True,
        )

        logger.info("[steep_slopes] Vectorizing slope threshold >%d%%…", threshold_pct)
        with rasterio.open(str(slope_path)) as src:
            data = src.read(1)
            transform = src.transform
            crs = src.crs
            nodata = src.nodata

            if nodata is not None:
                data = np.where(data == nodata, 0, data)

            steep_mask = (data > threshold_pct).astype(np.uint8)

        from shapely.geometry import shape
        geom_list = [
            shape(g)
            for g, v in shapes(steep_mask, transform=transform)
            if v == 1
        ]
        gdf = gpd.GeoDataFrame(
            {"geometry": geom_list, "slope_class": f">{threshold_pct}%"},
            crs=crs,
        )
        gdf["geometry"] = gdf["geometry"].simplify(simplify_tol, preserve_topology=True)
        gdf = gdf[~gdf.geometry.is_empty].copy()
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.22
        return gdf[["geometry", "slope_class", "fatal_flag", "weight_default"]]


class HighElevationLoader(ETLBase):
    """USGS 3DEP DEM → elevation >2500m → vectorized polygons. Reuses DEM."""

    @property
    def layer_name(self) -> str:
        return "high_elevation"

    def download(self, dest_dir: Path) -> Path:
        """Check if steep_slopes already downloaded the DEM; reuse it."""
        steep_dem = Path(self.config["storage"]["data_dir"]) / "steep_slopes" / "dem_conus.tif"
        if steep_dem.exists():
            logger.info("[high_elevation] Reusing DEM from steep_slopes layer")
            return steep_dem
        url = self.layer_config.get("download_url")
        dest = dest_dir / "dem_conus.tif"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        try:
            import rasterio
            from rasterio.features import shapes
        except ImportError:
            raise ImportError("rasterio required: pip install rasterio")

        threshold_m = self.layer_config.get("elevation_threshold_m", 2500)
        simplify_tol = self.layer_config.get("simplify_tolerance_m", 50)

        logger.info("[high_elevation] Vectorizing elevation >%dm …", threshold_m)
        with rasterio.open(str(raw_path)) as src:
            data = src.read(1).astype(float)
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
            if nodata is not None:
                data = np.where(data == nodata, 0, data)

        elev_mask = (data > threshold_m).astype(np.uint8)
        from shapely.geometry import shape
        geom_list = [shape(g) for g, v in shapes(elev_mask, transform=transform) if v == 1]

        gdf = gpd.GeoDataFrame(
            {"geometry": geom_list, "elev_threshold_m": float(threshold_m)},
            crs=crs,
        )
        gdf["geometry"] = gdf["geometry"].simplify(simplify_tol, preserve_topology=True)
        gdf = gdf[~gdf.geometry.is_empty].copy()
        gdf["fatal_flag"] = False
        gdf["weight_default"] = 0.12
        return gdf[["geometry", "elev_threshold_m", "fatal_flag", "weight_default"]]


class ContaminatedSitesLoader(ETLBase):
    """EPA NPL Superfund (fatal) + Brownfields (high risk)."""

    @property
    def layer_name(self) -> str:
        return "contaminated_sites"

    def download(self, dest_dir: Path) -> Path:
        url = self.layer_config.get(
            "npl_download_url",
            "https://www.epa.gov/sites/default/files/2016-05/npl_geojson.json",
        )
        dest = dest_dir / "npl.geojson"
        return self.download_file(url, dest)

    def process(self, raw_path: Path) -> gpd.GeoDataFrame:
        gdf = gpd.read_file(str(raw_path))

        # Normalize attribute names
        col_map = {
            "Site_Name": "site_name", "SITE_NAME": "site_name",
            "EPA_ID": "site_id", "EPAID": "site_id",
            "Status": "status", "STATUS": "status",
        }
        for src, dst in col_map.items():
            if src in gdf.columns:
                gdf = gdf.rename(columns={src: dst})

        # All NPL = Superfund = fatal
        gdf["site_type"] = "NPL"
        gdf["fatal_flag"] = True   # NPL = always fatal
        gdf["weight_default"] = 0.48

        # Ensure point geometry
        gdf = gdf[gdf.geometry.geom_type.isin(["Point", "MultiPoint"])].copy()

        keep = ["geometry", "site_type", "fatal_flag", "weight_default"]
        for c in ["site_name", "site_id", "status"]:
            if c in gdf.columns:
                keep.append(c)
        return gdf[keep]


# ════════════════════════════════════════════════════════════════════════════
# LOADER REGISTRY — maps layer_name → loader class
# ════════════════════════════════════════════════════════════════════════════

LOADER_REGISTRY: dict[str, type[ETLBase]] = {
    "wetlands":               WetlandsLoader,
    "protected_areas":        ProtectedAreasLoader,
    "critical_habitat":       CriticalHabitatLoader,
    "floodplains":            FloodplainsLoader,
    "wilderness_areas":       WildernessAreasLoader,
    "transmission_lines":     TransmissionLinesLoader,
    "substations":            SubstationsLoader,
    "pipeline_corridors":     PipelineCorridorsLoader,
    "agricultural_preserves": AgriculturalPreservesLoader,
    "federal_lands":          FederalLandsLoader,
    "tribal_lands":           TribalLandsLoader,
    "urban_areas":            UrbanAreasLoader,
    "steep_slopes":           SteepSlopesLoader,
    "high_elevation":         HighElevationLoader,
    "contaminated_sites":     ContaminatedSitesLoader,
}


def get_loader(layer_name: str, config: dict, db_url: str) -> ETLBase:
    """Instantiate the correct loader for a given layer_name."""
    cls = LOADER_REGISTRY.get(layer_name)
    if cls is None:
        raise KeyError(f"No loader registered for layer '{layer_name}'. "
                       f"Available: {list(LOADER_REGISTRY.keys())}")
    return cls(config, db_url)

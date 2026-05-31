#!/usr/bin/env python3
"""
etl_pipeline/scripts/load_all.py
Full ETL run: download + process + load all 15 layers into PostGIS.
Run: python -m etl_pipeline.scripts.load_all [--layers ...] [--force] [--skip-download]
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from etl_pipeline.base.etl_base import load_config
from etl_pipeline.scripts.layer_loaders import LOADER_REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("load_all")


def main():
    parser = argparse.ArgumentParser(description="Load all Fatal Flaw constraint layers into PostGIS")
    parser.add_argument("--layers", help="Comma-separated layer names (default: all)")
    parser.add_argument("--force", action="store_true", help="Truncate and reload existing tables")
    parser.add_argument("--skip-download", action="store_true", help="Use existing files; skip download")
    parser.add_argument("--config", help="Path to config.yaml", default=None)
    parser.add_argument("--report", help="Write JSON summary to this path", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    db_url = os.environ["DATABASE_URL"]

    target_layers = (
        [l.strip() for l in args.layers.split(",")]
        if args.layers
        else list(LOADER_REGISTRY.keys())
    )

    logger.info(
        "Starting ETL for %d layers (force=%s, skip_download=%s)",
        len(target_layers), args.force, args.skip_download,
    )

    all_results = []
    t_start = time.monotonic()

    for layer_name in target_layers:
        if layer_name not in LOADER_REGISTRY:
            logger.warning("Unknown layer '%s' — skipping", layer_name)
            continue
        if not config["layers"].get(layer_name, {}).get("enabled", True):
            logger.info("Layer '%s' disabled — skipping", layer_name)
            continue

        loader_cls = LOADER_REGISTRY[layer_name]
        loader = loader_cls(config, db_url)

        t0 = time.monotonic()
        try:
            logger.info("══════ %s ══════", layer_name.upper())

            if args.skip_download:
                # Find already-downloaded file
                cached = loader._check_cache(force=False)
                if cached is None:
                    raise FileNotFoundError(
                        f"No cached file for '{layer_name}'; run without --skip-download first"
                    )
                raw_path = cached
                import geopandas as gpd
                gdf = loader.process(raw_path)
                gdf = loader._ensure_schema(gdf)
                rows_loaded, rows_failed = loader._load_to_postgis(gdf, args.force)
                loader._refresh_index()
                summary = {
                    "layer_name": layer_name,
                    "status": "success",
                    "rows_loaded": rows_loaded,
                    "rows_failed": rows_failed,
                    "elapsed_s": round(time.monotonic() - t0, 1),
                }
            else:
                summary = loader.run(force=args.force)
                summary["elapsed_s"] = round(time.monotonic() - t0, 1)

            logger.info(
                "✓ %s: %d rows in %.1fs",
                layer_name, summary.get("rows_loaded", 0), summary["elapsed_s"],
            )

        except Exception as exc:
            logger.exception("✗ %s failed: %s", layer_name, exc)
            summary = {
                "layer_name": layer_name,
                "status": "failed",
                "error": str(exc),
                "elapsed_s": round(time.monotonic() - t0, 1),
            }

        all_results.append(summary)

    # ── Refresh fatal_union materialized view ────────────────────────────────
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY constraints.fatal_union"))
            conn.commit()
        logger.info("✓ Refreshed constraints.fatal_union materialized view")
    except Exception as exc:
        logger.warning("Could not refresh fatal_union: %s", exc)

    # ── Summary ──────────────────────────────────────────────────────────────
    total_elapsed = round(time.monotonic() - t_start, 1)
    ok = [r for r in all_results if r.get("status") == "success"]
    failed = [r for r in all_results if r.get("status") == "failed"]
    total_rows = sum(r.get("rows_loaded", 0) for r in ok)

    logger.info(
        "\n=== ETL COMPLETE ===\n"
        "  Layers OK:    %d\n"
        "  Layers failed: %d\n"
        "  Total rows:   %d\n"
        "  Total time:   %.1fs",
        len(ok), len(failed), total_rows, total_elapsed,
    )
    for r in failed:
        logger.error("  FAILED: %s — %s", r["layer_name"], r.get("error", "unknown"))

    if args.report:
        Path(args.report).write_text(json.dumps(all_results, indent=2, default=str))
        logger.info("Report written to %s", args.report)

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()


# ════════════════════════════════════════════════════════════════════════════
# refresh_layers.py  (separate entry point in same file for brevity)
# ════════════════════════════════════════════════════════════════════════════
# To use: python -m etl_pipeline.scripts.refresh_layers --layer wetlands
#
# This script provides idempotent per-layer refresh with version history.
#
# Usage examples:
#   python -m etl_pipeline.scripts.refresh_layers --layer wetlands
#   python -m etl_pipeline.scripts.refresh_layers --layer wetlands --force
#   python -m etl_pipeline.scripts.refresh_layers --all
#   python -m etl_pipeline.scripts.refresh_layers --list

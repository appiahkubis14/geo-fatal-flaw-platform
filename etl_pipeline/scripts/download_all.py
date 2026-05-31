#!/usr/bin/env python3
"""
etl_pipeline/scripts/download_all.py
Download all 15 constraint layers from official sources.
Run: python -m etl_pipeline.scripts.download_all [--layers wetlands,floodplains] [--force]
"""

from __future__ import annotations
import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from etl_pipeline.base.etl_base import load_config
from etl_pipeline.scripts.layer_loaders import LOADER_REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("download_all")


def main():
    parser = argparse.ArgumentParser(description="Download Fatal Flaw constraint layers")
    parser.add_argument("--layers", help="Comma-separated layer names (default: all)")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    parser.add_argument("--config", help="Path to config.yaml", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    db_url = os.environ["DATABASE_URL"]

    target_layers = (
        [l.strip() for l in args.layers.split(",")]
        if args.layers
        else list(LOADER_REGISTRY.keys())
    )

    logger.info("Downloading %d layers: %s", len(target_layers), target_layers)
    results = {}
    for layer_name in target_layers:
        if layer_name not in LOADER_REGISTRY:
            logger.warning("Unknown layer '%s' — skipping", layer_name)
            continue
        if not config["layers"].get(layer_name, {}).get("enabled", True):
            logger.info("Layer '%s' disabled in config — skipping", layer_name)
            continue

        loader_cls = LOADER_REGISTRY[layer_name]
        loader = loader_cls(config, db_url)
        dest_dir = loader.data_dir

        try:
            logger.info("=== Downloading: %s ===", layer_name)
            t0 = time.monotonic()
            raw_path = loader.download(dest_dir)
            elapsed = time.monotonic() - t0
            logger.info("✓ %s downloaded in %.1fs → %s", layer_name, elapsed, raw_path)
            results[layer_name] = {"status": "ok", "path": str(raw_path)}
        except Exception as exc:
            logger.error("✗ %s download failed: %s", layer_name, exc)
            results[layer_name] = {"status": "failed", "error": str(exc)}

    ok = sum(1 for r in results.values() if r["status"] == "ok")
    failed = len(results) - ok
    logger.info("Download complete: %d OK, %d failed", ok, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

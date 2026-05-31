#!/usr/bin/env python3
"""
etl_pipeline/scripts/refresh_layers.py
Idempotent per-layer refresh with version history in audit.etl_log.
Run: python -m etl_pipeline.scripts.refresh_layers --layer wetlands [--force]
     python -m etl_pipeline.scripts.refresh_layers --all [--force]
     python -m etl_pipeline.scripts.refresh_layers --list
"""

from __future__ import annotations
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from etl_pipeline.base.etl_base import load_config
from etl_pipeline.scripts.layer_loaders import LOADER_REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("refresh_layers")


def list_layers(config: dict) -> None:
    """Print status of all layers from the database."""
    from sqlalchemy import create_engine, text
    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            """
            SELECT layer_name,
                   MAX(finished_at) AS last_run,
                   MAX(CASE WHEN status='success' THEN rows_loaded ELSE 0 END) AS rows,
                   MAX(status) AS last_status
            FROM audit.etl_log
            GROUP BY layer_name
            ORDER BY layer_name
            """
        )).fetchall()

    print(f"\n{'Layer':<30} {'Last Run':<25} {'Rows':>10} {'Status':<12}")
    print("─" * 80)
    for row in rows:
        print(f"{row.layer_name:<30} {str(row.last_run):<25} {row.rows:>10} {row.last_status:<12}")

    # Show layers never loaded
    loaded = {r.layer_name for r in rows}
    never = set(LOADER_REGISTRY.keys()) - loaded
    if never:
        for ln in sorted(never):
            print(f"{ln:<30} {'NEVER':25} {'':>10} {'not_loaded':<12}")


def refresh_layer(layer_name: str, config: dict, db_url: str, force: bool) -> dict:
    """Run ETL for a single layer."""
    if layer_name not in LOADER_REGISTRY:
        raise KeyError(f"Unknown layer: '{layer_name}'")

    loader_cls = LOADER_REGISTRY[layer_name]
    loader = loader_cls(config, db_url)

    if not force:
        # Check if already up-to-date (last successful run within 7 days by default)
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(text(
                """
                SELECT finished_at, rows_loaded
                FROM audit.etl_log
                WHERE layer_name = :layer AND status = 'success'
                ORDER BY finished_at DESC LIMIT 1
                """
            ), {"layer": layer_name}).fetchone()

        if result:
            from datetime import datetime, timezone, timedelta
            last_run = result.finished_at
            age = datetime.now(timezone.utc) - last_run.replace(tzinfo=timezone.utc)
            if age < timedelta(days=7):
                logger.info(
                    "[%s] Last successful run was %s ago (%d rows). "
                    "Use --force to reload.",
                    layer_name, str(age).split(".")[0], result.rows_loaded,
                )
                return {"layer_name": layer_name, "status": "skipped", "rows_loaded": result.rows_loaded}

    return loader.run(force=force)


def main():
    parser = argparse.ArgumentParser(description="Refresh individual constraint layers")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--layer", help="Single layer name to refresh")
    group.add_argument("--all", action="store_true", help="Refresh all layers")
    group.add_argument("--list", action="store_true", help="List layer ETL status")
    parser.add_argument("--force", action="store_true", help="Force reload even if recently run")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    db_url = os.environ["DATABASE_URL"]

    if args.list:
        list_layers(config)
        return

    if args.layer:
        try:
            result = refresh_layer(args.layer, config, db_url, args.force)
            if result["status"] == "success":
                logger.info("✓ %s: %d rows loaded", args.layer, result.get("rows_loaded", 0))
            elif result["status"] == "skipped":
                logger.info("— %s: skipped (already up-to-date)", args.layer)
            else:
                logger.error("✗ %s: %s", args.layer, result.get("error", "failed"))
                sys.exit(1)
        except Exception as exc:
            logger.exception("Failed: %s", exc)
            sys.exit(1)

    elif args.all:
        failed = []
        for layer_name in LOADER_REGISTRY:
            try:
                result = refresh_layer(layer_name, config, db_url, args.force)
                logger.info(
                    "[%s] %s — %d rows",
                    layer_name, result["status"], result.get("rows_loaded", 0),
                )
                if result["status"] == "failed":
                    failed.append(layer_name)
            except Exception as exc:
                logger.error("[%s] Exception: %s", layer_name, exc)
                failed.append(layer_name)

        if failed:
            logger.error("Failed layers: %s", failed)
            sys.exit(1)


if __name__ == "__main__":
    main()

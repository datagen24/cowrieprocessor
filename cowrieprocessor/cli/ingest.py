"""Command line interface for bulk and delta loaders with telemetry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Sequence

from ..db import apply_migrations, create_engine_from_settings
from ..loader import (
    BulkLoader,
    BulkLoaderConfig,
    DeltaLoader,
    DeltaLoaderConfig,
    StatusEmitter,
)
from ..settings import DatabaseSettings, load_database_settings


def _resolve_db_settings(db_arg: str | None) -> DatabaseSettings:
    if not db_arg:
        return load_database_settings()
    if db_arg.startswith("sqlite:"):
        return load_database_settings(config={"url": db_arg})
    db_path = Path(db_arg)
    if db_path.exists() or db_arg.endswith(".sqlite"):
        return DatabaseSettings(url=f"sqlite:///{db_path.resolve()}")
    return load_database_settings(config={"url": db_arg})


def _make_bulk_config(args: argparse.Namespace) -> BulkLoaderConfig:
    config = BulkLoaderConfig(
        batch_size=args.batch_size,
        quarantine_threshold=args.quarantine_threshold,
    )
    return config


def _make_delta_config(args: argparse.Namespace) -> DeltaLoaderConfig:
    bulk_cfg = _make_bulk_config(args)
    return DeltaLoaderConfig(bulk=bulk_cfg)


def run_bulk_loader(args: argparse.Namespace, sources: Sequence[str | Path]) -> int:
    """Execute the bulk loader and emit status telemetry."""
    settings = _resolve_db_settings(args.db)
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)

    emitter = StatusEmitter("bulk_ingest", status_dir=args.status_dir)
    loader = BulkLoader(engine, _make_bulk_config(args))
    metrics = loader.load_paths(
        sources,
        ingest_id=args.ingest_id,
        telemetry_cb=emitter.record_metrics,
        checkpoint_cb=emitter.record_checkpoint,
    )
    print(
        f"Bulk ingest complete: files={metrics.files_processed} events={metrics.events_inserted}/{metrics.events_read}"
    )
    return 0


def run_delta_loader(args: argparse.Namespace, sources: Sequence[str | Path]) -> int:
    """Execute the delta loader and emit status telemetry, including DLQ updates."""
    settings = _resolve_db_settings(args.db)
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)

    emitter = StatusEmitter("delta_ingest", status_dir=args.status_dir)
    loader = DeltaLoader(engine, _make_delta_config(args))
    metrics = loader.load_paths(
        sources,
        ingest_id=args.ingest_id,
        telemetry_cb=emitter.record_metrics,
        checkpoint_cb=emitter.record_checkpoint,
        dead_letter_cb=emitter.record_dead_letters,
    )
    print(
        f"Delta ingest complete: files={metrics.files_processed} "
        f"events={metrics.events_inserted}/{metrics.events_read} dlq={metrics.events_quarantined}"
    )
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entry point for running bulk or delta ingestion."""
    parser = argparse.ArgumentParser(description="Load Cowrie logs into the database")
    parser.add_argument(
        "mode",
        choices=("bulk", "delta"),
        help="Loader mode to execute",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="Paths to Cowrie JSON logs to ingest",
    )
    parser.add_argument("--db", help="Database URL or SQLite path")
    parser.add_argument("--status-dir", help="Directory for status JSON", default=None)
    parser.add_argument("--ingest-id", help="Explicit ingest identifier")
    parser.add_argument("--batch-size", type=int, default=BulkLoaderConfig().batch_size)
    parser.add_argument(
        "--quarantine-threshold",
        type=int,
        default=BulkLoaderConfig().quarantine_threshold,
        help="Risk score above which events are quarantined",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)
    sources: Sequence[str | Path] = [Path(src) for src in args.sources]

    if args.mode == "bulk":
        return run_bulk_loader(args, sources)
    return run_delta_loader(args, sources)


if __name__ == "__main__":
    sys.exit(main())

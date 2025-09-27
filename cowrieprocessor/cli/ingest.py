"""Command line interface for bulk and delta loaders with telemetry."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Sequence

try:
    from enrichment_handlers import EnrichmentService
except ModuleNotFoundError:  # pragma: no cover - package execution path
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))
    from enrichment_handlers import EnrichmentService

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
        multiline_json=args.multiline_json,
    )
    return config


def _make_delta_config(args: argparse.Namespace) -> DeltaLoaderConfig:
    bulk_cfg = _make_bulk_config(args)
    return DeltaLoaderConfig(bulk=bulk_cfg)


def _resolve_enrichment_service(args: argparse.Namespace) -> EnrichmentService | None:
    if getattr(args, "skip_enrich", False):
        return None

    vt_api = getattr(args, "vt_api_key", None) or os.getenv("VT_API_KEY")
    dshield_email = getattr(args, "dshield_email", None) or os.getenv("DSHIELD_EMAIL")
    urlhaus_api = getattr(args, "urlhaus_api_key", None) or os.getenv("URLHAUS_API_KEY")
    spur_api = getattr(args, "spur_api_key", None) or os.getenv("SPUR_API_KEY")

    if not any([vt_api, dshield_email, urlhaus_api, spur_api]):
        return None

    cache_dir_value = getattr(args, "cache_dir", None) or os.getenv("COWRIEPROC_CACHE_DIR")
    cache_dir = (
        Path(cache_dir_value).expanduser()
        if cache_dir_value
        else Path.home() / ".cache" / "cowrieprocessor" / "enrichment"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    return EnrichmentService(
        cache_dir,
        vt_api=vt_api,
        dshield_email=dshield_email,
        urlhaus_api=urlhaus_api,
        spur_api=spur_api,
    )


def run_bulk_loader(args: argparse.Namespace, sources: Sequence[str | Path]) -> int:
    """Execute the bulk loader and emit status telemetry."""
    settings = _resolve_db_settings(args.db)
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)

    emitter = StatusEmitter("bulk_ingest", status_dir=args.status_dir)
    enrichment = _resolve_enrichment_service(args)
    loader = BulkLoader(engine, _make_bulk_config(args), enrichment_service=enrichment)
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
    enrichment = _resolve_enrichment_service(args)
    loader = DeltaLoader(engine, _make_delta_config(args), enrichment_service=enrichment)
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
    parser.add_argument(
        "--multiline-json",
        action="store_true",
        help="Enable multiline JSON parsing for pretty-printed Cowrie logs",
    )
    parser.add_argument("--skip-enrich", action="store_true", help="Disable external enrichment lookups")
    parser.add_argument("--cache-dir", type=Path, help="Directory for enrichment cache files")
    parser.add_argument("--vt-api-key", help="VirusTotal API key for file hash enrichment")
    parser.add_argument("--dshield-email", help="Email registered with DShield for IP enrichment")
    parser.add_argument("--urlhaus-api-key", help="URLHaus API token for URL/IP lookups")
    parser.add_argument("--spur-api-key", help="SPUR API token for infrastructure lookups")

    args = parser.parse_args(list(argv) if argv is not None else None)
    sources: Sequence[str | Path] = [Path(src) for src in args.sources]

    if args.mode == "bulk":
        return run_bulk_loader(args, sources)
    return run_delta_loader(args, sources)


if __name__ == "__main__":
    sys.exit(main())

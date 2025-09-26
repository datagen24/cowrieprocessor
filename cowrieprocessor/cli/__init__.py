"""Command-line entry points for Cowrie processor loaders."""

from .ingest import main as ingest_main

__all__ = ["ingest_main"]

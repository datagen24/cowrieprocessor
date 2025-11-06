"""CLI for building and maintaining ASN inventory from IP enrichment data."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from tqdm import tqdm

from cowrieprocessor.db import apply_migrations, create_session_maker
from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.models import ASNInventory, IPInventory
from cowrieprocessor.settings import DatabaseSettings

from .db_config import add_database_argument, resolve_database_settings

logger = logging.getLogger(__name__)


def build_asn_inventory(
    db_settings: DatabaseSettings,
    batch_size: int = 1000,
    progress: bool = True,
    verbose: bool = False,
) -> int:
    """Build and update ASN inventory from existing IP inventory data.

    This function extracts unique ASNs from the ip_inventory table and processes
    them idempotently: creates new ASN records and updates existing ones with
    current IP counts and metadata. Safe to run repeatedly (e.g., via cron).

    For each ASN:
    - Creates new record with organization metadata and IP count (if new)
    - Updates unique_ip_count, first_seen, last_seen (if existing)
    - Backfills missing metadata fields (organization, country, RIR)

    Metadata is extracted from IP enrichment JSON (MaxMind or Cymru).

    Args:
        db_settings: Database settings object (from sensors.toml or CLI args)
        batch_size: Number of records to process per batch
        progress: Show progress bar
        verbose: Enable detailed logging

    Returns:
        Total number of ASN records processed (created + updated)

    Example:
        >>> from cowrieprocessor.settings import load_database_settings
        >>> db_settings = load_database_settings()
        >>> count = build_asn_inventory(
        ...     db_settings=db_settings,
        ...     batch_size=1000,
        ...     progress=True,
        ... )
        >>> print(f"Processed {count} ASN records")
        Processed 5432 ASN records (120 created, 5312 updated)
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        # Connect to database
        engine = create_engine_from_settings(db_settings)
        session_maker = create_session_maker(engine)

        # Apply migrations if needed
        logger.info("Checking database schema...")
        apply_migrations(engine)

        with session_maker() as session:
            # Step 1: Get unique ASNs from ip_inventory
            logger.info("Extracting unique ASNs from IP inventory...")

            # Query unique ASNs with counts
            unique_asns = (
                session.query(
                    IPInventory.current_asn,
                    func.count(IPInventory.ip_address).label("ip_count"),
                    func.min(IPInventory.first_seen).label("earliest_seen"),
                    func.max(IPInventory.last_seen).label("latest_seen"),
                )
                .filter(IPInventory.current_asn.is_not(None))
                .group_by(IPInventory.current_asn)
                .all()
            )

            total_asns = len(unique_asns)
            logger.info(f"Found {total_asns} unique ASNs in IP inventory")

            if total_asns == 0:
                logger.warning("No ASNs found in IP inventory. Run IP enrichment first.")
                return 0

            # Step 2: Get existing ASN records for update logic
            existing_asn_map = {
                record.asn_number: record
                for record in session.query(ASNInventory)
                .filter(ASNInventory.asn_number.in_([asn for asn, _, _, _ in unique_asns]))
                .all()
            }

            new_count = len([asn for asn, _, _, _ in unique_asns if asn not in existing_asn_map])
            existing_count = len(existing_asn_map)
            logger.info(
                f"Found {len(unique_asns)} total ASNs: {new_count} new, {existing_count} existing (will update)"
            )

            # Step 3: Process all ASNs (create new + update existing)
            created_count = 0
            updated_count = 0
            skipped_count = 0
            now = datetime.now(timezone.utc)

            # Use tqdm for progress if enabled
            asn_iterator = tqdm(unique_asns, desc="Processing ASN inventory", disable=not progress)

            for asn, ip_count, earliest_seen, latest_seen in asn_iterator:
                try:
                    # Get a sample IP from this ASN to extract metadata
                    sample_ip = session.query(IPInventory).filter(IPInventory.current_asn == asn).first()

                    if not sample_ip:
                        logger.warning(f"No sample IP found for ASN {asn}, skipping")
                        skipped_count += 1
                        continue

                    # Extract metadata from enrichment JSON with defensive parsing
                    enrichment: Any = sample_ip.enrichment
                    organization_name: str | None = None
                    organization_country: str | None = None
                    rir_registry: str | None = None

                    # Validate enrichment is dict-like before processing
                    if not isinstance(enrichment, dict):
                        logger.warning(
                            f"ASN {asn}: enrichment data is not a dict (type: {type(enrichment).__name__}), "
                            f"creating record without metadata"
                        )
                        enrichment = {}

                    try:
                        # Try MaxMind first with defensive type checking
                        if "maxmind" in enrichment:
                            maxmind_data = enrichment["maxmind"]
                            if isinstance(maxmind_data, dict):
                                asn_org = maxmind_data.get("asn_org")
                                if asn_org is not None and not isinstance(asn_org, str):
                                    logger.debug(
                                        f"ASN {asn}: maxmind.asn_org has unexpected type "
                                        f"{type(asn_org).__name__}, converting to string"
                                    )
                                    asn_org = str(asn_org)
                                organization_name = asn_org if asn_org else None

                                country = maxmind_data.get("country")
                                if country is not None and not isinstance(country, str):
                                    logger.debug(
                                        f"ASN {asn}: maxmind.country has unexpected type "
                                        f"{type(country).__name__}, converting to string"
                                    )
                                    country = str(country)
                                organization_country = country if country else None
                            else:
                                logger.debug(
                                    f"ASN {asn}: maxmind data is not a dict (type: {type(maxmind_data).__name__})"
                                )

                        # Fall back to Cymru if MaxMind didn't have it
                        if "cymru" in enrichment and not organization_name:
                            cymru_data = enrichment["cymru"]
                            if isinstance(cymru_data, dict):
                                asn_org = cymru_data.get("asn_org")
                                if asn_org is not None and not isinstance(asn_org, str):
                                    logger.debug(
                                        f"ASN {asn}: cymru.asn_org has unexpected type "
                                        f"{type(asn_org).__name__}, converting to string"
                                    )
                                    asn_org = str(asn_org)
                                organization_name = asn_org if asn_org else None

                                country = cymru_data.get("country")
                                if country is not None and not isinstance(country, str):
                                    logger.debug(
                                        f"ASN {asn}: cymru.country has unexpected type "
                                        f"{type(country).__name__}, converting to string"
                                    )
                                    country = str(country)
                                organization_country = country if country else None

                                registry = cymru_data.get("registry")
                                if registry is not None and not isinstance(registry, str):
                                    logger.debug(
                                        f"ASN {asn}: cymru.registry has unexpected type "
                                        f"{type(registry).__name__}, converting to string"
                                    )
                                    registry = str(registry)
                                rir_registry = registry if registry else None
                            else:
                                logger.debug(f"ASN {asn}: cymru data is not a dict (type: {type(cymru_data).__name__})")

                    except (KeyError, TypeError, AttributeError) as parse_error:
                        logger.warning(
                            f"ASN {asn}: failed to parse enrichment metadata: {parse_error}, "
                            f"creating record without metadata"
                        )
                        # Reset to None to ensure record creation with empty metadata
                        organization_name = None
                        organization_country = None
                        rir_registry = None

                    # Check if ASN exists - update or create
                    if asn in existing_asn_map:
                        # Update existing record with current counts and metadata
                        asn_record = existing_asn_map[asn]
                        asn_record.unique_ip_count = ip_count

                        # Update first_seen to earliest timestamp
                        new_first_seen = earliest_seen or now
                        if new_first_seen < asn_record.first_seen:
                            asn_record.first_seen = new_first_seen  # type: ignore[assignment]

                        # Update last_seen to latest timestamp
                        new_last_seen = latest_seen or now
                        if new_last_seen > asn_record.last_seen:
                            asn_record.last_seen = new_last_seen  # type: ignore[assignment]

                        asn_record.updated_at = now  # type: ignore[assignment]

                        # Update metadata if it was missing before
                        if not asn_record.organization_name and organization_name:
                            asn_record.organization_name = organization_name  # type: ignore[assignment]
                        if not asn_record.organization_country and organization_country:
                            asn_record.organization_country = organization_country  # type: ignore[assignment]
                        if not asn_record.rir_registry and rir_registry:
                            asn_record.rir_registry = rir_registry  # type: ignore[assignment]

                        updated_count += 1
                    else:
                        # Create new ASN inventory record
                        asn_record = ASNInventory(
                            asn_number=asn,
                            organization_name=organization_name,
                            organization_country=organization_country,
                            rir_registry=rir_registry,
                            first_seen=earliest_seen or now,
                            last_seen=latest_seen or now,
                            unique_ip_count=ip_count,
                            total_session_count=0,  # Will be calculated separately if needed
                            enrichment={},
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(asn_record)
                        created_count += 1

                    # Commit in batches
                    if (created_count + updated_count) % batch_size == 0:
                        session.commit()
                        logger.debug(f"Committed batch of {batch_size} ASN records")

                except Exception as e:
                    logger.error(f"Error processing ASN {asn}: {e}")
                    skipped_count += 1
                    continue

            # Final commit
            session.commit()

            # Summary reporting
            total_processed = created_count + updated_count
            if skipped_count > 0:
                logger.info(
                    f"Successfully processed {total_processed} ASN records: "
                    f"{created_count} created, {updated_count} updated "
                    f"({skipped_count} skipped due to errors)"
                )
            else:
                logger.info(
                    f"Successfully processed {total_processed} ASN records: "
                    f"{created_count} created, {updated_count} updated"
                )

            return total_processed

    except Exception as e:
        logger.error(f"Failed to build ASN inventory: {e}")
        raise


def main() -> None:
    """CLI entry point for building and updating ASN inventory."""
    parser = argparse.ArgumentParser(
        description="Build and update ASN inventory from IP enrichment data (idempotent, cron-safe)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process ASN inventory (creates new + updates existing, uses sensors.toml)
  cowrie-enrich-asn --progress --verbose

  # With explicit database URL
  cowrie-enrich-asn --db-url postgresql://user:pass@host/db --progress

  # With custom batch size for large databases
  cowrie-enrich-asn --db-url sqlite:////path/to/db.sqlite --batch-size 500 --progress

  # Safe for cron jobs (idempotent, updates counts from current IP inventory)
  0 */6 * * * /usr/local/bin/cowrie-enrich-asn --progress
        """,
    )

    # Add standard database argument (--db-url, with sensors.toml fallback)
    add_database_argument(
        parser,
        help_text="Database connection URL. If not provided, reads from sensors.toml config file.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of records to process per batch (default: 1000)",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress bar",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    try:
        # Resolve database settings from --db-url or sensors.toml
        db_settings = resolve_database_settings(args.db_url)

        # Build/update ASN inventory
        processed = build_asn_inventory(
            db_settings=db_settings,
            batch_size=args.batch_size,
            progress=args.progress,
            verbose=args.verbose,
        )

        print(f"\n✅ Successfully processed {processed} ASN inventory records")
        sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

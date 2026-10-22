"""
main.py — CLI entry point for TechPulse AI Digest Bot.
Executes the autonomous multi-agent digest pipeline with command-line flags,
robust logging, and Windows-safe encoding.
"""

import sys
import io
import argparse
import logging
from typing import Optional

# Ensure standard output and error handles UTF-8 on Windows environments
if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from src.orchestrator import DigestOrchestrator
from src.storage.database import DigestDatabase
from config.settings import settings


def setup_logging(verbose: bool = False) -> None:
    """Configure structured console logging."""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(log_format, date_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Remove existing handlers to avoid duplicates
    root_logger.handlers = [handler]


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="TechPulse AI Digest Bot — Multi-Source Technical Intelligence Agent",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Harvest and curate items without writing to disk or database",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Display SQLite historical database metrics and exit",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override digest date (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    return parser.parse_args()


def main() -> int:
    """Main execution function."""
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("main")

    # If --stats requested, query DB and exit
    if args.stats:
        db = DigestDatabase(settings.DB_PATH)
        stats = db.get_stats()
        print("\n" + "=" * 50)
        print("TechPulse Database Metrics:")
        print(f"  Total Tracked URLs:         {stats.get('total_seen_urls', 0)}")
        print(f"  Historical Digests:         {stats.get('total_digests_generated', 0)}")
        print(f"  All-time Must Read Items:   {stats.get('total_must_reads', 0)}")
        print("=" * 50 + "\n")
        return 0

    try:
        orchestrator = DigestOrchestrator()
        result = orchestrator.run(dry_run=args.dry_run, custom_date=args.date)
        return 0 if result["success"] else 1
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
        return 1
    except Exception as e:
        logger.error(f"Fatal execution failure: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

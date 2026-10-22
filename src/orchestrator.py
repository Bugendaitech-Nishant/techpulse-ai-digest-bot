"""
orchestrator.py — High-level pipeline runner for TechPulse AI Digest Bot.
Wires together HarvesterAgent, ProcessorAgent, PublisherAgent, and DigestDatabase.
"""

import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from src.models import TechDigest
from src.storage.database import DigestDatabase
from src.agents.harvester import HarvesterAgent
from src.agents.processor import ProcessorAgent
from src.agents.publisher import PublisherAgent
from config.settings import settings

logger = logging.getLogger(__name__)


class DigestOrchestrator:
    """Coordinates end-to-end multi-agent execution pipeline."""

    def __init__(
        self,
        db: Optional[DigestDatabase] = None,
        harvester: Optional[HarvesterAgent] = None,
        processor: Optional[ProcessorAgent] = None,
        publisher: Optional[PublisherAgent] = None,
    ):
        self.db = db or DigestDatabase(settings.DB_PATH)
        self.harvester = harvester or HarvesterAgent(db=self.db)
        self.processor = processor or ProcessorAgent()
        self.publisher = publisher or PublisherAgent()

    def run(self, dry_run: bool = False, custom_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute full pipeline:
        1. Harvest from all 6 sources + 30-day deduplication
        2. Filter and summarize with Groq LLM
        3. Format and export Markdown report + persist to database
        """
        pipeline_start = time.perf_counter()
        today = custom_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger.info(f"--- Starting TechPulse Pipeline execution for {today} ---")

        # ── Step 1: Harvester Agent ──
        raw_items, harvest_stats = self.harvester.harvest()

        if not raw_items:
            logger.warning("No novel items discovered. Generating empty/placeholder digest.")
            digest = TechDigest(date=today, items=[], total_harvested=0, total_curated=0)
        else:
            # ── Step 2: Processor Agent ──
            digest = self.processor.process(raw_items, target_date=today)
            digest.total_harvested = harvest_stats.get("total_harvested_raw", len(raw_items))
            digest.total_deduplicated = harvest_stats.get("historical_duplicates_filtered", 0)

        # ── Step 3: Publisher Agent ──
        output_path: Optional[Path] = None
        if not dry_run:
            output_path = self.publisher.publish(digest)
            # Record finalized digest into database
            self.db.record_digest(digest)
            logger.info("Persisted digest records to SQLite database.")
        else:
            logger.info("DRY RUN: Skipping file write and database commit.")

        elapsed = round(time.perf_counter() - pipeline_start, 2)
        logger.info(f"--- Pipeline completed in {elapsed}s ---")

        return {
            "success": True,
            "date": today,
            "duration_seconds": elapsed,
            "total_harvested": digest.total_harvested,
            "must_reads": len(digest.must_reads),
            "inspirations": len(digest.inspirations),
            "skipped": len(digest.skips),
            "output_file": str(output_path) if output_path else None,
            "harvest_stats": harvest_stats,
        }

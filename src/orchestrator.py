"""
orchestrator.py — High-level pipeline runner for TechPulse AI Digest Bot.
Wires together HarvesterAgent, ProcessorAgent, PublisherAgent, and DigestDatabase.
"""

import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from src.models import DigestItem, TechDigest
from src import runlog
from src.storage.database import DigestDatabase
from src.agents.harvester import HarvesterAgent
from src.agents.processor import ProcessorAgent
from src.agents.publisher import PublisherAgent
from src.agents.critic import review_digest
from src.stories import find_story_groups, story_id_for
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
        self.processor = processor or ProcessorAgent(
            feedback_provider=lambda: self.db.get_feedback_examples(settings.FEEDBACK_EXAMPLES)
        )
        self.publisher = publisher or PublisherAgent()

    @staticmethod
    def merge_same_day(existing: Dict[str, Any], new: TechDigest) -> TechDigest:
        """Combine an already-stored digest for the same date with a fresh run; the fresh item wins on a URL clash."""
        fresh_urls = {item.url for item in new.items}
        kept = [DigestItem(**i) for i in existing.get("items", []) if i["url"] not in fresh_urls]
        weight = {"Must Read": 0, "Inspiration": 1, "Skip": 2}
        items = sorted(kept + list(new.items), key=lambda i: (weight[i.category], -i.priority_score))
        items = [i.model_copy(update={"rank": n}) for n, i in enumerate(items, 1)]
        return new.model_copy(update={
            "items": items,
            "total_harvested": existing.get("total_harvested", 0) + new.total_harvested,
            "total_curated": len([i for i in items if i.category != "Skip"]),
        })

    def assign_stories(self, digest: TechDigest) -> TechDigest:
        """Give items that report the same event one story id, across the last week. Best effort."""
        if not self.processor.client or not digest.items:
            return digest
        kept = [i for i in digest.items if i.category != "Skip"]
        groups = find_story_groups(kept, self.db.get_recent_items(digest.date), self.processor.ask_json)
        mapping = {url: story_id_for(urls) for urls in groups for url in urls}
        if not mapping:
            return digest
        logger.info(f"Stories: {len(groups)} stories span {len(mapping)} items")
        self.db.set_story_ids(mapping)
        self.publisher.patch_story_ids(mapping)
        items = [i.model_copy(update={"story_id": mapping.get(i.url, i.story_id)}) for i in digest.items]
        return digest.model_copy(update={"items": items})

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

        # A second run on the same date must add to that day's digest, not replace it.
        if not dry_run:
            existing = self.db.get_digest_by_date(today)
            if existing:
                digest = self.merge_same_day(existing, digest)

        if not dry_run:
            digest = self.assign_stories(digest)
            if self.processor.client:
                digest = review_digest(digest, self.processor.ask_json)

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

        breakdown = harvest_stats.get("collector_breakdown", {})
        failed_sources = [name for name, info in breakdown.items() if not info.get("success", True)]
        if failed_sources:
            logger.warning(f"Sources that failed this run: {', '.join(sorted(failed_sources))}")
        if not dry_run:
            runlog.append_run(runlog.make_record(
                date=today,
                duration_seconds=elapsed,
                harvested=digest.total_harvested,
                novel=harvest_stats.get("novel_items_for_curation", 0),
                kept=len([i for i in digest.items if i.category != "Skip"]),
                unreviewed=len([i for i in digest.items if i.why_it_matters.startswith("Not reviewed")]),
                security=len([i for i in digest.items if i.source == "security_advisories"]),
                failed_sources=failed_sources,
            ))

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
            "failed_sources": failed_sources,
        }

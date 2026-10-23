"""
harvester.py — Agent 1: The Multi-Source Data Harvester
Coordinates concurrent data collection across all configured sources,
enforces deduplication, tracks collection metrics, and persists items to SQLite.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Any

from src.models import RawItem, CollectorResult
from src.collectors import (
    BaseCollector,
    GitHubTrendingCollector,
    GitHubSearchCollector,
    HackerNewsCollector,
    HuggingFacePapersCollector,
    DevToCollector,
    ArXivCollector,
    SecurityAdvisoryCollector,
)
from src.storage.database import DigestDatabase
from config.settings import settings

logger = logging.getLogger(__name__)


class HarvesterAgent:
    """Agent responsible for parallel ingestion and deduplication across all sources."""

    def __init__(self, db: DigestDatabase, collectors: List[BaseCollector] = None):
        self.db = db
        self.collectors = collectors or [
            GitHubTrendingCollector(),
            GitHubSearchCollector(),
            HackerNewsCollector(),
            HuggingFacePapersCollector(),
            DevToCollector(),
            ArXivCollector(),
            SecurityAdvisoryCollector(),
        ]

    def harvest(self) -> Tuple[List[RawItem], Dict[str, Any]]:
        """
        Execute all collectors concurrently.
        Performs in-memory URL deduplication followed by 30-day database window deduplication.
        Returns:
            Tuple of (unseen_raw_items, harvest_telemetry)
        """
        logger.info(f"Agent 1 (Harvester): Initiating collection from {len(self.collectors)} sources in parallel")

        results: List[CollectorResult] = []
        raw_items: List[RawItem] = []

        # Execute all collectors concurrently with thread pool
        with ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_COLLECTORS) as executor:
            future_to_collector = {
                executor.submit(collector.fetch): collector.name
                for collector in self.collectors
            }
            for future in as_completed(future_to_collector):
                name = future_to_collector[future]
                try:
                    res = future.result()
                    results.append(res)
                    if res.success:
                        raw_items.extend(res.items)
                except Exception as e:
                    logger.error(f"Collector [{name}] raised fatal exception: {e}")
                    results.append(CollectorResult(collector_name=name, success=False, error=str(e)))

        total_collected = len(raw_items)

        # 1. In-memory deduplication for current batch
        seen_batch_urls = set()
        deduped_batch: List[RawItem] = []
        for item in raw_items:
            h = self.db.hash_url(item.url)
            if h not in seen_batch_urls:
                seen_batch_urls.add(h)
                deduped_batch.append(item)

        # 2. Database 30-day sliding window deduplication
        unseen_items, db_filtered_count = self.db.filter_unseen(
            deduped_batch, window_days=settings.DEDUP_WINDOW_DAYS
        )

        # 3. Mark newly discovered items as seen in database
        if unseen_items:
            self.db.mark_items_seen(unseen_items)

        telemetry = {
            "total_harvested_raw": total_collected,
            "unique_in_batch": len(deduped_batch),
            "historical_duplicates_filtered": db_filtered_count,
            "novel_items_for_curation": len(unseen_items),
            "collector_breakdown": {
                r.collector_name: {"count": len(r.items), "duration_s": r.duration_seconds, "success": r.success}
                for r in results
            },
        }

        logger.info(
            f"Agent 1 (Harvester): Finished. {total_collected} fetched -> {len(unseen_items)} novel items selected"
        )
        return unseen_items, telemetry

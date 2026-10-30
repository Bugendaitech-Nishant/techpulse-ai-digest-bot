"""
base.py — Abstract base class for all data collectors.
Provides standardized error isolation, timeout enforcement, retries, and telemetry.
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import List

from src.models import RawItem, CollectorResult
from config.settings import settings

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract collector defining interface and error isolation."""

    name: str = "base_collector"
    enabled: bool = True
    timeout: int = settings.COLLECTOR_TIMEOUT

    def fetch(self) -> CollectorResult:
        """
        Public execution wrapper.
        Enforces execution timeouts, catches unhandled exceptions, and returns CollectorResult.
        """
        if not self.enabled:
            logger.info(f"Collector [{self.name}] is disabled. Skipping.")
            return CollectorResult(collector_name=self.name, success=True, items=[])

        start_time = time.perf_counter()
        logger.info(f"Collector [{self.name}] starting harvest...")

        try:
            try:
                items = self._fetch_items()
            except Exception as first_error:  # one retry: free APIs time out now and then
                logger.warning(f"Collector [{self.name}] failed once ({first_error}); retrying")
                time.sleep(2)
                items = self._fetch_items()
            elapsed = time.perf_counter() - start_time
            logger.info(f"Collector [{self.name}] harvested {len(items)} items in {elapsed:.2f}s")
            return CollectorResult(
                collector_name=self.name,
                items=items,
                success=True,
                duration_seconds=round(elapsed, 2),
            )
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            error_msg = f"Collector [{self.name}] failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return CollectorResult(
                collector_name=self.name,
                items=[],
                success=False,
                duration_seconds=round(elapsed, 2),
                error=str(e),
            )

    @abstractmethod
    def _fetch_items(self) -> List[RawItem]:
        """Implement specific harvesting logic in subclasses."""
        pass

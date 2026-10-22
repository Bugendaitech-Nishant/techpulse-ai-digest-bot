"""
quota_manager.py — Production concurrency, cooldown, and hourly cap governor.
Guarantees:
1. No concurrent harvest jobs run at the same time (409 Conflict).
2. Minimum mandatory cooldown between harvests (429 Too Many Requests).
3. Sliding-window hourly budget cap to protect Groq LLM & scraper rate limits (429).
4. Optional API key authentication for harvest triggering.
"""

import time
import threading
import logging
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional, List
from collections import deque

from config.settings import settings

logger = logging.getLogger(__name__)


class QuotaManager:
    """Thread-safe rate-limiting and quota governance manager."""

    def __init__(
        self,
        cooldown_seconds: Optional[int] = None,
        max_harvests_per_hour: Optional[int] = None,
        api_key: Optional[str] = None,
    ):
        self._lock = threading.Lock()
        self.cooldown_seconds = cooldown_seconds if cooldown_seconds is not None else settings.HARVEST_COOLDOWN_SECONDS
        self.max_harvests_per_hour = max_harvests_per_hour if max_harvests_per_hour is not None else settings.MAX_HARVESTS_PER_HOUR
        self.api_key = api_key if api_key is not None else settings.HARVEST_API_KEY

        self._is_running: bool = False
        self._current_run_start: Optional[float] = None
        self._last_completed_timestamp: Optional[float] = None
        self._harvest_timestamps_window: deque = deque()  # timestamps of runs in last 3600s
        self._server_start_time: float = time.time()

    def check_auth(self, provided_key: Optional[str]) -> bool:
        """Verify API key if required by configuration."""
        if not self.api_key:
            return True  # Open if no key is configured
        return provided_key == self.api_key

    def check_harvest_allowed(self, provided_key: Optional[str] = None) -> Tuple[bool, str, int, Dict[str, Any]]:
        """
        Evaluate if a harvest request is permitted right now.
        Returns:
            Tuple of:
            - allowed: bool
            - message: str
            - http_status_code: int (200, 401, 409, 429)
            - metadata: dict with remaining cooldown & quota status
        """
        now = time.time()

        with self._lock:
            # 1. Auth check
            if not self.check_auth(provided_key):
                return False, "Unauthorized: Invalid or missing X-API-Key header.", 401, self._telemetry_snapshot(now)

            # 2. Concurrency check
            if self._is_running:
                elapsed = int(now - (self._current_run_start or now))
                return False, f"Harvest pipeline is currently active (running for {elapsed}s). Please wait for completion.", 409, self._telemetry_snapshot(now)

            # 3. Cooldown check
            if self._last_completed_timestamp is not None:
                elapsed_since_last = now - self._last_completed_timestamp
                if elapsed_since_last < self.cooldown_seconds:
                    remaining = int(self.cooldown_seconds - elapsed_since_last)
                    return False, f"Harvest cooldown in effect. Please wait {remaining} seconds before next run.", 429, self._telemetry_snapshot(now)

            # 4. Hourly cap check (prune timestamps older than 3600 seconds)
            cutoff = now - 3600.0
            while self._harvest_timestamps_window and self._harvest_timestamps_window[0] < cutoff:
                self._harvest_timestamps_window.popleft()

            if len(self._harvest_timestamps_window) >= self.max_harvests_per_hour:
                earliest = self._harvest_timestamps_window[0]
                reset_in = int(3600.0 - (now - earliest)) + 1
                return False, f"Global hourly harvest limit ({self.max_harvests_per_hour}/hour) reached. Quota slot opens in {reset_in} seconds.", 429, self._telemetry_snapshot(now)

            return True, "Ready to harvest.", 200, self._telemetry_snapshot(now)

    def start_harvest(self) -> None:
        """Mark harvest as running and record start time."""
        now = time.time()
        with self._lock:
            self._is_running = True
            self._current_run_start = now

    def finish_harvest(self, success: bool = True) -> None:
        """Mark harvest as finished and register in sliding window."""
        now = time.time()
        with self._lock:
            self._is_running = False
            self._current_run_start = None
            if success:
                self._last_completed_timestamp = now
                self._harvest_timestamps_window.append(now)

    def _telemetry_snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Produce thread-safe snapshot of quota metrics."""
        now = now or time.time()
        cutoff = now - 3600.0
        while self._harvest_timestamps_window and self._harvest_timestamps_window[0] < cutoff:
            self._harvest_timestamps_window.popleft()

        cooldown_remaining = 0
        if self._last_completed_timestamp is not None:
            elapsed = now - self._last_completed_timestamp
            if elapsed < self.cooldown_seconds:
                cooldown_remaining = int(self.cooldown_seconds - elapsed)

        hourly_used = len(self._harvest_timestamps_window)
        hourly_remaining = max(0, self.max_harvests_per_hour - hourly_used)

        return {
            "is_harvesting": self._is_running,
            "cooldown_active": cooldown_remaining > 0,
            "cooldown_remaining_seconds": cooldown_remaining,
            "cooldown_period_seconds": self.cooldown_seconds,
            "hourly_harvests_used": hourly_used,
            "hourly_harvests_max": self.max_harvests_per_hour,
            "hourly_harvests_remaining": hourly_remaining,
            "auth_required": bool(self.api_key),
            "uptime_seconds": round(now - self._server_start_time, 1),
            "last_harvest_at": (
                datetime.fromtimestamp(self._last_completed_timestamp, timezone.utc).isoformat()
                if self._last_completed_timestamp else None
            ),
        }

    def get_status(self) -> Dict[str, Any]:
        """Public telemetry getter."""
        with self._lock:
            return self._telemetry_snapshot()

    def reset_for_testing(self) -> None:
        """Reset internal states for unit/integration testing."""
        with self._lock:
            self._is_running = False
            self._current_run_start = None
            self._last_completed_timestamp = None
            self._harvest_timestamps_window.clear()
            self.api_key = settings.HARVEST_API_KEY
            self.cooldown_seconds = settings.HARVEST_COOLDOWN_SECONDS
            self.max_harvests_per_hour = settings.MAX_HARVESTS_PER_HOUR


quota_manager = QuotaManager()

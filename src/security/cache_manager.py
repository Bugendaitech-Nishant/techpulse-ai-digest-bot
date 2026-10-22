"""
cache_manager.py — In-memory caching layer with TTL and invalidation hooks.
Caches heavy digest queries to protect database I/O and speed up cockpit loads.
"""

import time
import threading
import logging
from typing import Any, Optional, Dict

from config.settings import settings

logger = logging.getLogger(__name__)


class CacheManager:
    """Thread-safe in-memory cache with TTL and harvest invalidation."""

    def __init__(self, default_ttl_seconds: Optional[int] = None):
        self._lock = threading.Lock()
        self.default_ttl = default_ttl_seconds if default_ttl_seconds is not None else settings.CACHE_TTL_SECONDS
        self._store: Dict[str, Dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Fetch item if present and unexpired."""
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None

            if now > entry["expires_at"]:
                # Evict expired entry
                del self._store[key]
                self._misses += 1
                return None

            self._hits += 1
            return entry["data"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store item with expiration."""
        ttl_seconds = ttl if ttl is not None else self.default_ttl
        now = time.time()
        with self._lock:
            self._store[key] = {
                "data": value,
                "expires_at": now + ttl_seconds,
                "cached_at": now,
            }

    def invalidate(self, key_prefix: Optional[str] = None) -> int:
        """Invalidate keys matching prefix or all keys if none provided."""
        with self._lock:
            if key_prefix is None:
                count = len(self._store)
                self._store.clear()
                logger.info(f"Cache cleared: {count} entries evicted.")
                return count

            keys_to_del = [k for k in self._store if k.startswith(key_prefix)]
            for k in keys_to_del:
                del self._store[k]
            logger.info(f"Cache invalidated {len(keys_to_del)} entries matching '{key_prefix}'.")
            return len(keys_to_del)

    def get_stats(self) -> Dict[str, Any]:
        """Return cache health metrics."""
        with self._lock:
            total_lookups = self._hits + self._misses
            hit_ratio = round((self._hits / total_lookups * 100), 1) if total_lookups > 0 else 0.0
            return {
                "active_entries": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio_percent": hit_ratio,
                "default_ttl_seconds": self.default_ttl,
            }

    def reset_for_testing(self) -> None:
        """Clear cache state for tests."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0


cache_manager = CacheManager()

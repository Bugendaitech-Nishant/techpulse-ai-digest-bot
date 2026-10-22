"""
database.py — SQLite persistence and deduplication engine.
Maintains a 30-day sliding deduplication window to ensure recurring items
are not recommended repeatedly across daily digests.
"""

import sqlite3
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from src.models import RawItem, TechDigest, DigestItem

from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DigestDatabase:
    """Manages SQLite persistence for deduplication and historical metrics."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create necessary tables if they don't already exist."""
        with self._connection() as conn:
            cursor = conn.cursor()
            # Table 1: Track seen URLs to prevent duplicate recommendations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_items (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_seen_last_seen ON seen_items(last_seen_at);")

            # Table 2: Historical record of generated digests
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS digests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    total_harvested INTEGER NOT NULL,
                    total_curated INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # Table 3: Individual curated items saved in digests
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS digest_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    digest_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    why_it_matters TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(digest_date) REFERENCES digests(date)
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_digest_items_date ON digest_items(digest_date);")
            conn.commit()

    @staticmethod
    def hash_url(url: str) -> str:
        """Generate a normalized SHA-256 hash for a URL."""
        # Strip trailing slashes and query tracking params
        normalized = url.strip().rstrip("/").lower()
        # Remove common UTM query params if present
        if "?" in normalized:
            base, query = normalized.split("?", 1)
            params = [p for p in query.split("&") if not p.startswith("utm_")]
            normalized = base + ("?" + "&".join(params) if params else "")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def filter_unseen(self, items: List[RawItem], window_days: int = 30) -> Tuple[List[RawItem], int]:
        """
        Filter out items that have already been processed in the last `window_days`.
        Returns a tuple of (unseen_items, count_of_filtered_items).
        """
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        unseen_items: List[RawItem] = []
        filtered_count = 0

        with self._connection() as conn:
            cursor = conn.cursor()
            for item in items:
                h = self.hash_url(item.url)
                cursor.execute(
                    "SELECT first_seen_at FROM seen_items WHERE url_hash = ? AND last_seen_at >= ?",
                    (h, cutoff_date),
                )
                row = cursor.fetchone()
                if row:
                    filtered_count += 1
                else:
                    unseen_items.append(item)

        logger.info(
            f"Deduplication: {len(unseen_items)} novel items kept, {filtered_count} duplicate items filtered (window: {window_days}d)"
        )
        return unseen_items, filtered_count

    def mark_items_seen(self, items: List[RawItem]) -> None:
        """Record all ingested items into the seen table with timestamps."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn:
            cursor = conn.cursor()
            for item in items:
                h = self.hash_url(item.url)
                cursor.execute("""
                    INSERT INTO seen_items (url_hash, url, title, source, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url_hash) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at,
                        title = excluded.title;
                """, (h, item.url, item.title, item.source, now, now))
            conn.commit()

    def record_digest(self, digest: TechDigest) -> None:
        """Persist a completed digest report and all its categorized items."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn:
            cursor = conn.cursor()

            # Check existing count
            cursor.execute("SELECT COUNT(*) FROM digest_items WHERE digest_date = ?", (digest.date,))
            existing_count = cursor.fetchone()[0]

            # If new digest is empty and we already have items for this date, preserve existing!
            if len(digest.items) == 0 and existing_count > 0:
                logger.info(f"Preserving existing {existing_count} items for {digest.date} against empty harvest.")
                return

            curated_count = len(digest.must_reads) + len(digest.inspirations)
            cursor.execute("""
                INSERT INTO digests (date, total_harvested, total_curated, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_harvested = CASE WHEN excluded.total_harvested > 0 THEN excluded.total_harvested ELSE digests.total_harvested END,
                    total_curated = CASE WHEN excluded.total_curated > 0 THEN excluded.total_curated ELSE digests.total_curated END,
                    created_at = excluded.created_at;
            """, (digest.date, digest.total_harvested, curated_count, now))

            # Only replace items if new digest provides valid items
            if len(digest.items) > 0:
                cursor.execute("DELETE FROM digest_items WHERE digest_date = ?", (digest.date,))
                for item in digest.items:
                    cursor.execute("""
                        INSERT INTO digest_items (
                            digest_date, title, url, source, category, summary, why_it_matters, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        digest.date, item.title, item.url, item.source,
                        item.category, item.summary, item.why_it_matters, now
                    ))

            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        """Fetch summary statistics from the database."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM seen_items;")
            total_seen = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM digests;")
            total_digests = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM digest_items WHERE category = 'Must Read';")
            total_must_reads = cursor.fetchone()[0]

            return {
                "total_seen_urls": total_seen,
                "total_digests_generated": total_digests,
                "total_must_reads": total_must_reads,
            }

    def list_digests(self) -> List[Dict[str, Any]]:
        """List all historical digest summaries ordered by date descending."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date, total_harvested, total_curated, created_at FROM digests ORDER BY date DESC;")
            return [dict(row) for row in cursor.fetchall()]

    def get_digest_by_date(self, target_date: str) -> Optional[Dict[str, Any]]:
        """Fetch complete digest details and items for a specific date."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date, total_harvested, total_curated, created_at FROM digests WHERE date = ?;", (target_date,))
            digest_row = cursor.fetchone()
            if not digest_row:
                return None

            cursor.execute("""
                SELECT title, url, source, category, summary, why_it_matters, created_at
                FROM digest_items
                WHERE digest_date = ?
                ORDER BY CASE category
                    WHEN 'Must Read' THEN 1
                    WHEN 'Inspiration' THEN 2
                    ELSE 3
                END, id ASC;
            """, (target_date,))
            items = [dict(row) for row in cursor.fetchall()]

            res = dict(digest_row)
            res["items"] = items
            return res

    def get_latest_digest(self) -> Optional[Dict[str, Any]]:
        """Fetch the most recent digest."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date FROM digests ORDER BY date DESC LIMIT 1;")
            row = cursor.fetchone()
            if not row:
                return None
            return self.get_digest_by_date(row["date"])


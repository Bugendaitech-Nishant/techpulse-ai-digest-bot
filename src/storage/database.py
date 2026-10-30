"""
database.py — SQLite persistence and deduplication engine.
Maintains a 30-day sliding deduplication window to ensure recurring items
are not recommended repeatedly across daily digests.
"""

import json
import re
import sqlite3
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from src.models import RawItem, TechDigest, DigestItem

from contextlib import contextmanager

logger = logging.getLogger(__name__)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DigestDatabase:
    """Manages SQLite persistence for deduplication and historical metrics."""

    def __init__(self, db_path: Path, auto_hydrate: bool = True):
        self.db_path = Path(db_path)
        self.auto_hydrate = auto_hydrate
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        if auto_hydrate:
            # The rating log (local file, or the feedback branch checked out by CI) is replayed on every start.
            from src.feedback import read_events
            self.load_feedback_events(read_events())

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
                    ranking_backend TEXT NOT NULL DEFAULT 'deterministic',
                    ranking_version TEXT NOT NULL DEFAULT 'v1',
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

            # Table 4: Reader ratings (thumbs up / down) per URL
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    url TEXT PRIMARY KEY,
                    url_hash TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    rated_at TEXT NOT NULL
                );
            """)
            for column in (
                "relevance_score REAL NOT NULL DEFAULT 0",
                "impact_score REAL NOT NULL DEFAULT 0",
                "freshness_score REAL NOT NULL DEFAULT 0",
                "novelty_score REAL NOT NULL DEFAULT 0",
                "confidence REAL NOT NULL DEFAULT 0",
                "priority_score REAL NOT NULL DEFAULT 0",
                "rank INTEGER NOT NULL DEFAULT 0",
                "published_at TEXT NOT NULL DEFAULT ''",
                "tags TEXT NOT NULL DEFAULT '[]'",
            ):
                try:
                    cursor.execute(f"ALTER TABLE digest_items ADD COLUMN {column};")
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise
            try:
                cursor.execute("ALTER TABLE digests ADD COLUMN ranking_version TEXT NOT NULL DEFAULT 'v1';")
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error).lower():
                    raise
            try:
                cursor.execute("ALTER TABLE digests ADD COLUMN ranking_backend TEXT NOT NULL DEFAULT 'deterministic';")
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error).lower():
                    raise
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_digest_items_date ON digest_items(digest_date);")

            # Auto-hydrate database if newly created / empty (critical for ephemeral servers like Render)
            if self.auto_hydrate:
                cursor.execute("SELECT COUNT(*) FROM digests;")
                if cursor.fetchone()[0] == 0:
                    self._auto_hydrate_from_markdown(cursor)

            conn.commit()

    def _auto_hydrate_from_markdown(self, cursor: sqlite3.Cursor) -> None:
        """
        Rebuild the database from the committed digests/ files, so history and deduplication survive
        an ephemeral server (Render). A YYYY-MM-DD.json holds everything; older dates that only have a
        Markdown file are parsed as far as the Markdown allows (no dates, no filtered items).
        """
        from config.settings import settings
        digests_dir = settings.DIGESTS_DIR
        if not digests_dir.exists():
            return

        digests: Dict[str, TechDigest] = {}
        for path in sorted(digests_dir.glob("*.json")):
            if not DATE_RE.match(path.stem):
                continue
            try:
                digests[path.stem] = TechDigest.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not read {path} for auto-hydration: {e}")
        for path in sorted(digests_dir.glob("*.md")):
            if DATE_RE.match(path.stem) and path.stem not in digests:
                try:
                    parsed = self._parse_markdown_digest(path.stem, path.read_text(encoding="utf-8", errors="replace"))
                except Exception as e:
                    logger.warning(f"Could not read {path} for auto-hydration: {e}")
                    continue
                if parsed:
                    digests[path.stem] = parsed

        for digest in digests.values():
            self._write_digest(cursor, digest, digest.generated_at)
            for item in digest.items:
                cursor.execute("""
                    INSERT OR IGNORE INTO seen_items (url_hash, url, title, source, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (self.hash_url(item.url), item.url, item.title, item.source, digest.generated_at, digest.generated_at))

        if digests:
            logger.info(f"Auto-hydrated database with {sum(len(d.items) for d in digests.values())} items across {len(digests)} digests.")

    @staticmethod
    def _parse_markdown_digest(date_str: str, content: str) -> Optional[TechDigest]:
        """Best-effort read of a Markdown digest written before digests were also saved as JSON."""
        from src.agents.publisher import SOURCE_BADGES
        source_keys = {name: key for key, name in SOURCE_BADGES.items()}
        items: List[DigestItem] = []
        for section in content.split("\n## "):
            title = section.split("\n")[0]
            category = "Must Read" if "Must Read" in title else "Inspiration" if "Inspiration" in title else None
            if not category:
                continue
            for block in re.split(r"\n### \d+\. ", "\n" + section)[1:]:
                link = re.search(r"\[(.*?)\]\((.*?)\)", block)
                if not link:
                    continue
                source_line = re.search(r"\*\*Source\*\*:\s*([^\n]*)", block)
                source_text = source_line.group(1) if source_line else ""
                source = source_text.split("·")[0].split("`")[0].strip() or "Feed"
                summary = re.search(r"\*\*Summary\*\*:\s*(.*?)(?=\n\n\*\*Why|\Z)", block, re.DOTALL)
                why = re.search(r"\*\*Why It Matters\*\*:\s*(.*?)(?=\n\n---|\n---|\Z)", block, re.DOTALL)
                priority = re.search(r"\*\*Priority\*\*:\s*([\d.]+)", block)
                items.append(DigestItem(
                    title=link.group(1).strip(),
                    url=link.group(2).strip(),
                    source=source_keys.get(source, source),
                    category=category,
                    summary=summary.group(1).strip() if summary else "",
                    why_it_matters=why.group(1).strip() if why else "",
                    tags=re.findall(r"`([^`]+)`", source_text),
                    priority_score=min(100.0, float(priority.group(1))) if priority else 0.0,
                ))
        if not items:
            return None
        items = [i.model_copy(update={"rank": n}) for n, i in enumerate(items, 1)]
        harvested = re.search(r"Total Harvested:\s*(\d+)", content)
        generated = re.search(r"\*\*Generated At\*\*:\s*`([^`]+)`", content)
        return TechDigest(
            date=date_str,
            items=items,
            total_harvested=int(harvested.group(1)) if harvested else len(items),
            total_curated=len(items),
            generated_at=generated.group(1) if generated else f"{date_str}T00:00:00+00:00",
        )

    @staticmethod
    def _write_digest(cursor: sqlite3.Cursor, digest: TechDigest, created_at: str) -> None:
        """Insert or update one digest row and replace its items. The caller owns the transaction."""
        curated = len(digest.must_reads) + len(digest.inspirations)
        cursor.execute("""
            INSERT INTO digests (date, total_harvested, total_curated, ranking_backend, ranking_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_harvested = CASE WHEN excluded.total_harvested > 0 THEN excluded.total_harvested ELSE digests.total_harvested END,
                total_curated = CASE WHEN excluded.total_curated > 0 THEN excluded.total_curated ELSE digests.total_curated END,
                created_at = excluded.created_at;
        """, (digest.date, digest.total_harvested, curated, digest.ranking_backend, digest.ranking_version, created_at))
        if not digest.items:
            return
        cursor.execute("DELETE FROM digest_items WHERE digest_date = ?", (digest.date,))
        for item in digest.items:
            cursor.execute("""
                INSERT INTO digest_items (
                    digest_date, title, url, source, category, summary, why_it_matters,
                    relevance_score, impact_score, freshness_score, novelty_score,
                    confidence, priority_score, rank, published_at, tags, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                digest.date, item.title, item.url, item.source,
                item.category, item.summary, item.why_it_matters,
                item.relevance_score, item.impact_score, item.freshness_score,
                item.novelty_score, item.confidence, item.priority_score, item.rank,
                item.published_at, json.dumps(item.tags), created_at,
            ))

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
        with self._connection() as conn:
            cursor = conn.cursor()

            # Check existing count
            cursor.execute("SELECT COUNT(*) FROM digest_items WHERE digest_date = ?", (digest.date,))
            existing_count = cursor.fetchone()[0]

            # If new digest is empty and we already have items for this date, preserve existing!
            if len(digest.items) == 0 and existing_count > 0:
                logger.info(f"Preserving existing {existing_count} items for {digest.date} against empty harvest.")
                return

            self._write_digest(cursor, digest, digest.generated_at)
            conn.commit()

    # ─── Reader feedback ────────────────────────────────────────────────

    def record_feedback(self, event: Dict[str, Any]) -> bool:
        """Store a rating event; an older event never overwrites a newer one. Returns True if stored."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rated_at FROM feedback WHERE url = ?;", (event["url"],))
            row = cursor.fetchone()
            if row and row["rated_at"] > event["at"]:
                return False
            cursor.execute(
                """
                INSERT INTO feedback (url, url_hash, rating, title, source, summary, category, rated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    rating = excluded.rating, title = excluded.title, source = excluded.source,
                    summary = excluded.summary, category = excluded.category, rated_at = excluded.rated_at;
                """,
                (
                    event["url"], self.hash_url(event["url"]), event["rating"], event.get("title", ""),
                    event.get("source", ""), event.get("summary", ""), event.get("category", ""), event["at"],
                ),
            )
            conn.commit()
            return True

    def load_feedback_events(self, events: List[Dict[str, Any]]) -> int:
        """Replay a durable log into the table (used at start-up). Returns how many were applied."""
        return sum(1 for event in events if self.record_feedback(event))

    def get_feedback_map(self) -> Dict[str, int]:
        """Current rating per URL, cleared ratings (0) excluded."""
        with self._connection() as conn:
            rows = conn.execute("SELECT url, rating FROM feedback WHERE rating != 0;").fetchall()
        return {row["url"]: row["rating"] for row in rows}

    def get_feedback_examples(self, limit: int = 8) -> Dict[str, List[Dict[str, Any]]]:
        """Most recent liked and disliked items, for calibrating the curator."""
        out: Dict[str, List[Dict[str, Any]]] = {"up": [], "down": []}
        with self._connection() as conn:
            for key, rating in (("up", 1), ("down", -1)):
                rows = conn.execute(
                    "SELECT title, source, summary FROM feedback WHERE rating = ? AND title != '' "
                    "ORDER BY rated_at DESC LIMIT ?;",
                    (rating, limit),
                ).fetchall()
                out[key] = [dict(r) for r in rows]
        return out

    def get_feedback_counts(self) -> Dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute("SELECT rating, COUNT(*) AS n FROM feedback WHERE rating != 0 GROUP BY rating;").fetchall()
        counts = {row["rating"]: row["n"] for row in rows}
        return {"up": counts.get(1, 0), "down": counts.get(-1, 0)}

    def find_item_by_hash(self, url_hash: str) -> Optional[Dict[str, Any]]:
        """Look a digest item up by the hash of its URL (email links carry the hash, not the URL)."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT title, url, source, category, summary FROM digest_items ORDER BY id DESC;"
            ).fetchall()
        for row in rows:
            if self.hash_url(row["url"]) == url_hash:
                return dict(row)
        return None

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

    def _feedback_insights(self, recent_digests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """How useful the reader found the digest: overall, and for the top 10 of each recent digest."""
        counts = self.get_feedback_counts()
        ratings = self.get_feedback_map()
        top_up = top_down = 0
        for digest in recent_digests:
            detail = self.get_digest_by_date(digest["date"]) or {}
            kept = [i for i in detail.get("items", []) if i["category"] != "Skip"][:10]
            for item in kept:
                rating = ratings.get(item["url"], 0)
                top_up += rating == 1
                top_down += rating == -1
        def rate(up: int, down: int):
            return round(up / (up + down), 3) if up + down else None
        return {
            "up": counts["up"],
            "down": counts["down"],
            "useful_rate": rate(counts["up"], counts["down"]),
            "top10_rated": top_up + top_down,
            "top10_useful_rate": rate(top_up, top_down),
        }

    def get_insights(self, window_days: int = 30) -> Dict[str, Any]:
        """Aggregate real, DB-derived statistics for the dashboard (no synthetic figures)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT date, total_harvested, total_curated, ranking_backend, ranking_version, created_at "
                "FROM digests ORDER BY date DESC;"
            )
            digests = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT category, COUNT(*) AS n FROM digest_items GROUP BY category;")
            by_category = {row["category"]: row["n"] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT source, COUNT(*) AS n, MAX(priority_score) AS best, AVG(priority_score) AS avg "
                "FROM digest_items WHERE category != 'Skip' GROUP BY source ORDER BY n DESC, source ASC;"
            )
            by_source = [
                {
                    "source": row["source"],
                    "count": row["n"],
                    # priority_score is 0 for digests rehydrated from markdown, so report it only when measured
                    "avg_priority": round(row["avg"], 1) if row["best"] else None,
                }
                for row in cursor.fetchall()
            ]

            cursor.execute("SELECT COUNT(*) FROM seen_items WHERE first_seen_at >= ?;", (cutoff,))
            seen_window = cursor.fetchone()[0]

        feedback = self._feedback_insights(digests[:14])
        harvested = sum(d["total_harvested"] for d in digests)
        curated = sum(d["total_curated"] for d in digests)
        latest = digests[0] if digests else None
        return {
            "window_days": window_days,
            "digests_total": len(digests),
            "items_total": sum(n for cat, n in by_category.items() if cat != "Skip"),
            "seen_in_window": seen_window,
            "last_harvest_at": max((d["created_at"] for d in digests), default=None),
            "latest": latest,
            "keep_rate": round(curated / harvested, 3) if harvested else None,
            "feedback": feedback,
            "by_category": by_category,
            "by_source": by_source,
            "history": [
                {"date": d["date"], "harvested": d["total_harvested"], "curated": d["total_curated"]}
                for d in digests[:30]
            ],
        }

    def list_digests(self) -> List[Dict[str, Any]]:
        """List all historical digest summaries ordered by date descending."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date, total_harvested, total_curated, ranking_backend, ranking_version, created_at FROM digests ORDER BY date DESC;")
            return [dict(row) for row in cursor.fetchall()]

    def get_digest_by_date(self, target_date: str) -> Optional[Dict[str, Any]]:
        """Fetch complete digest details and items for a specific date."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date, total_harvested, total_curated, ranking_backend, ranking_version, created_at FROM digests WHERE date = ?;", (target_date,))
            digest_row = cursor.fetchone()
            if not digest_row:
                return None

            cursor.execute("""
                SELECT title, url, source, category, summary, why_it_matters,
                       relevance_score, impact_score, freshness_score, novelty_score,
                       confidence, priority_score, rank, published_at, tags, created_at
                FROM digest_items
                WHERE digest_date = ?
                ORDER BY CASE category WHEN 'Must Read' THEN 1 WHEN 'Inspiration' THEN 2 ELSE 3 END,
                         priority_score DESC, id ASC;
            """, (target_date,))
            items = [{**dict(row), "tags": json.loads(row["tags"] or "[]")} for row in cursor.fetchall()]

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

"""
test_database.py — Unit tests for SQLite persistence and 30-day deduplication logic.
"""

import tempfile
from pathlib import Path
from src.storage.database import DigestDatabase
from src.models import RawItem, DigestItem, TechDigest


def test_database_initialization():
    """Verify that database tables and indexes are created properly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = DigestDatabase(db_path, auto_hydrate=False)
        assert db_path.exists()
        stats = db.get_stats()
        assert stats["total_seen_urls"] == 0
        assert stats["total_digests_generated"] == 0


def test_url_hash_normalization():
    """Verify that URL normalization ignores trailing slashes, case, and utm params."""
    u1 = "https://github.com/developer/project/"
    u2 = "HTTPS://GITHUB.COM/DEVELOPER/PROJECT"
    u3 = "https://github.com/developer/project?utm_source=twitter&utm_medium=social"

    h1 = DigestDatabase.hash_url(u1)
    h2 = DigestDatabase.hash_url(u2)
    h3 = DigestDatabase.hash_url(u3)

    assert h1 == h2
    assert h1 == h3


def test_deduplication_window():
    """Verify that duplicate items are filtered within the sliding window."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = DigestDatabase(db_path, auto_hydrate=False)

        item1 = RawItem(
            title="Project A",
            url="https://github.com/org/project-a",
            source="github_trending",
        )
        item2 = RawItem(
            title="Project B",
            url="https://github.com/org/project-b",
            source="github_trending",
        )

        # First run: both are unseen
        unseen, filtered = db.filter_unseen([item1, item2], window_days=30)
        assert len(unseen) == 2
        assert filtered == 0

        # Mark them as seen
        db.mark_items_seen([item1, item2])

        # Second run: both should now be filtered as duplicates
        unseen_2, filtered_2 = db.filter_unseen([item1, item2], window_days=30)
        assert len(unseen_2) == 0
        assert filtered_2 == 2

        # A new third item should still be seen
        item3 = RawItem(
            title="Project C",
            url="https://github.com/org/project-c",
            source="github_trending",
        )
        unseen_3, filtered_3 = db.filter_unseen([item1, item3], window_days=30)
        assert len(unseen_3) == 1
        assert unseen_3[0].title == "Project C"
        assert filtered_3 == 1


def test_record_digest():
    """Verify recording of daily digests and metrics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = DigestDatabase(db_path, auto_hydrate=False)

        d_item = DigestItem(
            title="LangGraph Pro",
            url="https://github.com/langchain-ai/langgraph",
            source="github_trending",
            category="Must Read",
            summary="Stateful agent graph.",
            why_it_matters="Core framework.",
        )
        digest = TechDigest(
            date="2026-10-22",
            items=[d_item],
            total_harvested=10,
            total_curated=1,
        )

        db.record_digest(digest)
        stats = db.get_stats()
        assert stats["total_digests_generated"] == 1
        assert stats["total_must_reads"] == 1
        assert db.get_digest_by_date("2026-10-22")["ranking_version"] == "v1"
        assert db.get_digest_by_date("2026-10-22")["ranking_backend"] == "deterministic"


def test_auto_hydration_from_markdown():
    """Verify that a brand new empty database auto-hydrates from committed markdown files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "fresh_autohydrate.db"
        # Initializing the database will trigger auto-hydration from digests/*.md
        db = DigestDatabase(db_path)

        digests = db.list_digests()
        assert len(digests) >= 1  # Should find 2026-10-22.md or other committed digests
        latest = db.get_latest_digest()
        assert latest is not None
        assert len(latest["items"]) > 0

        # Verify seen_items deduplication table was also hydrated
        stats = db.get_stats()
        assert stats["total_seen_urls"] > 0

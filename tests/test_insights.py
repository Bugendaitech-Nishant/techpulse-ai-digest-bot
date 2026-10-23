"""Tests for the DB-derived dashboard statistics (no synthetic figures)."""

import tempfile
from pathlib import Path

from src.models import DigestItem, TechDigest
from src.storage.database import DigestDatabase


def _item(url: str, source: str, category: str, priority: float = 0.0) -> DigestItem:
    return DigestItem(
        title=f"Item {url}",
        url=f"https://example.com/{url}",
        source=source,
        category=category,
        summary="s",
        why_it_matters="w",
        priority_score=priority,
    )


def test_insights_empty_database_has_no_invented_numbers():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DigestDatabase(Path(tmpdir) / "t.db", auto_hydrate=False)
        insights = db.get_insights()
        assert insights["digests_total"] == 0
        assert insights["items_total"] == 0
        assert insights["last_harvest_at"] is None
        assert insights["keep_rate"] is None
        assert insights["by_source"] == []


def test_insights_aggregate_sources_funnel_and_priority():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DigestDatabase(Path(tmpdir) / "t.db", auto_hydrate=False)
        db.record_digest(
            TechDigest(
                date="2026-10-20",
                total_harvested=10,
                total_curated=3,
                items=[
                    _item("a", "arxiv_ai", "Must Read", 80.0),
                    _item("b", "arxiv_ai", "Inspiration", 40.0),
                    _item("c", "hacker_news", "Must Read", 0.0),
                ],
            )
        )
        insights = db.get_insights()
        assert insights["digests_total"] == 1
        assert insights["items_total"] == 3
        assert insights["keep_rate"] == 0.3
        assert insights["by_category"] == {"Must Read": 2, "Inspiration": 1}
        sources = {s["source"]: s for s in insights["by_source"]}
        assert sources["arxiv_ai"]["count"] == 2
        assert sources["arxiv_ai"]["avg_priority"] == 60.0
        assert sources["hacker_news"]["avg_priority"] is None  # never measured
        assert insights["history"] == [{"date": "2026-10-20", "harvested": 10, "curated": 3}]

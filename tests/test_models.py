"""
test_models.py — Unit tests for Pydantic data schemas and validation rules.
"""

import pytest
from src.models import RawItem, DigestItem, TechDigest, CollectorResult


def test_raw_item_valid():
    """Verify valid RawItem creation and URL/title cleaning."""
    item = RawItem(
        title="  Awesome AI Agent Framework  ",
        url="https://github.com/example/agent",
        description="A great framework",
        source="github_trending",
        score=150,
        language="Python",
    )
    assert item.title == "Awesome AI Agent Framework"
    assert item.url == "https://github.com/example/agent"
    assert item.score == 150
    assert item.source == "github_trending"


def test_raw_item_invalid_url():
    """Verify that malformed URLs trigger ValueError."""
    with pytest.raises(ValueError):
        RawItem(
            title="Invalid URL Item",
            url="ftp://invalid.com/item",
            source="test",
        )


def test_digest_item_properties():
    """Verify categorization filtering properties on TechDigest."""
    d1 = DigestItem(
        title="Agent Engine",
        url="https://example.com/1",
        source="github_trending",
        category="Must Read",
        summary="Builds agent systems.",
        why_it_matters="Very relevant.",
    )
    d2 = DigestItem(
        title="Side Toy",
        url="https://example.com/2",
        source="hacker_news",
        category="Inspiration",
        summary="Fun toy.",
        why_it_matters="Creative concept.",
    )
    d3 = DigestItem(
        title="Boring Article",
        url="https://example.com/3",
        source="devto_articles",
        category="Skip",
        summary="Not useful.",
        why_it_matters="Irrelevant.",
    )

    digest = TechDigest(date="2026-10-22", items=[d1, d2, d3])
    assert digest.ranking_version == "v1"
    assert digest.ranking_backend == "deterministic"
    assert len(digest.must_reads) == 1
    assert digest.must_reads[0].title == "Agent Engine"
    assert len(digest.inspirations) == 1
    assert digest.inspirations[0].title == "Side Toy"
    assert len(digest.skips) == 1


def test_collector_result():
    """Verify telemetry model fields."""
    res = CollectorResult(collector_name="test_collector", success=True, duration_seconds=1.23)
    assert res.collector_name == "test_collector"
    assert res.duration_seconds == 1.23
    assert res.error is None

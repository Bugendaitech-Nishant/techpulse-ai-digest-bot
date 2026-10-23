from datetime import datetime, timezone

from src.models import DigestItem, RawItem
from src.ranking import rank_items


def _digest(title, url, category="Must Read", **scores):
    return DigestItem(
        title=title,
        url=url,
        source="github_trending",
        category=category,
        summary=title,
        why_it_matters="Relevant.",
        **scores,
    )


def test_ranking_is_deterministic_and_category_ordered():
    raw = [
        RawItem(title="Routine tool", url="https://x/routine", source="github_trending", score=10),
        RawItem(title="Important tool", url="https://x/important", source="github_trending", score=20),
        RawItem(title="Idea", url="https://x/idea", source="hacker_news", score=100),
    ]
    items = [
        _digest("Idea", "https://x/idea", "Inspiration"),
        _digest("Routine tool", "https://x/routine"),
        _digest("Important tool", "https://x/important"),
    ]

    result = rank_items(items, raw, now=datetime(2026, 10, 23, tzinfo=timezone.utc))

    assert [item.category for item in result] == ["Must Read", "Must Read", "Inspiration"]
    assert result[0].rank == 1
    assert result[0].priority_score >= result[1].priority_score
    assert rank_items(items, raw, now=datetime(2026, 10, 23, tzinfo=timezone.utc)) == result


def test_ranking_normalizes_scores_per_source():
    raw = [
        RawItem(title="GitHub low", url="https://x/github-low", source="github_trending", score=10),
        RawItem(title="GitHub high", url="https://x/github-high", source="github_trending", score=1000),
        RawItem(title="HN low", url="https://x/hn-low", source="hacker_news", score=1),
        RawItem(title="HN high", url="https://x/hn-high", source="hacker_news", score=100),
    ]
    items = [_digest(raw_item.title, raw_item.url) for raw_item in raw]

    result = rank_items(items, raw, now=datetime(2026, 10, 23, tzinfo=timezone.utc))
    by_url = {item.url: item for item in result}

    assert by_url["https://x/github-high"].priority_score > by_url["https://x/github-low"].priority_score
    assert by_url["https://x/hn-high"].priority_score > by_url["https://x/hn-low"].priority_score
    assert all(0 <= item.priority_score <= 100 for item in result)


def test_recent_items_receive_higher_freshness():
    raw = [
        RawItem(title="Old", url="https://x/old", source="github_trending", published_at="2026-10-01T00:00:00+00:00"),
        RawItem(title="New", url="https://x/new", source="github_trending", published_at="2026-10-23T00:00:00+00:00"),
    ]
    result = rank_items(
        [_digest("Old", "https://x/old"), _digest("New", "https://x/new")],
        raw,
        now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
    )
    by_url = {item.url: item for item in result}

    assert by_url["https://x/new"].freshness_score > by_url["https://x/old"].freshness_score


def test_malformed_or_naive_dates_are_safe():
    raw = [
        RawItem(title="Malformed", url="https://x/malformed", source="github_trending", published_at="not-a-date"),
        RawItem(title="Naive", url="https://x/naive", source="github_trending", published_at="2026-10-23T00:00:00"),
    ]

    result = rank_items(
        [_digest("Malformed", raw[0].url), _digest("Naive", raw[1].url)],
        raw,
        now=datetime(2026, 10, 23, 12),
    )

    assert all(0 <= item.freshness_score <= 1 for item in result)


def test_equal_inputs_have_stable_ordering():
    raw = [
        RawItem(title="Same", url="https://x/a", source="github_trending", score=1),
        RawItem(title="Same", url="https://x/b", source="github_trending", score=1),
    ]
    items = [_digest("Same", raw[0].url), _digest("Same", raw[1].url)]

    result = rank_items(items, raw, now=datetime(2026, 10, 23, tzinfo=timezone.utc))

    assert [item.url for item in result] == [
        item.url for item in rank_items(items, raw, now=datetime(2026, 10, 23, tzinfo=timezone.utc))
    ]

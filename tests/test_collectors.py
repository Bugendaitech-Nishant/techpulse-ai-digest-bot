"""
test_collectors.py — Unit and isolation tests for all 6 data collectors.
"""

from unittest.mock import patch, MagicMock
from src.collectors import (
    GitHubTrendingCollector,
    GitHubSearchCollector,
    HackerNewsCollector,
    HuggingFacePapersCollector,
    DevToCollector,
    ArXivCollector,
)


def test_collector_isolation_on_network_error():
    """Verify that collectors return clean CollectorResult with error on failure, never crashing."""
    collector = GitHubTrendingCollector()

    with patch("requests.get", side_effect=Exception("Connection timed out")):
        res = collector.fetch()
        assert res.success is False
        assert len(res.items) == 0
        assert "Connection timed out" in (res.error or "")


def test_hacker_news_collector_parsing():
    """Verify parsing of Algolia HN API response."""
    collector = HackerNewsCollector()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "hits": [
            {
                "title": "Show HN: Modern AI Agent",
                "url": "https://example.com/agent",
                "objectID": "12345",
                "points": 142,
                "num_comments": 48,
                "author": "dev",
            }
        ]
    }

    with patch("requests.get", return_value=mock_response):
        res = collector.fetch()
        assert res.success is True
        assert len(res.items) == 1
        item = res.items[0]
        assert item.title == "Show HN: Modern AI Agent"
        assert item.url == "https://example.com/agent"
        assert item.score == 142
        assert item.source == "hacker_news"


def test_huggingface_papers_collector_parsing():
    """Verify parsing of Hugging Face Daily Papers API."""
    collector = HuggingFacePapersCollector()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "paper": {
                "id": "2410.12345",
                "title": "Scaling Autonomous Agents with Memory",
                "summary": "This paper presents a novel memory consolidation architecture.",
            },
            "upvotes": 85,
        }
    ]

    with patch("requests.get", return_value=mock_response):
        res = collector.fetch()
        assert res.success is True
        assert len(res.items) == 1
        item = res.items[0]
        assert "Scaling Autonomous Agents" in item.title
        assert item.url == "https://huggingface.co/papers/2410.12345"
        assert item.score == 85
        assert item.source == "huggingface_papers"


def test_devto_collector_parsing():
    """Verify parsing of Dev.to articles API."""
    collector = DevToCollector()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "title": "Building Production Multi-Agent Systems in Python",
            "url": "https://dev.to/user/building-agents",
            "positive_reactions_count": 67,
            "reading_time_minutes": 8,
            "description": "A comprehensive deep dive into orchestration.",
        }
    ]

    with patch("requests.get", return_value=mock_response):
        res = collector.fetch()
        assert res.success is True
        assert len(res.items) >= 1
        item = res.items[0]
        assert item.title == "Building Production Multi-Agent Systems in Python"
        assert item.score == 67


def test_devto_collector_skips_bare_bracket_reposts():
    """A '[Boost]' repost has no real title and must not reach the digest."""
    collector = DevToCollector()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"title": "[Boost]", "url": "https://dev.to/u/boost", "positive_reactions_count": 1},
        {"title": "A real article", "url": "https://dev.to/u/real", "positive_reactions_count": 5},
    ]
    with patch("requests.get", return_value=mock_response):
        titles = {i.title for i in collector.fetch().items}
    assert titles == {"A real article"}

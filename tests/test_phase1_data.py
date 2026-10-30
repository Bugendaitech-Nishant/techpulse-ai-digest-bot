"""Phase 1: dates, tags and real counts survive the JSON/Markdown round trip; stale items are dropped."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from config.settings import settings
from src.agents.harvester import is_too_old
from src.agents.publisher import PublisherAgent
from src.collectors.github_search import GitHubSearchCollector
from src.models import DigestItem, RawItem, TechDigest
from src.storage.database import DigestDatabase

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _digest() -> TechDigest:
    items = [
        DigestItem(title="A", url="https://a.dev/1", source="hacker_news", category="Must Read", summary="s",
                   why_it_matters="w", tags=["LiteLLM", "security"], published_at="2026-10-30T08:00:00+00:00",
                   priority_score=91.0, rank=1),
        DigestItem(title="B", url="https://b.dev/2", source="arxiv_ai", category="Skip", summary="s",
                   why_it_matters="w", rank=2),
    ]
    return TechDigest(date="2026-10-30", items=items, total_harvested=94, generated_at="2026-10-30T03:44:00+00:00")


def test_json_digest_keeps_dates_tags_filtered_items_and_build_time(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIGESTS_DIR", tmp_path)
    PublisherAgent(output_dir=tmp_path).publish(_digest())
    assert (tmp_path / "2026-10-30.json").exists()

    stored = DigestDatabase(tmp_path / "rebuilt.db").get_digest_by_date("2026-10-30")
    first = stored["items"][0]
    assert first["published_at"] == "2026-10-30T08:00:00+00:00"
    assert first["tags"] == ["LiteLLM", "security"]
    assert [i["category"] for i in stored["items"]] == ["Must Read", "Skip"]  # filtered item survives
    assert stored["total_harvested"] == 94
    assert stored["created_at"] == "2026-10-30T03:44:00+00:00"  # not the time the server woke up


def test_markdown_only_digest_still_recovers_tags_counts_and_source_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIGESTS_DIR", tmp_path)
    publisher = PublisherAgent(output_dir=tmp_path)
    publisher.publish(_digest())
    (tmp_path / "2026-10-30.json").unlink()  # simulate a digest written before JSON existed

    stored = DigestDatabase(tmp_path / "rebuilt.db").get_digest_by_date("2026-10-30")
    first = stored["items"][0]
    assert first["source"] == "hacker_news"  # the badge name maps back to the collector key
    assert first["tags"] == ["LiteLLM", "security"]
    assert first["published_at"] == ""  # unknown, never guessed
    assert stored["total_harvested"] == 94
    assert len(stored["items"]) == 1  # Markdown has no filtered items


def test_too_old_rule():
    def item(source, published):
        return RawItem(title="x y", url="https://x.dev/", source=source, published_at=published)

    old = (NOW - timedelta(days=15)).isoformat()
    recent = (NOW - timedelta(days=2)).isoformat()
    assert is_too_old(item("huggingface_papers", old), 7, NOW)
    assert not is_too_old(item("huggingface_papers", recent), 7, NOW)
    assert not is_too_old(item("huggingface_papers", ""), 7, NOW)  # undated is kept
    assert not is_too_old(item("huggingface_papers", "not a date"), 7, NOW)
    assert not is_too_old(item("github_trending", old), 7, NOW)  # trending today, however old the repo
    assert not is_too_old(item("security_advisories", old), 7, NOW)


def test_github_search_asks_once_per_topic_and_uses_push_date():
    def response(repos):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"items": repos}
        return resp

    def repo(name, stars):
        return {"full_name": name, "html_url": f"https://github.com/{name}", "stargazers_count": stars,
                "pushed_at": "2026-10-29T10:00:00Z", "created_at": "2019-01-01T00:00:00Z"}

    replies = [response([repo("a/one", 90)]), response([repo("a/one", 90), repo("b/two", 400)]), response([])]
    with patch("src.collectors.github_search.requests.get", side_effect=replies) as get:
        items = GitHubSearchCollector()._fetch_items()

    assert get.call_count == 3
    assert [i.title for i in items] == ["b/two", "a/one"]  # merged, de-duplicated, most stars first
    assert items[0].published_at == "2026-10-29T10:00:00Z"

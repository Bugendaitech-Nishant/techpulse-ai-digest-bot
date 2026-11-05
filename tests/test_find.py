"""Find: ranked archive search for a use case, and live GitHub discovery."""

import pytest
import requests
from fastapi.testclient import TestClient

import api
from src import discover
from src.models import DigestItem, TechDigest
from src.security.cache_manager import cache_manager
from src.storage.database import DigestDatabase


def _i(n, title, summary, topics, source="github_trending", tags=(), date="2026-11-04", category="Must Read"):
    return DigestItem(title=title, url=f"https://example.com/{n}", source=source, category=category, summary=summary,
                      why_it_matters="w", topics=list(topics), tags=list(tags), next_step="Read")


@pytest.fixture
def db(tmp_path):
    d = DigestDatabase(tmp_path / "t.db", auto_hydrate=False)
    d.record_digest(TechDigest(date="2026-11-04", total_harvested=5, items=[
        _i(1, "acme vector database engine", "A store with tenant isolation for retrieval augmented generation", ["rag", "databases"], tags=["vector"]),
        _i(2, "Serving models cheaply", "How we serve open models with batching and quantization", ["inference"], source="devto_articles"),
        _i(3, "React 20 released", "Server components land in the compiler", ["web", "javascript"], source="hacker_news"),
        _i(4, "Attention is cheaper now", "A paper on linear attention for long context", ["research", "llm-models"], source="arxiv_ai"),
        _i(5, "Noise", "vector vector vector", ["startups"], category="Skip"),
    ]))
    return d


def test_title_matches_outrank_body_matches_and_skips_are_hidden(db):
    db.record_digest(TechDigest(date="2026-11-03", total_harvested=1, items=[
        _i(6, "Weekly links", "mentions a vector database in passing", ["databases"], date="2026-11-03")]))
    urls = [i["url"] for i in db.search_items("vector database")]
    assert urls[0] == "https://example.com/1" and "https://example.com/5" not in urls


def test_words_are_stemmed_and_match_as_prefixes(db):
    assert [i["url"] for i in db.search_items("serve model")][0] == "https://example.com/2"   # serving -> serve
    assert [i["url"] for i in db.search_items("quantiz")][0] == "https://example.com/2"       # prefix


def test_use_case_phrasing_widens_to_any_word_when_few_match_all(db):
    items, mode = db.search_with_mode("I need a vector database with tenant streaming")
    assert mode == "any" and items and items[0]["url"] == "https://example.com/1"
    assert db.search_with_mode("")[1] == "recent"


def test_one_shared_word_is_not_an_answer(db):
    db.record_digest(TechDigest(date="2026-11-02", total_harvested=2, items=[
        _i(20, "Cost-aware abstention for LLM tickets", "cost of wrong answers", ["llm-models"], source="arxiv_ai"),
        _i(21, "Agent state machines", "managing state in agents", ["agents"])]))
    # each shares one word with the query; that is how unrelated items look relevant
    assert db.search_with_mode("kubernetes cost visibility")[0] == []
    assert db.search_with_mode("react state management")[0] == []
    assert db.search_with_mode("cost")[0], "a one-word query still matches on that word"


def test_a_query_with_plenty_of_exact_matches_is_not_widened(db):
    db.record_digest(TechDigest(date="2026-11-03", total_harvested=6, items=[
        _i(10 + n, f"Kafka tip {n}", "kafka streams", ["data-engineering"]) for n in range(6)]))
    assert db.search_with_mode("kafka streams")[1] == "all"


def test_filters_by_kind_and_area(db):
    assert [i["url"] for i in db.search_items("", kind="paper")] == ["https://example.com/4"]
    assert [i["url"] for i in db.search_items("", area="Frontend & mobile")] == ["https://example.com/3"]
    assert {i["url"] for i in db.search_items("", kind="tool")} == {"https://example.com/1"}


def test_hostile_queries_cannot_break_the_index(db):
    for q in ['"', "AND OR NOT", "foo*bar", "') DROP TABLE digest_items; --", "NEAR(", "a:b", "(((", "\\"]:
        db.search_items(q)  # must not raise
    assert db.search_items("react")


def test_index_follows_edits(db):
    db.set_story_ids({"https://example.com/3": "abc"})  # an update that does not touch indexed columns
    assert db.search_items("react")
    db.record_digest(TechDigest(date="2026-11-04", total_harvested=1, items=[_i(7, "Replaced", "only this remains", ["web"])]))
    assert not db.search_items("react") and db.search_items("replaced")


def test_existing_databases_get_indexed_on_upgrade(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    d = DigestDatabase(path, auto_hydrate=False)
    d.record_digest(TechDigest(date="2026-11-04", total_harvested=1, items=[_i(1, "Old row", "kafka streams", ["data-engineering"])]))
    with sqlite3.connect(path) as conn:
        for trigger in ("items_ai", "items_ad", "items_au"):
            conn.execute(f"DROP TRIGGER {trigger}")
        conn.execute("DROP TABLE items_fts")
    assert [i["title"] for i in DigestDatabase(path, auto_hydrate=False).search_items("kafka")] == ["Old row"]


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_manager.invalidate()


def test_github_discovery_maps_results_and_caches(monkeypatch):
    calls = []
    body = {"items": [{"full_name": "a/b", "html_url": "https://github.com/a/b", "description": "d", "stargazers_count": 900,
                       "language": "Rust", "pushed_at": "2026-11-01T00:00:00Z", "topics": ["x"], "license": {"spdx_id": "MIT"}}]}
    monkeypatch.setattr(discover.requests, "get", lambda url, **kw: calls.append(kw) or _Resp(200, body))
    first = discover.github_repos("vector database for rag")
    assert first["items"][0] == {"title": "a/b", "url": "https://github.com/a/b", "description": "d", "stars": 900,
                                 "language": "Rust", "pushed_at": "2026-11-01T00:00:00Z", "topics": ["x"], "license": "MIT"}
    assert "archived:false" in calls[0]["params"]["q"] and "stars:>" in calls[0]["params"]["q"]
    discover.github_repos("rag vector database")  # same words, other order and filler: served from cache
    assert len(calls) == 1


@pytest.mark.parametrize("response,fragment", [(_Resp(403), "rate limiting"), (_Resp(500), "HTTP 500")])
def test_github_failures_become_messages_not_errors(monkeypatch, response, fragment):
    monkeypatch.setattr(discover.requests, "get", lambda *a, **k: response)
    out = discover.github_repos("kafka")
    assert out["items"] == [] and fragment in out["error"]


def test_github_unreachable_is_reported(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(discover.requests, "get", boom)
    assert "could not be reached" in discover.github_repos("kafka")["error"]
    assert discover.github_repos("the and of") == {"items": [], "error": ""}  # nothing searchable: no request


def test_endpoints(db, monkeypatch):
    monkeypatch.setattr(api, "db", db)
    monkeypatch.setattr(discover.requests, "get", lambda *a, **k: _Resp(200, {"items": []}))
    client = TestClient(api.app)
    data = client.get("/api/search", params={"q": "vector database", "kind": "tool"}).json()
    assert data["items"][0]["kind"] == "tool" and "GenAI & ML" in data["areas"]
    assert data["items"][0]["areas"] == ["GenAI & ML", "Backend & data"] and data["mode"] in ("all", "any")
    assert client.get("/api/discover", params={"q": "kafka"}).json() == {"items": [], "error": ""}

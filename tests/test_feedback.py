"""Tests for ratings: signing, the durable log, the table, the API, GitHub sync and the curation prompt."""

import base64
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from config.settings import settings
from src import delivery
from src import feedback as fb
from src.agents.processor import ProcessorAgent
from src.models import DigestItem, TechDigest
from src.storage.database import DigestDatabase


def _db(tmp_path: Path) -> DigestDatabase:
    return DigestDatabase(tmp_path / "t.db", auto_hydrate=False)


def _seed(db: DigestDatabase, n: int = 3) -> list[str]:
    items = [
        DigestItem(title=f"Title {i}", url=f"https://example.com/{i}", source="arxiv_ai",
                   category="Must Read", summary=f"Summary {i}", why_it_matters="w")
        for i in range(n)
    ]
    db.record_digest(TechDigest(date="2026-10-23", items=items, total_harvested=n))
    return [i.url for i in items]


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(settings, "FEEDBACK_SECRET", "s3cret")


def test_signature_round_trip_and_tamper_detection(secret):
    h = DigestDatabase.hash_url("https://example.com/1")
    sig = fb.sign(h, "up")
    assert fb.verify(h, "up", sig)
    assert not fb.verify(h, "down", sig)  # a signature for one verdict is not valid for the other
    assert not fb.verify(h[:-1] + "0", "up", sig)
    assert not fb.verify(h, "up", "")


def test_no_secret_means_no_links_and_no_valid_signatures(monkeypatch):
    monkeypatch.setattr(settings, "FEEDBACK_SECRET", "")
    assert fb.feedback_link("https://x.example/", "a" * 64, "up") == ""
    assert not fb.verify("a" * 64, "up", "anything")


def test_log_keeps_the_latest_event_per_url_and_skips_corrupt_lines(tmp_path):
    log = tmp_path / "f.jsonl"
    fb.append_event(fb.make_event("https://e.com/1", 1, "T", "s", "sum", "Must Read"), log)
    log.write_text(log.read_text() + "not json\n", encoding="utf-8")
    fb.append_event(fb.make_event("https://e.com/1", -1, "T", "s", "sum", "Must Read"), log)
    events = fb.read_events(log)
    assert len(events) == 2
    assert fb.latest_by_url(events)["https://e.com/1"]["rating"] == -1


def test_table_rating_examples_and_older_events_never_win(tmp_path):
    db = _db(tmp_path)
    urls = _seed(db)
    new = fb.make_event(urls[0], 1, "Title 0", "arxiv_ai", "Summary 0", "Must Read")
    assert db.record_feedback(new)
    old = dict(new, rating=-1, at="2000-01-01T00:00:00+00:00")
    assert not db.record_feedback(old)
    assert db.get_feedback_map() == {urls[0]: 1}
    db.record_feedback(fb.make_event(urls[1], -1, "Title 1", "arxiv_ai", "Summary 1", "Must Read"))
    examples = db.get_feedback_examples(5)
    assert [e["title"] for e in examples["up"]] == ["Title 0"]
    assert [e["title"] for e in examples["down"]] == ["Title 1"]
    assert db.get_feedback_counts() == {"up": 1, "down": 1}


def test_clearing_a_rating_removes_it_from_the_map(tmp_path):
    db = _db(tmp_path)
    urls = _seed(db)
    db.record_feedback(fb.make_event(urls[0], 1, "T", "s", "x", "Must Read"))
    db.record_feedback(fb.make_event(urls[0], 0, "T", "s", "x", "Must Read"))
    assert db.get_feedback_map() == {}


def test_a_new_database_replays_the_durable_log(tmp_path, monkeypatch):
    log = tmp_path / "f.jsonl"
    monkeypatch.setattr(settings, "FEEDBACK_FILE", log)
    fb.append_event(fb.make_event("https://e.com/9", 1, "Nine", "s", "sum", "Must Read"), log)
    db = DigestDatabase(tmp_path / "fresh.db")  # auto_hydrate on
    assert db.get_feedback_map() == {"https://e.com/9": 1}


def test_prompt_carries_profile_avoid_list_and_the_readers_verdicts(monkeypatch):
    monkeypatch.setattr(settings, "USER_AVOID", ["Crypto hype"])
    provider = lambda: {
        "up": [{"title": "Liked thing", "source": "s", "summary": "good"}],
        "down": [{"title": "Disliked thing", "source": "s", "summary": "bad"}],
    }
    prompt = ProcessorAgent(api_key="k", feedback_provider=provider)._build_system_prompt()
    assert "Crypto hype" in prompt
    assert "USEFUL" in prompt and "Liked thing" in prompt
    assert "NOT USEFUL" in prompt and "Disliked thing" in prompt


def test_prompt_is_clean_with_no_feedback_and_survives_a_broken_provider():
    clean = ProcessorAgent(api_key="k")._build_system_prompt()
    assert "READER FEEDBACK" not in clean

    def boom():
        raise RuntimeError("store down")

    assert "READER FEEDBACK" not in ProcessorAgent(api_key="k", feedback_provider=boom)._build_system_prompt()


def test_email_brief_has_signed_links_only_when_configured(secret):
    digest = {"date": "2026-10-23", "items": [{"title": "T", "url": "https://e.com/1", "source": "s",
                                               "category": "Must Read", "why_it_matters": "w"}]}
    brief = delivery.build_brief(digest, top_n=3, feed_url="https://feed.example/")
    assert "feedback?u=" in brief["html"] and "r=up" in brief["text"] and "r=down" in brief["text"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = _db(tmp_path)
    urls = _seed(db)
    monkeypatch.setattr(api, "db", db)
    monkeypatch.setattr(settings, "FEEDBACK_FILE", tmp_path / "f.jsonl")
    monkeypatch.setattr(settings, "FEEDBACK_SECRET", "s3cret")
    monkeypatch.setattr(settings, "FEEDBACK_GITHUB_TOKEN", "")
    monkeypatch.setattr(api.quota_manager, "api_key", None)
    api.limiter.reset()
    return TestClient(api.app), db, urls


def test_api_rates_an_item_and_reports_that_it_is_not_persisted_without_a_token(client):
    c, db, urls = client
    res = c.post("/api/feedback", json={"url": urls[0], "rating": 1})
    assert res.status_code == 200 and res.json()["persisted"] is False
    assert c.get("/api/feedback").json()["ratings"] == {urls[0]: 1}
    assert len(fb.read_events()) == 1
    again = c.post("/api/feedback", json={"url": urls[0], "rating": 1}).json()
    assert again["changed"] is False and len(fb.read_events()) == 1  # no duplicate log line


def test_api_rejects_unknown_items_bad_ratings_and_missing_keys(client, monkeypatch):
    c, db, urls = client
    assert c.post("/api/feedback", json={"url": "https://nope.example/x", "rating": 1}).status_code == 404
    assert c.post("/api/feedback", json={"url": urls[0], "rating": 5}).status_code == 422
    monkeypatch.setattr(api.quota_manager, "api_key", "k3y")
    assert c.post("/api/feedback", json={"url": urls[0], "rating": 1}).status_code == 401
    ok = c.post("/api/feedback", json={"url": urls[0], "rating": 1}, headers={"X-API-Key": "k3y"})
    assert ok.status_code == 200


def test_signed_link_flow_confirms_before_it_votes(client):
    c, db, urls = client
    h = DigestDatabase.hash_url(urls[1])
    sig = fb.sign(h, "down")
    page = c.get(f"/feedback?u={h}&r=down&sig={sig}")
    assert page.status_code == 200 and "Title 1" in page.text
    assert db.get_feedback_map() == {}  # opening the link alone must not vote
    assert c.post("/api/feedback/signed", json={"u": h, "r": "down", "sig": sig}).status_code == 200
    assert db.get_feedback_map() == {urls[1]: -1}
    assert c.post("/api/feedback/signed", json={"u": h, "r": "up", "sig": sig}).status_code == 403
    assert c.get(f"/feedback?u={h}&r=down&sig=bad").status_code == 403


def test_github_push_appends_to_the_feedback_branch_and_retries_a_conflict(monkeypatch):
    monkeypatch.setattr(settings, "FEEDBACK_GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    existing = base64.b64encode(b'{"url": "old"}\n').decode()
    puts = []

    class Resp:
        def __init__(self, code, data=None):
            self.status_code, self._data = code, data or {}

        def json(self):
            return self._data

    def fake_get(url, **kw):
        return Resp(200, {"content": existing, "sha": "abc"})

    def fake_put(url, json=None, **kw):
        puts.append(json)
        return Resp(409 if len(puts) == 1 else 200)

    monkeypatch.setattr(fb.requests, "get", fake_get)
    monkeypatch.setattr(fb.requests, "put", fake_put)
    event = fb.make_event("https://e.com/1", 1, "T", "s", "x", "Must Read")
    assert fb.push_event(event) is True
    assert len(puts) == 2 and puts[0]["branch"] == "feedback" and puts[0]["sha"] == "abc"
    body = base64.b64decode(puts[1]["content"]).decode()
    assert body.startswith('{"url": "old"}\n') and "https://e.com/1" in body


def test_github_push_is_off_without_a_token(monkeypatch):
    monkeypatch.setattr(settings, "FEEDBACK_GITHUB_TOKEN", "")
    assert fb.push_event(fb.make_event("u", 1, "T", "s", "x", "c")) is False

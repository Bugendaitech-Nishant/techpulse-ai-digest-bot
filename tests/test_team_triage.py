"""Tests for team triage, archive search and the standup brief."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from config.settings import settings
from src import triage
from src.models import DigestItem, TechDigest
from src.storage.database import DigestDatabase


def _item(n: int, step: str, category: str = "Must Read", topics=None, title=None) -> DigestItem:
    return DigestItem(
        title=title or f"Item {n}", url=f"https://example.com/{n}", source="hacker_news", category=category,
        summary=f"Summary {n} about litellm", why_it_matters="why", next_step=step,
        next_step_detail=f"do thing {n}", topics=topics or ["python"], tags=["tag"],
    )


@pytest.fixture
def db(tmp_path):
    database = DigestDatabase(tmp_path / "t.db", auto_hydrate=False)
    database.record_digest(TechDigest(date="2026-11-03", items=[_item(1, "Patch", topics=["security"])], total_harvested=1))
    database.record_digest(TechDigest(
        date="2026-11-04",
        items=[_item(2, "Try"), _item(3, "Read"), _item(4, "Ignore", "Skip"), _item(5, "Evaluate", title="Rust 100% fast_path")],
        total_harvested=4,
    ))
    return database


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "db", db)
    monkeypatch.setattr(settings, "TRIAGE_FILE", tmp_path / "triage.jsonl")
    monkeypatch.setattr(settings, "FEEDBACK_GITHUB_TOKEN", None)
    return TestClient(api.app)


def test_taking_an_item_needs_a_name_and_is_shared(client):
    url = "https://example.com/2"
    assert client.post("/api/triage", json={"url": url, "status": "doing"}).status_code == 422
    res = client.post("/api/triage", json={"url": url, "status": "doing", "owner": "  Priya  K ", "note": "on it"})
    assert res.status_code == 200 and res.json()["changed"] is True
    state = client.get("/api/triage").json()["items"][url]
    assert (state["status"], state["owner"], state["note"]) == ("doing", "Priya K", "on it")


def test_repeating_the_same_state_is_not_logged_twice(client, tmp_path):
    body = {"url": "https://example.com/2", "status": "done", "owner": "Sam"}
    client.post("/api/triage", json=body)
    assert client.post("/api/triage", json=body).json()["changed"] is False
    assert len((tmp_path / "triage.jsonl").read_text().splitlines()) == 1


def test_reopen_clears_the_item_and_unknown_items_are_refused(client):
    url = "https://example.com/2"
    client.post("/api/triage", json={"url": url, "status": "dismissed"})
    client.post("/api/triage", json={"url": url, "status": "open"})
    assert url not in client.get("/api/triage").json()["items"]
    assert client.post("/api/triage", json={"url": "https://nope.example", "status": "done"}).status_code == 404
    assert client.post("/api/triage", json={"url": url, "status": "bogus"}).status_code == 422


def test_write_needs_the_key_when_one_is_configured(client, monkeypatch):
    monkeypatch.setattr(api.quota_manager, "api_key", "k")
    body = {"url": "https://example.com/2", "status": "done"}
    assert client.post("/api/triage", json=body).status_code == 401
    assert client.post("/api/triage", json=body, headers={"X-API-Key": "k"}).status_code == 200


def test_log_is_replayed_after_a_restart_and_older_events_lose(tmp_path, db):
    log = tmp_path / "log.jsonl"
    old = triage.make_event("https://example.com/2", "done", "A", "", "t", "s", "Try")
    new = {**old, "status": "doing", "owner": "B", "at": "2999-01-01T00:00:00+00:00"}
    for event in (new, old):  # arrives out of order
        triage.append_event(event, log)
    fresh = DigestDatabase(tmp_path / "fresh.db", auto_hydrate=False)
    fresh.load_triage_events(triage.read_events(log))
    assert fresh.get_triage_map()["https://example.com/2"]["status"] == "doing"


def test_search_spans_days_hides_skips_and_treats_wildcards_literally(db):
    assert {i["url"] for i in db.search_items("litellm")} == {f"https://example.com/{n}" for n in (1, 2, 3, 5)}
    assert [i["date"] for i in db.search_items("litellm")][0] == "2026-11-04"
    assert [i["url"] for i in db.search_items("", topic="security")] == ["https://example.com/1"]
    assert [i["url"] for i in db.search_items("", step="Evaluate")] == ["https://example.com/5"]
    assert [i["url"] for i in db.search_items("100% fast_path")] == ["https://example.com/5"]
    assert [i["url"] for i in db.search_items("%")] == ["https://example.com/5"]  # a literal %, not a wildcard
    assert db.search_items("summary 3 litellm")[0]["url"] == "https://example.com/3"


def test_search_endpoint(client):
    data = client.get("/api/search", params={"q": "litellm", "step": "Try"}).json()
    assert data["count"] == 1 and data["items"][0]["next_step"] == "Try"


def test_brief_shows_open_work_and_progress_and_leaves_out_finished_work(client):
    client.post("/api/triage", json={"url": "https://example.com/1", "status": "doing", "owner": "Priya"})
    text = client.get("/api/brief", params={"date": "2026-11-03"}).json()["markdown"]
    assert "## In progress (1)" in text and "[Priya]" in text
    client.post("/api/triage", json={"url": "https://example.com/1", "status": "done"})
    text = client.get("/api/brief", params={"date": "2026-11-03"}).json()["markdown"]
    assert "Item 1" not in text  # finished work is not repeated
    assert "Item 4" not in client.get("/api/brief").json()["markdown"]  # skips never appear


def test_brief_for_an_idle_day_says_so_and_unknown_date_is_404(client, db):
    quiet = _item(9, "Read", "Inspiration").model_copy(update={"summary": "A paper about protein folding"})
    db.record_digest(TechDigest(date="2026-11-05", items=[quiet], total_harvested=1))
    assert "Nothing needs the team today." in client.get("/api/brief", params={"date": "2026-11-05"}).json()["markdown"]
    assert client.get("/api/brief", params={"date": "1999-01-01"}).status_code == 404

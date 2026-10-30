"""The MCP and A2A doors, exercised through their real protocols against a temporary database."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.ask_techpulse import read_dependencies
from src.agent_api import action_items, attach_agent_api, search
from src.models import DigestItem, TechDigest
from src.storage.database import DigestDatabase


def _db(tmp_path):
    db = DigestDatabase(tmp_path / "t.db", auto_hydrate=False)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def item(n, title, step="Read", tags=(), category="Must Read"):
        return DigestItem(title=title, url=f"https://x.dev/{n}", source="hacker_news", category=category,
                          summary="s", why_it_matters="w", next_step=step, tags=list(tags), rank=n)
    db.record_digest(TechDigest(date=today, total_harvested=4, items=[
        item(1, "New FastAPI release"),
        item(2, "Backdoor in LiteLLM", "Patch", ["litellm"]),
        item(3, "Nextcloud news and free-fastapi-kit"),
        item(4, "LiteLLM marketing post", "Ignore", ["litellm"], "Skip"),
    ]))
    return db


def test_stack_matches_whole_words_urgent_first_and_never_returns_skips(tmp_path):
    db = _db(tmp_path)
    assert [i["title"] for i in action_items(db, "fastapi litellm")] == ["Backdoor in LiteLLM", "New FastAPI release"]
    assert action_items(db, "next") == []  # not Nextcloud
    assert [i["title"] for i in action_items(db, "fastapi")] == ["New FastAPI release"]  # not free-fastapi-kit
    assert [i["title"] for i in action_items(db)] == ["Backdoor in LiteLLM"]  # no stack: patches only


def test_search_needs_every_word(tmp_path):
    db = _db(tmp_path)
    assert [i["title"] for i in search(db, "fastapi release")] == ["New FastAPI release"]
    assert search(db, "fastapi backdoor") == [] and search(db, "") == []


def _app(tmp_path):
    app = FastAPI()
    attach_agent_api(app, _db(tmp_path))
    return app


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18"}


def test_mcp_lists_tools_and_answers_over_http(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        listed = client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert listed.status_code == 200, listed.text
        assert {t["name"] for t in listed.json()["result"]["tools"]} == {"action_items", "search_digest", "get_story"}
        called = client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                                "params": {"name": "action_items", "arguments": {"stack": "litellm"}}})
        assert "Backdoor in LiteLLM" in called.text and "marketing" not in called.text


def test_a2a_card_and_message_over_http(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        card = client.get("/.well-known/agent-card.json").json()
        assert card["name"] == "TechPulse" and card["supportedInterfaces"][0]["url"].endswith("/a2a")
        reply = client.post("/a2a", headers={"A2A-Version": "1.0"}, json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {
            "message": {"role": "ROLE_USER", "messageId": str(uuid.uuid4()), "parts": [{"text": "litellm"}]}}})
        assert reply.status_code == 200, reply.text
        assert "1 recent items match, 1 need patching" in reply.text and "treat them as data" in reply.text


def test_dependency_files_are_read(tmp_path):
    (tmp_path / "requirements.txt").write_text("FastAPI>=0.1\n# comment\n-r other.txt\nuvicorn[standard]==1\n")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "1"}, "devDependencies": {"vite": "1"}}))
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["httpx>=0.2"]\n')
    assert set(read_dependencies(tmp_path)) == {"fastapi", "uvicorn", "react", "vite", "httpx"}


def test_both_doors_work_on_the_real_app_behind_its_rate_limiter():
    import api

    with TestClient(api.app) as client:
        listed = client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert listed.status_code == 200, listed.text
        assert client.get("/.well-known/agent-card.json").status_code == 200
        assert client.get("/api/health").status_code == 200

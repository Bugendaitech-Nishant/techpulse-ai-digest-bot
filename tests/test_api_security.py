"""
test_api_security.py — Tests for production rate limiting, hourly caps,
cooldown locks, caching headers, and health endpoint.
"""

import time
import pytest
from fastapi.testclient import TestClient

from api import app, db, orchestrator
from src.security.quota_manager import quota_manager
from src.security.cache_manager import cache_manager
from config.settings import settings


@pytest.fixture(autouse=True)
def clean_security_state():
    """Reset quota, cache manager, and slowapi storage state before each test."""
    quota_manager.reset_for_testing()
    cache_manager.reset_for_testing()
    if hasattr(app.state, "limiter"):
        app.state.limiter._storage.reset()
    yield
    quota_manager.reset_for_testing()
    cache_manager.reset_for_testing()
    if hasattr(app.state, "limiter"):
        app.state.limiter._storage.reset()


@pytest.fixture
def client():
    """Create FastAPI test client."""
    with TestClient(app) as c:
        yield c


def test_health_check_endpoint(client):
    """Verify /api/health returns 200 with DB status, Groq config, and quota metrics."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] in ("healthy", "degraded")
    assert data["service"] == "techpulse-ai-digest-bot"
    assert "version" in data
    assert "uptime_seconds" in data
    assert "database" in data
    assert data["database"]["connected"] is True
    assert "quota" in data
    assert data["quota"]["hourly_harvests_max"] == settings.MAX_HARVESTS_PER_HOUR
    assert "cache" in data


def test_caching_headers_and_invalidation(client):
    """Verify cache headers (MISS then HIT) and cache invalidation on new harvest."""
    # First request -> cache MISS
    res1 = client.get("/api/stats")
    assert res1.status_code == 200
    assert res1.headers.get("X-Cache") == "MISS"
    assert "public, max-age=" in res1.headers.get("Cache-Control", "")

    # Second immediate request -> cache HIT
    res2 = client.get("/api/stats")
    assert res2.status_code == 200
    assert res2.headers.get("X-Cache") == "HIT"

    # Invalidate cache
    cache_manager.invalidate()

    # Third request -> cache MISS again
    res3 = client.get("/api/stats")
    assert res3.status_code == 200
    assert res3.headers.get("X-Cache") == "MISS"


def test_harvest_cooldown_lock(client, monkeypatch):
    """Verify mandatory cooldown rejects subsequent harvests within cooldown period with 429."""
    # Mock orchestrator.run to be instantaneous
    monkeypatch.setattr(orchestrator, "run", lambda dry_run=False: {"success": True, "duration_seconds": 0.1})

    # First harvest should succeed
    res1 = client.post("/api/harvest")
    assert res1.status_code == 200
    assert res1.json()["success"] is True

    # Immediate second harvest should be rejected by cooldown lock (429)
    res2 = client.post("/api/harvest")
    assert res2.status_code == 429
    data2 = res2.json()
    assert data2["success"] is False
    assert "cooldown in effect" in data2["error"].lower()
    assert data2["quota"]["cooldown_active"] is True
    assert data2["quota"]["cooldown_remaining_seconds"] > 0


def test_harvest_hourly_cap_enforcement(client, monkeypatch):
    """Verify sliding-window hourly budget cap rejects executions exceeding limit."""
    monkeypatch.setattr(orchestrator, "run", lambda dry_run=False: {"success": True, "duration_seconds": 0.1})

    # Configure a small hourly cap of 2 and 0 cooldown for test
    quota_manager.max_harvests_per_hour = 2
    quota_manager.cooldown_seconds = 0

    # Run 1
    res1 = client.post("/api/harvest")
    assert res1.status_code == 200

    # Run 2
    res2 = client.post("/api/harvest")
    assert res2.status_code == 200

    # Run 3 -> Hourly cap reached!
    res3 = client.post("/api/harvest")
    assert res3.status_code == 429
    data3 = res3.json()
    assert "hourly harvest limit" in data3["error"].lower()
    assert data3["quota"]["hourly_harvests_remaining"] == 0


def test_harvest_concurrency_lock():
    """Verify quota_manager rejects parallel runs with 409 Conflict."""
    quota_manager.start_harvest()
    allowed, message, status, meta = quota_manager.check_harvest_allowed()
    assert allowed is False
    assert status == 409
    assert "currently active" in message.lower()
    quota_manager.finish_harvest(success=True)


def test_harvest_api_key_auth(client, monkeypatch):
    """Verify API key authentication when configured."""
    quota_manager.api_key = "secret_agent_key_42"
    quota_manager.cooldown_seconds = 0

    # Request without key -> 401 Unauthorized
    res_no_key = client.post("/api/harvest")
    assert res_no_key.status_code == 401
    assert "Unauthorized" in res_no_key.json()["error"]

    # Request with wrong key -> 401 Unauthorized
    res_wrong_key = client.post("/api/harvest", headers={"X-API-Key": "wrong"})
    assert res_wrong_key.status_code == 401

    # Request with valid key -> 200 OK
    monkeypatch.setattr(orchestrator, "run", lambda dry_run=False: {"success": True, "duration_seconds": 0.1})
    res_valid = client.post("/api/harvest", headers={"X-API-Key": "secret_agent_key_42"})
    assert res_valid.status_code == 200


def test_background_harvest_submission(client, monkeypatch):
    """Verify background harvest returns 202 Accepted immediately."""
    quota_manager.cooldown_seconds = 0
    monkeypatch.setattr(orchestrator, "run", lambda dry_run=False: {"success": True, "duration_seconds": 0.1})

    res = client.post("/api/harvest?background=true")
    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "accepted"
    assert "background" in data["message"].lower()


def test_dashboard_and_curated_digests_endpoints(client):
    """Verify both / and /curated-digests return status 200 with HTML content."""
    res_home = client.get("/")
    assert res_home.status_code == 200
    assert "text/html" in res_home.headers.get("content-type", "")
    assert "TechPulse" in res_home.text

    res_archive = client.get("/curated-digests")
    assert res_archive.status_code == 200
    assert "text/html" in res_archive.headers.get("content-type", "")
    assert "Curated" in res_archive.text or "Digest" in res_archive.text

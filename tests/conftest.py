"""Shared fixtures: keep tests independent of a developer's local .env and real data files."""

import pytest


@pytest.fixture(autouse=True)
def _no_local_access_key(monkeypatch):
    """A HARVEST_API_KEY in .env must not turn open-access tests into 401s.

    The setting is cleared first because `quota_manager.reset_for_testing()` re-reads it.
    """
    from config.settings import settings
    from src.security.quota_manager import quota_manager

    monkeypatch.setattr(settings, "HARVEST_API_KEY", None)
    monkeypatch.setattr(quota_manager, "api_key", None)


@pytest.fixture(autouse=True)
def _isolated_run_log(tmp_path, monkeypatch):
    """Pipeline tests must not append to the real digests/runs.jsonl."""
    from config.settings import settings

    monkeypatch.setattr(settings, "RUNS_FILE", tmp_path / "runs.jsonl")

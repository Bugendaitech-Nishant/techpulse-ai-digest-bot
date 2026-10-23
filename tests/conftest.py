"""Shared fixtures: keep tests independent of a developer's local .env."""

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

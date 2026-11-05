"""
discover.py: live search of GitHub for a use case, beyond what the digests happened to cover.

The archive only knows what the day's feeds surfaced. When a project needs "a vector database for
multi-tenant RAG", the answer may never have trended, so Find also asks GitHub directly. Results are
ranked by GitHub's own best match, limited to maintained repositories, and cached so a team asking
the same question does not spend the shared unauthenticated rate limit (10 searches a minute).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from config.settings import settings
from src.security.cache_manager import cache_manager
from src.storage.database import DigestDatabase

logger = logging.getLogger(__name__)

CACHE_SECONDS = 15 * 60
MIN_STARS = 20
MAX_AGE_DAYS = 365  # a repository untouched for a year is a risk, not a recommendation


def github_repos(query: str, limit: int = 8) -> Dict[str, Any]:
    """Maintained repositories matching a use case. Never raises: returns {'items': [], 'error': reason}."""
    terms = DigestDatabase._terms(query)
    if not terms:
        return {"items": [], "error": ""}
    key = "discover:" + " ".join(sorted(terms))  # word order must not defeat the cache
    cached = cache_manager.get(key)
    if cached is not None:
        return cached

    since = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).date().isoformat()
    headers = {"User-Agent": settings.USER_AGENT, "Accept": "application/vnd.github+json"}
    if settings.GITHUB_API_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_API_TOKEN}"
    try:
        res = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": f"{' '.join(terms)} in:name,description,readme,topics archived:false stars:>{MIN_STARS} pushed:>{since}",
                    "per_page": max(1, min(limit, 20))},
            headers=headers,
            timeout=10,
        )
    except requests.RequestException as error:
        logger.warning("GitHub discovery failed: %s", error)
        return {"items": [], "error": "GitHub could not be reached."}
    if res.status_code in (403, 429):
        return {"items": [], "error": "GitHub is rate limiting searches. Try again in a minute."}
    if res.status_code != 200:
        return {"items": [], "error": f"GitHub answered with HTTP {res.status_code}."}

    items: List[Dict[str, Any]] = [
        {
            "title": repo.get("full_name", ""),
            "url": repo.get("html_url", ""),
            "description": repo.get("description") or "",
            "stars": repo.get("stargazers_count", 0),
            "language": repo.get("language") or "",
            "pushed_at": repo.get("pushed_at") or "",
            "topics": (repo.get("topics") or [])[:5],
            "license": ((repo.get("license") or {}).get("spdx_id") or ""),
        }
        for repo in res.json().get("items", [])
        if repo.get("html_url")
    ]
    result = {"items": items, "error": ""}
    cache_manager.set(key, result, ttl=CACHE_SECONDS)
    return result

"""
github_search.py — Discovers high-velocity AI & developer tooling repositories
via the GitHub Search API.
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import List

from src.models import RawItem
from src.collectors.base import BaseCollector
from config.settings import settings


class GitHubSearchCollector(BaseCollector):
    name = "github_search"

    def _fetch_items(self) -> List[RawItem]:
        items: List[RawItem] = []
        # Query active repos created or updated recently with significant stars
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        query = f"(topic:ai-agents OR topic:llm OR topic:developer-tools) pushed:>{week_ago} stars:>50"
        api_url = "https://api.github.com/search/repositories"

        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": settings.LIMIT_GITHUB_SEARCH,
        }

        resp = requests.get(
            api_url,
            params=params,
            headers={
                "User-Agent": settings.USER_AGENT,
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=self.timeout,
        )

        if resp.status_code != 200:
            return items

        data = resp.json()
        for repo in data.get("items", []):
            items.append(RawItem(
                title=repo.get("full_name", ""),
                url=repo.get("html_url", ""),
                description=repo.get("description") or "",
                source=self.name,
                score=repo.get("stargazers_count", 0),
                language=repo.get("language") or "Python",
                published_at=repo.get("created_at"),
                extra_metadata={
                    "forks": repo.get("forks_count", 0),
                    "topics": repo.get("topics", []),
                },
            ))

        return items

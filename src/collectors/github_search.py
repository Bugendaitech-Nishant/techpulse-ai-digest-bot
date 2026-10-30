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
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        headers = {"User-Agent": settings.USER_AGENT, "Accept": "application/vnd.github.v3+json"}
        if settings.GITHUB_API_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_API_TOKEN}"

        # GitHub's search treats "(topic:a OR topic:b)" as matching nothing, so ask once per topic.
        repos: dict = {}
        for topic in ("ai-agents", "llm", "developer-tools"):
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"topic:{topic} pushed:>{week_ago} stars:>50",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": settings.LIMIT_GITHUB_SEARCH,
                },
                headers=headers,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"GitHub search returned HTTP {resp.status_code} for topic {topic}")
            for repo in resp.json().get("items", []):
                repos.setdefault(repo["html_url"], repo)

        top = sorted(repos.values(), key=lambda r: r.get("stargazers_count", 0), reverse=True)
        return [
            RawItem(
                title=repo.get("full_name", ""),
                url=repo.get("html_url", ""),
                description=repo.get("description") or "",
                source=self.name,
                score=repo.get("stargazers_count", 0),
                language=repo.get("language") or "Python",
                published_at=repo.get("pushed_at") or "",  # last push: created_at can be years old
                extra_metadata={"forks": repo.get("forks_count", 0), "topics": repo.get("topics", [])},
            )
            for repo in top[: settings.LIMIT_GITHUB_SEARCH]
        ]

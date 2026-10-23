"""
devto.py — Ingests top engineering articles from Dev.to across AI, Python, and open-source tags.
Extracts title, positive reactions, reading time, and tags.
"""

import re
import requests
from typing import List

from src.models import RawItem
from src.collectors.base import BaseCollector
from config.settings import settings


class DevToCollector(BaseCollector):
    name = "devto_articles"

    def _fetch_items(self) -> List[RawItem]:
        items: List[RawItem] = []
        tags = ["ai", "python", "opensource"]

        for tag in tags:
            api_url = "https://dev.to/api/articles"
            params = {
                "tag": tag,
                "top": 1,  # Top articles from the past day
                "per_page": settings.LIMIT_DEVTO // len(tags),
            }

            resp = requests.get(
                api_url,
                params=params,
                headers={"User-Agent": settings.USER_AGENT},
                timeout=self.timeout,
            )

            if resp.status_code != 200:
                continue

            articles = resp.json()
            if not isinstance(articles, list):
                continue

            for art in articles:
                title = art.get("title")
                url = art.get("url")
                if not title or not url:
                    continue
                # Reposts arrive as a bare "[Boost]" style tag with no real title.
                if re.fullmatch(r"\[[^\]]*\]", title.strip()):
                    continue

                reactions = art.get("positive_reactions_count", 0)
                reading_time = art.get("reading_time_minutes", 1)
                desc = f"{art.get('description', '')} ({reading_time} min read, {reactions} reactions)"

                items.append(RawItem(
                    title=title,
                    url=url,
                    description=desc,
                    source=self.name,
                    score=reactions,
                    language=tag.capitalize(),
                    published_at=art.get("published_at"),
                    extra_metadata={
                        "reading_time": reading_time,
                        "tags": art.get("tag_list", []),
                    },
                ))

        return items

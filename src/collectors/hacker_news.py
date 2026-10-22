"""
hacker_news.py — Ingests top trending tech discussions from Hacker News via the Algolia HN API.
Returns top front-page stories with points, comment counts, and direct links.
"""

import requests
from typing import List

from src.models import RawItem
from src.collectors.base import BaseCollector
from config.settings import settings


class HackerNewsCollector(BaseCollector):
    name = "hacker_news"

    def _fetch_items(self) -> List[RawItem]:
        items: List[RawItem] = []
        api_url = "https://hn.algolia.com/api/v1/search"
        params = {
            "tags": "front_page",
            "hitsPerPage": settings.LIMIT_HACKER_NEWS,
        }

        resp = requests.get(
            api_url,
            params=params,
            headers={"User-Agent": settings.USER_AGENT},
            timeout=self.timeout,
        )

        if resp.status_code != 200:
            return items

        hits = resp.json().get("hits", [])
        for hit in hits:
            title = hit.get("title")
            url = hit.get("url")
            story_id = hit.get("objectID")

            # Fallback to HN thread if no external URL
            if not url:
                url = f"https://news.ycombinator.com/item?id={story_id}"

            if not title:
                continue

            score = hit.get("points") or 0
            comments = hit.get("num_comments") or 0
            desc = f"HN discussion ({score} points, {comments} comments) by {hit.get('author', 'unknown')}"

            items.append(RawItem(
                title=title,
                url=url,
                description=desc,
                source=self.name,
                score=score,
                language="Tech/Discussion",
                published_at=hit.get("created_at"),
                extra_metadata={
                    "hn_id": story_id,
                    "num_comments": comments,
                    "author": hit.get("author"),
                },
            ))

        return items

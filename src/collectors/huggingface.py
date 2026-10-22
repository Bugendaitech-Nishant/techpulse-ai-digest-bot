"""
huggingface.py — Tracks top daily AI research papers from Hugging Face Daily Papers API.
Extracts title, abstract, upvotes, and paper URLs.
"""

import requests
from typing import List

from src.models import RawItem
from src.collectors.base import BaseCollector
from config.settings import settings


class HuggingFacePapersCollector(BaseCollector):
    name = "huggingface_papers"

    def _fetch_items(self) -> List[RawItem]:
        items: List[RawItem] = []
        api_url = "https://huggingface.co/api/daily_papers"

        resp = requests.get(
            api_url,
            headers={"User-Agent": settings.USER_AGENT},
            timeout=self.timeout,
        )

        if resp.status_code != 200:
            return items

        papers = resp.json()
        if not isinstance(papers, list):
            return items

        for entry in papers[:settings.LIMIT_HUGGINGFACE_PAPERS]:
            paper = entry.get("paper", {})
            paper_id = paper.get("id")
            title = paper.get("title")
            summary = paper.get("summary") or ""
            upvotes = entry.get("upvotes", 0)

            if not title or not paper_id:
                continue

            # Format clean short abstract
            cleaned_summary = " ".join(summary.split())
            if len(cleaned_summary) > 280:
                cleaned_summary = cleaned_summary[:277] + "..."

            url = f"https://huggingface.co/papers/{paper_id}"

            items.append(RawItem(
                title=f"HF Paper: {title}",
                url=url,
                description=f"{cleaned_summary} (Upvotes: {upvotes})",
                source=self.name,
                score=upvotes,
                language="AI Research",
                published_at=paper.get("publishedAt"),
                extra_metadata={
                    "arxiv_id": paper_id,
                    "upvotes": upvotes,
                },
            ))

        return items

"""
arxiv_ai.py — Fetches newly submitted preprints in Artificial Intelligence (cs.AI)
and Machine Learning (cs.LG) from the official ArXiv API.
"""

import requests
import xml.etree.ElementTree as ET
from typing import List

from src.models import RawItem
from src.collectors.base import BaseCollector
from config.settings import settings


class ArXivCollector(BaseCollector):
    name = "arxiv_ai"

    def _fetch_items(self) -> List[RawItem]:
        items: List[RawItem] = []
        api_url = "https://export.arxiv.org/api/query"
        params = {
            "search_query": "cat:cs.AI OR cat:cs.LG",
            "start": 0,
            "max_results": settings.LIMIT_ARXIV,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        resp = requests.get(
            api_url,
            params=params,
            headers={"User-Agent": settings.USER_AGENT},
            timeout=self.timeout,
        )

        resp.raise_for_status()  # let the collector retry and report the failure instead of looking empty

        # Parse Atom XML
        root = ET.fromstring(resp.text)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", namespace):
            title_el = entry.find("atom:title", namespace)
            summary_el = entry.find("atom:summary", namespace)
            id_el = entry.find("atom:id", namespace)
            published_el = entry.find("atom:published", namespace)

            if title_el is None or id_el is None:
                continue

            title = " ".join((title_el.text or "").split())
            url = (id_el.text or "").strip()
            # Convert abs url to arxiv link
            if url.startswith("http://"):
                url = "https://" + url[7:]

            summary = " ".join((summary_el.text or "").split()) if summary_el is not None else ""
            if len(summary) > 280:
                summary = summary[:277] + "..."

            published_at = published_el.text.strip() if published_el is not None else ""

            items.append(RawItem(
                title=f"ArXiv: {title}",
                url=url,
                description=summary,
                source=self.name,
                score=10,  # Base confidence score for peer preprint
                language="AI/ML Research",
                published_at=published_at,
            ))

        return items

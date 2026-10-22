"""
github_trending.py — Scrapes GitHub Trending repositories using BeautifulSoup.
Extracts repo names, descriptions, primary language, and star velocity.
"""

import requests
from bs4 import BeautifulSoup
from typing import List

from src.models import RawItem
from src.collectors.base import BaseCollector
from config.settings import settings


class GitHubTrendingCollector(BaseCollector):
    name = "github_trending"

    def _fetch_items(self) -> List[RawItem]:
        items: List[RawItem] = []
        languages = ["python", ""]  # Python-specific + all languages trending

        for lang in languages:
            url = f"https://github.com/trending/{lang}" if lang else "https://github.com/trending"
            resp = requests.get(
                url,
                headers={"User-Agent": settings.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("article.Box-row")

            for row in rows[:settings.LIMIT_GITHUB_TRENDING]:
                h2 = row.select_one("h2 a")
                if not h2:
                    continue

                repo_slug = h2.get("href", "").strip("/")
                if not repo_slug:
                    continue

                full_url = f"https://github.com/{repo_slug}"
                title = repo_slug.replace("/", " / ")

                desc_el = row.select_one("p")
                description = desc_el.get_text(strip=True) if desc_el else ""

                lang_el = row.select_one("span[itemprop='programmingLanguage']")
                detected_lang = lang_el.get_text(strip=True) if lang_el else (lang.capitalize() if lang else "General")

                stars_el = row.select_one("span.d-inline-block.float-sm-right")
                stars_text = stars_el.get_text(strip=True) if stars_el else "0"
                stars = int("".join(c for c in stars_text if c.isdigit()) or 0)

                items.append(RawItem(
                    title=title,
                    url=full_url,
                    description=description,
                    source=self.name,
                    score=stars,
                    language=detected_lang,
                    extra_metadata={"trending_lang": lang or "all"},
                ))

        return items

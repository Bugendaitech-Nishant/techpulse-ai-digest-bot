"""
feeds.py: official release notes and engineering blogs, read from their RSS or Atom feeds.

The trending sources lean towards AI repos and discussion. A team that also runs backend, frontend and
cloud needs the primary sources: vendor changelogs, framework blogs, standards bodies. Feeds are cheap,
public and need no login. The list is configuration (`settings.FEEDS`); one dead feed is logged and
skipped, and the source only counts as failed when every feed fails.

Feed text is untrusted: responses are size-capped, and any document declaring entities is refused,
because the standard-library XML parser expands them.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from config.settings import settings
from src.collectors.base import BaseCollector
from src.models import RawItem

logger = logging.getLogger(__name__)

MAX_BYTES = 3_000_000
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


def _text(html: str, limit: int = 600) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())[:limit]


def _when(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)  # RSS: "Tue, 04 Nov 2026 10:00:00 GMT"
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom: ISO 8601
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_feed(content: bytes) -> List[Dict[str, object]]:
    """Entries of an RSS 2.0 or Atom document: title, link, text, published (aware datetime or None)."""
    if b"<!ENTITY" in content:
        raise ValueError("feed declares XML entities")
    root = ElementTree.fromstring(content)
    entries: List[Dict[str, object]] = []
    for node in root.iter("item"):  # RSS
        entries.append({
            "title": (node.findtext("title") or "").strip(),
            "link": (node.findtext("link") or "").strip(),
            "text": _text(node.findtext(CONTENT) or node.findtext("description") or ""),
            "published": _when(node.findtext("pubDate") or node.findtext(DC_DATE) or ""),
        })
    for node in root.iter(f"{ATOM}entry"):  # Atom
        links = node.findall(f"{ATOM}link")
        href = next((l.get("href") for l in links if l.get("rel") in (None, "alternate") and l.get("href")), "")
        entries.append({
            "title": (node.findtext(f"{ATOM}title") or "").strip(),
            "link": (href or "").strip(),
            "text": _text(node.findtext(f"{ATOM}summary") or node.findtext(f"{ATOM}content") or ""),
            "published": _when(node.findtext(f"{ATOM}published") or node.findtext(f"{ATOM}updated") or ""),
        })
    return entries


class OfficialFeedsCollector(BaseCollector):
    name = "official_blogs"

    def _read(self, feed: Tuple[str, str]) -> Tuple[str, List[RawItem], Optional[str]]:
        label, url = feed
        try:
            res = requests.get(url, headers={"User-Agent": settings.USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
                               timeout=self.timeout)
            if res.status_code != 200:
                return label, [], f"HTTP {res.status_code}"
            if len(res.content) > MAX_BYTES:
                return label, [], "response too large"
            entries = parse_feed(res.content)
        except (requests.RequestException, ElementTree.ParseError, ValueError) as error:
            return label, [], str(error)[:120]

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.FEED_MAX_AGE_DAYS)
        fresh = [e for e in entries if len(str(e["title"])) >= 2 and str(e["link"]).startswith(("http://", "https://"))
                 and e["published"] and e["published"] >= cutoff]  # undated entries cannot be judged fresh
        fresh.sort(key=lambda e: e["published"], reverse=True)
        return label, [
            RawItem(title=str(e["title"]), url=str(e["link"]), description=f"{label}: {e['text']}", source=self.name,
                    score=0, published_at=e["published"].isoformat(), extra_metadata={"feed": label})
            for e in fresh[: settings.FEED_PER_FEED]
        ], None

    def _fetch_items(self) -> List[RawItem]:
        feeds = settings.FEEDS
        if not feeds:
            return []
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self._read, feeds))
        failed = [(label, why) for label, _, why in results if why]
        for label, why in failed:
            logger.warning("Feed [%s] skipped: %s", label, why)
        if len(failed) == len(feeds):
            raise RuntimeError(f"all {len(feeds)} feeds failed, e.g. {failed[0][0]}: {failed[0][1]}")
        items = [i for _, found, _ in results for i in found]
        return items[: settings.LIMIT_FEEDS]

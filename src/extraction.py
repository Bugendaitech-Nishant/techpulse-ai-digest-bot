"""extraction.py: read the article behind a link, so the curator summarises text instead of guessing from a title."""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.models import RawItem
from config.settings import settings

logger = logging.getLogger(__name__)

MAX_CHARS = 1500
THIN_DESCRIPTION = 120
# Sources whose own description already is the content (an abstract, a README blurb) or has no article.
SKIP_HOSTS = ("news.ycombinator.com", "github.com", "arxiv.org", "huggingface.co")


def needs_text(item: RawItem) -> bool:
    """A stub like 'HN discussion (12 points)' tells the model nothing; fetch the page it links to."""
    host = urlparse(item.url).netloc.lower()
    if any(host == h or host.endswith("." + h) for h in SKIP_HOSTS):
        return False
    return item.description.startswith("HN discussion") or len(item.description) < THIN_DESCRIPTION


def fetch_article_text(url: str, timeout: int = 8) -> str:
    """Readable text of the page, or '' on any failure. Best effort: a blocked site must not stop the run."""
    try:
        resp = requests.get(url, headers={"User-Agent": settings.USER_AGENT}, timeout=timeout)
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", "html"):
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup
        paragraphs = [p.get_text(" ", strip=True) for p in root.find_all("p")]
        text = " ".join(p for p in paragraphs if len(p) > 40)
        return text[:MAX_CHARS]
    except Exception as error:
        logger.debug(f"Could not read {url}: {error}")
        return ""


def enrich_with_text(items: List[RawItem], fetch=fetch_article_text, workers: int = 8) -> int:
    """Replace thin descriptions with the article's opening text, in place. Returns how many were enriched."""
    todo = [i for i in items if needs_text(i)]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        texts = list(pool.map(lambda i: fetch(i.url), todo))
    enriched = 0
    for item, text in zip(todo, texts):
        if len(text) > THIN_DESCRIPTION:
            item.description = text
            enriched += 1
    logger.info(f"Extraction: read the article text for {enriched} of {len(todo)} thin items")
    return enriched

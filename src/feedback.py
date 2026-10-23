"""
feedback.py: durable thumbs-up / thumbs-down ratings, signed email links and GitHub sync.

Ratings are an append-only JSONL log (one event per line, the latest event per URL wins).
The log is the durable record because the web host's disk is ephemeral and the daily
curation job runs on a fresh machine. Both read it: the job from a checkout of the
`feedback` branch, the server by fetching that branch's file at start-up. Writes from the
server are pushed to that branch through the GitHub Contents API when a token is set.
A dedicated branch keeps rating commits from triggering a redeploy of `main`.
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from config.settings import settings

logger = logging.getLogger(__name__)

RATINGS = {"up": 1, "down": -1}
FEEDBACK_BRANCH = "feedback"
LOG_PATH_IN_REPO = "data/feedback.jsonl"


# ─── Signed one-click links (used in the email) ─────────────────────────────

def sign(url_hash: str, rating: str) -> str:
    """HMAC for an email link. Empty when no secret is configured, which disables links."""
    if not settings.FEEDBACK_SECRET:
        return ""
    msg = f"{url_hash}:{rating}".encode()
    return hmac.new(settings.FEEDBACK_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]


def verify(url_hash: str, rating: str, signature: str) -> bool:
    expected = sign(url_hash, rating)
    return bool(expected) and rating in RATINGS and hmac.compare_digest(expected, signature or "")


def feedback_link(base_url: str, url_hash: str, rating: str) -> str:
    """Link to the confirmation page for one rating, or '' when signing is not configured."""
    signature = sign(url_hash, rating)
    if not signature or not base_url:
        return ""
    return f"{base_url.rstrip('/')}/feedback?u={url_hash}&r={rating}&sig={signature}"


# ─── Durable log ────────────────────────────────────────────────────────────

def make_event(url: str, rating: int, title: str, source: str, summary: str, category: str) -> Dict[str, Any]:
    return {
        "url": url,
        "rating": rating,
        "title": title,
        "source": source,
        "summary": summary[:400],
        "category": category,
        "at": datetime.now(timezone.utc).isoformat(),
    }


def append_event(event: Dict[str, Any], path: Optional[Path] = None) -> None:
    path = Path(path or settings.FEEDBACK_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = Path(path or settings.FEEDBACK_FILE)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping a corrupt feedback line.")
            continue
        if isinstance(event, dict) and event.get("url") and event.get("rating") in (-1, 0, 1):
            events.append(event)
    return events


def latest_by_url(events: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Latest event per URL, in log order; a rating of 0 means the reader cleared it."""
    latest: Dict[str, Dict[str, Any]] = {}
    for event in events:
        latest[event["url"]] = event
    return latest


# ─── GitHub sync (best effort, never blocks a rating from being saved locally) ─

def _api(path: str) -> str:
    return f"https://api.github.com/repos/{settings.GITHUB_REPO}/{path}"


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.FEEDBACK_GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": settings.USER_AGENT,
    }


def github_sync_enabled() -> bool:
    return bool(settings.FEEDBACK_GITHUB_TOKEN and settings.GITHUB_REPO)


def push_event(event: Dict[str, Any]) -> bool:
    """Append one event to the feedback branch. Returns True when it is stored on GitHub."""
    if not github_sync_enabled():
        return False
    line = json.dumps(event, ensure_ascii=False) + "\n"
    for attempt in (1, 2):  # a second try covers a concurrent write changing the file's sha
        try:
            current = requests.get(
                _api(f"contents/{LOG_PATH_IN_REPO}"), params={"ref": FEEDBACK_BRANCH}, headers=_headers(), timeout=10
            )
            body: Dict[str, Any] = {"message": "Record feedback", "branch": FEEDBACK_BRANCH}
            if current.status_code == 200:
                existing = base64.b64decode(current.json()["content"]).decode("utf-8")
                body["sha"] = current.json()["sha"]
            elif current.status_code == 404:
                existing = ""
            else:
                logger.warning(f"Feedback sync read failed with HTTP {current.status_code}.")
                return False
            body["content"] = base64.b64encode((existing + line).encode("utf-8")).decode("ascii")
            put = requests.put(_api(f"contents/{LOG_PATH_IN_REPO}"), json=body, headers=_headers(), timeout=10)
            if put.status_code in (200, 201):
                return True
            if put.status_code in (409, 422) and attempt == 1:
                continue
            logger.warning(f"Feedback sync write failed with HTTP {put.status_code}.")
            return False
        except requests.RequestException as error:
            logger.warning(f"Feedback sync failed: {error}")
            return False
    return False


def fetch_remote_events() -> List[Dict[str, Any]]:
    """Read the feedback log from the public feedback branch so a fresh server starts with it."""
    if not settings.GITHUB_REPO:
        return []
    url = f"https://raw.githubusercontent.com/{settings.GITHUB_REPO}/{FEEDBACK_BRANCH}/{LOG_PATH_IN_REPO}"
    try:
        res = requests.get(url, timeout=10, headers={"User-Agent": settings.USER_AGENT})
    except requests.RequestException as error:
        logger.warning(f"Could not fetch the feedback log: {error}")
        return []
    if res.status_code != 200:
        return []
    events = []
    for line in res.text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("url") and event.get("rating") in (-1, 0, 1):
            events.append(event)
    return events

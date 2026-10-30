"""stories.py: group items that report the same event, across days, so a story appears once with a timeline.

Titles alone are enough for one cheap model call: today's kept items plus the last week's, grouped by event.
Word overlap cannot do this ("PHP2Shell" and "HTTP2Shell" share no words), and embeddings are not worth
installing for a few hundred titles.
"""

import hashlib
import json
import logging
from typing import Any, Callable, Dict, List, Sequence

from src.models import DigestItem

logger = logging.getLogger(__name__)

PROMPT = """Group the items below that report the SAME event: one vulnerability, one release, one incident or one announcement.
Different projects or papers in the same field are NOT the same story. Related follow-ups to one event ARE.
Respond only with JSON: {"groups": [["t3", "r5"], ["t9", "t12", "r2"]]} listing only groups of two or more ids.
Each id appears at most once.

ITEMS:
"""


def story_id_for(urls: Sequence[str]) -> str:
    """Stable across runs: the id comes from the earliest member's URL."""
    return hashlib.sha1(sorted(urls)[0].encode("utf-8")).hexdigest()[:10]


def find_story_groups(
    today: Sequence[DigestItem],
    recent: Sequence[Dict[str, Any]],
    ask: Callable[[str], str],
) -> List[List[str]]:
    """Return groups of URLs (2+ each). `ask` sends a prompt to the model and returns its JSON text.

    `recent` rows carry title, url and date, oldest first. Any failure returns no groups: a missing
    cluster is harmless, a wrong one would hide news.
    """
    if not today:
        return []
    ids: Dict[str, str] = {}
    lines: List[str] = []
    for n, row in enumerate(recent):
        ids[f"r{n}"] = row["url"]
        lines.append(f"r{n} [{row.get('date', '')}] {row['title']}")
    for n, item in enumerate(today):
        ids[f"t{n}"] = item.url
        lines.append(f"t{n} [today] {item.title}")
    try:
        data = json.loads(ask(PROMPT + "\n".join(lines)))
        raw_groups = data.get("groups", [])
    except Exception as error:
        logger.warning(f"Story grouping failed, continuing without it: {error}")
        return []

    groups: List[List[str]] = []
    claimed: set = set()
    for group in raw_groups if isinstance(raw_groups, list) else []:
        urls = [ids[i] for i in group if isinstance(i, str) and i in ids and i not in claimed]
        claimed.update(i for i in group if isinstance(i, str))
        if len(set(urls)) >= 2:
            groups.append(list(dict.fromkeys(urls)))
    return groups

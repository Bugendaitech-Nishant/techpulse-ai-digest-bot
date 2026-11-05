"""
triage.py: who is handling which digest item, shared by the whole team.

Ratings say whether an item was good. Triage says what the team did about it: somebody
took it, finished it, or decided it does not apply. The record is an append-only JSONL log
(latest event per URL wins) using the same durability route as ratings: a local file plus
the `feedback` branch on GitHub when a token is set, so it survives the host's ephemeral disk.

Names are self-declared. There is no login, so this is a coordination aid for a team that
trusts each other, not an audit trail. Set HARVEST_API_KEY to keep strangers from writing.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings
from src import feedback

logger = logging.getLogger(__name__)

STATUSES = ("open", "doing", "done", "dismissed")
ACTION_STEPS = ("Patch", "Try", "Evaluate")  # next steps that ask somebody to do something
REPO_PATH = "data/triage.jsonl"
MAX_OWNER, MAX_NOTE = 40, 500


def make_event(url: str, status: str, owner: str, note: str, title: str, source: str, next_step: str) -> Dict[str, Any]:
    owner = " ".join(str(owner or "").split())[:MAX_OWNER]
    return {
        "url": url,
        "status": status,
        "owner": owner,
        "note": str(note or "").strip()[:MAX_NOTE],
        "title": title,
        "source": source,
        "next_step": next_step,
        "at": datetime.now(timezone.utc).isoformat(),
    }


def is_valid(event: Any) -> bool:
    return isinstance(event, dict) and bool(event.get("url")) and event.get("status") in STATUSES and bool(event.get("at"))


def append_event(event: Dict[str, Any], path: Optional[Path] = None) -> None:
    path = Path(path or settings.TRIAGE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = Path(path or settings.TRIAGE_FILE)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping a corrupt triage line.")
            continue
        if is_valid(event):
            events.append(event)
    return events


def push_event(event: Dict[str, Any]) -> bool:
    """Append to the log on the feedback branch. True when it is stored on GitHub."""
    return feedback.push_event(event, repo_path=REPO_PATH)


def fetch_remote_events() -> List[Dict[str, Any]]:
    return feedback.fetch_remote_events(repo_path=REPO_PATH, is_valid=is_valid)


# ─── Standup brief ──────────────────────────────────────────────────────────

def _line(item: Dict[str, Any], state: Optional[Dict[str, Any]]) -> str:
    action = (item.get("action") or "").strip()
    owner = f" [{state['owner']}]" if state and state.get("owner") else ""
    verb = f"**{item['next_step']}**{owner} " if item.get("actionable") else ""
    touches = f" (touches {', '.join(h for h in item['stack_hits'])})" if item.get("stack_hits") else ""
    return f"- {verb}[{item['title']}]({item['url']}){touches}" + (f": {action}" if action else "")


def build_brief(date: str, items: List[Dict[str, Any]], triage: Dict[str, Dict[str, Any]]) -> str:
    """Plain Markdown a team can paste into chat. `items` come from radar.annotate().

    Handled items are left out, so the brief shows only what is still open or under way.
    """
    status = lambda i: (triage.get(i["url"]) or {}).get("status", "open")  # noqa: E731
    live = [i for i in items if i["tier"] != "filtered" and status(i) not in ("done", "dismissed")]

    doing = [i for i in live if status(i) == "doing"]
    others = [i for i in live if status(i) != "doing"]
    alerts = [i for i in others if i["tier"] == "alert"]
    stack = [i for i in others if i["tier"] == "stack"]
    picks = [i for i in others if i["tier"] == "pick"]

    lines = [f"# TechPulse brief for {date}", ""]
    for heading, group in (("Act on", alerts), ("In progress", doing), ("Touches our stack", stack), ("Worth your time", picks)):
        if group:
            lines += [f"## {heading} ({len(group)})", *[_line(i, triage.get(i["url"])) for i in group], ""]
    if not (alerts or doing or stack or picks):
        lines += ["Nothing needs the team today.", ""]
    return "\n".join(lines).rstrip() + "\n"

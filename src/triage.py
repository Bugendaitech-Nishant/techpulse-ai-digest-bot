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
    detail = (item.get("next_step_detail") or "").strip()
    owner = f" [{state['owner']}]" if state and state.get("owner") else ""
    tail = f": {detail}" if detail else ""
    return f"- **{item['next_step']}**{owner} [{item['title']}]({item['url']}){tail}"


def build_brief(digest: Dict[str, Any], triage: Dict[str, Dict[str, Any]], reads: int = 5) -> str:
    """Plain Markdown a team can paste into chat: what needs doing, who has it, what to read."""
    items = [i for i in digest.get("items", []) if i.get("category") != "Skip"]
    status = lambda i: (triage.get(i["url"]) or {}).get("status", "open")  # noqa: E731

    todo = [i for i in items if i.get("next_step") in ACTION_STEPS and status(i) == "open"]
    doing = [i for i in items if status(i) == "doing"]
    read = [i for i in items if i.get("next_step") not in ACTION_STEPS and status(i) == "open"
            and i.get("category") == "Must Read"][:reads]

    order = {step: n for n, step in enumerate(ACTION_STEPS)}
    todo.sort(key=lambda i: order.get(i["next_step"], 9))

    lines = [f"# TechPulse brief for {digest.get('date', '')}", ""]
    if todo:
        lines += [f"## Needs someone ({len(todo)})", *[_line(i, triage.get(i["url"])) for i in todo], ""]
    if doing:
        lines += [f"## In progress ({len(doing)})", *[_line(i, triage.get(i["url"])) for i in doing], ""]
    if read:
        lines += ["## Worth reading", *[f"- [{i['title']}]({i['url']})" for i in read], ""]
    if not (todo or doing or read):
        lines += ["Nothing needs the team today.", ""]
    return "\n".join(lines).rstrip() + "\n"

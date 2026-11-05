"""
radar.py: sort a day's kept items into a briefing a team can read in a few minutes.

A team that spans backend, frontend, cloud and AI needs two things from a digest: the few
changes everybody should know about, and a way to see its own area without the rest. Each item
therefore gets a tier, one or more areas, and a kind:

  alert    on the optional watchlist (or a security advisory) and asking for action
  stack    on the watchlist, no action needed yet
  major    the biggest updates of the day across every area, capped so the briefing is finishable
  more     everything else the curator kept, grouped by area
  filtered the curator's skips, shown with the reason

The watchlist is optional: with no `tools` configured there are no alerts, and the briefing is
major updates plus areas. Only alerts and patches can become somebody's task. A "Try this" on a
trending repo is a suggestion, not work, so the briefing offers no "take it" button for it.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from config.settings import settings

MAJOR_SIZE = 5  # the biggest updates across all areas; watchlist alerts are never cut
# The curator tags each item with 1-3 topics from a fixed list; areas group those topics.
AREAS = {
    "GenAI & ML": {"agents", "llm-models", "local-llm", "inference", "rag", "evaluation", "fine-tuning", "multimodal", "ai-safety"},
    "Backend & data": {"python", "rust", "databases", "data-engineering"},
    "Frontend & mobile": {"javascript", "web", "mobile"},
    "Cloud & DevOps": {"cloud", "devops", "kubernetes", "observability"},
    "Security": {"security", "vulnerabilities", "supply-chain"},
    "Emerging": {"hardware", "robotics", "regulation", "startups", "research"},
}
GENERAL = "General"  # developer-tools, open-source, or no topic at all
KINDS = {
    "github_trending": "tool", "github_search": "tool",
    "arxiv_ai": "paper", "huggingface_papers": "paper",
    "hacker_news": "article", "devto_articles": "article",
    "security_advisories": "advisory",
}
SECURITY_TOPICS = {"security", "vulnerabilities", "supply-chain"}
ACTION_STEPS = {"Patch", "Evaluate"}
# Actions the curator writes when it has nothing specific to say. They are not work.
GENERIC_ACTION = re.compile(r"\b(clone the repo|git clone|pip install|npm i(nstall)?|run the (example|sample|demo|quickstart)|sample (query|plugin|script))\b", re.I)


@dataclass
class Stack:
    names: List[str] = field(default_factory=list)
    aliases: Dict[str, List[str]] = field(default_factory=dict)
    broad: set = field(default_factory=set)

    def __post_init__(self) -> None:
        self._patterns = {}
        for name in self.names:
            terms = {name.lower(), *(a.lower() for a in self.aliases.get(name, []))}
            alternation = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
            # Whole words only, so "go" is not found in "google" and "rust" not in "trust".
            self._patterns[name] = re.compile(rf"(?<![\w.-])(?:{alternation})(?![\w-])", re.I)

    def hits(self, item: Mapping[str, Any]) -> List[str]:
        text = " ".join([item.get("title", ""), item.get("summary", ""), " ".join(item.get("tags") or [])])
        return [name for name, pattern in self._patterns.items() if pattern.search(text)]


def load_stack() -> Stack:
    return Stack(list(settings.USER_TOOLS), dict(settings.STACK_ALIASES), {b.lower() for b in settings.STACK_BROAD})


def areas_of(item: Mapping[str, Any]) -> List[str]:
    topics = set(item.get("topics") or [])
    found = [name for name, members in AREAS.items() if topics & members]
    if item.get("source") == "security_advisories" and "Security" not in found:
        found.append("Security")
    return found or [GENERAL]


def kind_of(item: Mapping[str, Any]) -> str:
    return KINDS.get(item.get("source", ""), "article")


def is_generic_action(item: Mapping[str, Any]) -> bool:
    return bool(GENERIC_ACTION.search(item.get("next_step_detail") or ""))


def _tier(item: Mapping[str, Any], hits: List[str]) -> str:
    if item.get("category") == "Skip":
        return "filtered"
    secure = item.get("source") == "security_advisories" or bool(SECURITY_TOPICS & set(item.get("topics") or []))
    if item.get("source") == "security_advisories" or (hits and (secure or item.get("next_step") in ACTION_STEPS)):
        return "alert"
    if hits:
        return "stack"
    return "major" if item.get("category") == "Must Read" else "more"


def annotate(items: Sequence[Mapping[str, Any]], stack: Stack, size: int = MAJOR_SIZE) -> List[Dict[str, Any]]:
    """Every item with `stack_hits`, `tier`, `actionable` and `action`; the featured ones first, in order."""
    out: List[Dict[str, Any]] = []
    for item in items:
        everything = stack.hits(item)
        promoting = [h for h in everything if h.lower() not in stack.broad]
        tier = _tier(item, promoting)
        generic = is_generic_action(item)
        out.append({
            **item,
            "stack_hits": promoting,
            "broad_hits": [h for h in everything if h not in promoting],
            "tier": tier,
            "action": "" if generic or item.get("next_step") in ("Read", "Watch", "Ignore") else item.get("next_step_detail", ""),
            "areas": areas_of(item),
            "kind": kind_of(item),
            "actionable": tier == "alert" or (item.get("next_step") == "Patch" and tier != "filtered" and not generic),
        })

    rank = lambda i: -float(i.get("priority_score") or 0)  # noqa: E731
    majors = sorted((i for i in out if i["tier"] == "major"), key=rank)
    for overflow in majors[size:]:
        overflow["tier"] = "more"  # the biggest few only: a briefing nobody finishes is not a briefing

    order = {"alert": 0, "stack": 1, "major": 2, "more": 3, "filtered": 4}
    return sorted(out, key=lambda i: (order[i["tier"]], rank(i)))


def area_strip(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Kept items per area, in a fixed order, so each person can jump to their own."""
    counts: Dict[str, int] = {}
    for item in items:
        if item.get("tier") != "filtered":
            for area in item.get("areas", []):
                counts[area] = counts.get(area, 0) + 1
    names = [*AREAS, GENERAL]
    return [{"name": n, "count": counts[n]} for n in names if counts.get(n)]


def stack_strip(items: Iterable[Mapping[str, Any]], stack: Stack) -> List[Dict[str, Any]]:
    """How many kept items touch each tool today: the 'is anything about what we run?' glance."""
    counts = {name: 0 for name in stack.names}
    for item in items:
        if item.get("tier") == "filtered":
            continue
        for name in [*item.get("stack_hits", []), *item.get("broad_hits", [])]:
            counts[name] += 1
    return [{"name": n, "hits": counts[n], "broad": n.lower() in stack.broad} for n in stack.names]


def headline(items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    n = lambda tier: sum(1 for i in items if i["tier"] == tier)  # noqa: E731
    return {"alerts": n("alert"), "stack": n("stack"), "major": n("major"), "more": n("more"), "filtered": n("filtered")}

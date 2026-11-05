"""
radar.py: turn a day's kept items into a short briefing for a team that runs a known stack.

The question a digest must answer is "what does this change for us?". Most of what the sources
publish changes nothing for any given team, so the briefing sorts every item into a tier:

  alert    touches the stack and asks for action (a patch, an evaluation, a security issue)
  stack    touches the stack, no action needed yet
  pick     does not touch the stack but is the best reading of the day
  more     kept by the curator, left out of the briefing
  filtered the curator's skips, shown with the reason

Only alerts and patches can become somebody's task. A "Try this" on a trending repo
that the team does not use is a suggestion, not work, and the briefing says so by not offering a
"take it" button for it.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from config.settings import settings

BRIEF_SIZE = 7  # alerts + stack news + picks together; alerts are never cut
MIN_PICKS = 3
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
    return "pick" if item.get("category") == "Must Read" else "more"


def annotate(items: Sequence[Mapping[str, Any]], stack: Stack, size: int = BRIEF_SIZE) -> List[Dict[str, Any]]:
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
            "actionable": tier == "alert" or (item.get("next_step") == "Patch" and tier != "filtered" and not generic),
        })

    rank = lambda i: -float(i.get("priority_score") or 0)  # noqa: E731
    fixed = [i for i in out if i["tier"] in ("alert", "stack")]
    room = max(MIN_PICKS, size - len(fixed))
    picks = sorted((i for i in out if i["tier"] == "pick"), key=rank)
    for overflow in picks[room:]:
        overflow["tier"] = "more"  # the best few only: a briefing nobody finishes is not a briefing

    order = {"alert": 0, "stack": 1, "pick": 2, "more": 3, "filtered": 4}
    return sorted(out, key=lambda i: (order[i["tier"]], rank(i)))


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
    return {"alerts": n("alert"), "stack": n("stack"), "picks": n("pick"), "more": n("more"), "filtered": n("filtered")}

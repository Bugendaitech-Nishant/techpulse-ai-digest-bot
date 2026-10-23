"""Deterministic, source-aware ranking for curated digest items."""

import math
import re
from datetime import datetime, timezone
from typing import Dict, List, Sequence

from src.models import DigestItem, RawItem

RANKING_VERSION = "v1"
RANKING_WEIGHTS = {
    "relevance": 0.35,
    "impact": 0.25,
    "freshness": 0.15,
    "novelty": 0.15,
    "source_popularity": 0.10,
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _freshness(published_at: str, now: datetime) -> float:
    if not published_at:
        return 0.5
    value = published_at.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return 0.5
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600)
    return math.exp(-age_hours / (24.0 * 3.0))


def _source_percentiles(raw_items: Sequence[RawItem]) -> Dict[str, Dict[str, float]]:
    grouped: Dict[str, List[int]] = {}
    for item in raw_items:
        grouped.setdefault(item.source, []).append(item.score)
    result: Dict[str, Dict[str, float]] = {}
    for source, scores in grouped.items():
        ordered = sorted(scores)
        result[source] = {
            str(score): 0.0 if len(ordered) == 1 else ordered.index(score) / (len(ordered) - 1)
            for score in scores
        }
    return result


def rank_items(
    items: Sequence[DigestItem],
    raw_items: Sequence[RawItem],
    *,
    now: datetime | None = None,
) -> List[DigestItem]:
    """Rank items within category using normalized source and editorial signals."""
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    raw_by_url = {item.url: item for item in raw_items}
    percentiles = _source_percentiles(raw_items)
    selected_tokens: List[set[str]] = []
    ranked: List[DigestItem] = []

    category_weight = {"Must Read": 1.0, "Inspiration": 0.7, "Skip": 0.0}
    candidates = list(items)
    candidates.sort(key=lambda item: (category_weight[item.category], item.title.lower()), reverse=True)

    for item in candidates:
        raw = raw_by_url.get(item.url)
        source_popularity = percentiles.get(raw.source, {}).get(str(raw.score), 0.0) if raw else 0.0
        freshness = _freshness(raw.published_at, timestamp) if raw else 0.5
        text_tokens = _tokens(f"{item.title} {item.summary} {' '.join(item.tags)}")
        overlap = max(
            (len(text_tokens & previous) / max(1, len(text_tokens | previous)) for previous in selected_tokens),
            default=0.0,
        )
        novelty = 1.0 - overlap
        relevance = item.relevance_score or (1.0 if item.category == "Must Read" else 0.6 if item.category == "Inspiration" else 0.0)
        impact = item.impact_score or (1.0 if item.category == "Must Read" else 0.5 if item.category == "Inspiration" else 0.0)
        priority = 100.0 * sum((
            RANKING_WEIGHTS["relevance"] * relevance,
            RANKING_WEIGHTS["impact"] * impact,
            RANKING_WEIGHTS["freshness"] * freshness,
            RANKING_WEIGHTS["novelty"] * novelty,
            RANKING_WEIGHTS["source_popularity"] * source_popularity,
        ))
        ranked.append(item.model_copy(update={
            "freshness_score": round(freshness, 4),
            "novelty_score": round(novelty, 4),
            "priority_score": round(priority, 4),
            "confidence": round(max(item.confidence, (relevance + impact) / 2), 4),
        }))
        selected_tokens.append(text_tokens)

    ranked.sort(
        key=lambda item: (
            category_weight[item.category],
            item.priority_score,
            item.title.lower(),
            item.url,
        ),
        reverse=True,
    )
    return [item.model_copy(update={"rank": index}) for index, item in enumerate(ranked, 1)]

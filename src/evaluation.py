"""Dependency-free offline evaluation metrics for digest ranking experiments."""

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.models import DigestItem


@dataclass(frozen=True)
class RankingMetrics:
    """Metrics for one ranked list against human relevance judgements."""

    precision_at_k: float
    ndcg_at_k: float
    reciprocal_rank: float


def validate_label_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    min_items: int = 1,
    min_sources: int = 1,
    require_human: bool = False,
) -> None:
    """Reject incomplete or ambiguous fixtures before model comparison."""
    if min_items <= 0:
        raise ValueError("min_items must be greater than zero")
    if min_sources <= 0:
        raise ValueError("min_sources must be greater than zero")
    if len(entries) < min_items:
        raise ValueError(
            f"fixture contains {len(entries)} items; at least {min_items} are required"
        )

    urls: set[str] = set()
    sources: set[str] = set()
    for index, entry in enumerate(entries):
        url = entry.get("url")
        source = entry.get("source")
        label = entry.get("relevance")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"fixture entry {index} has no valid url")
        if url in urls:
            raise ValueError(f"fixture contains duplicate url: {url}")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"fixture entry {index} has no valid source")
        if (
            isinstance(label, bool)
            or not isinstance(label, (int, float))
            or not 0 <= float(label) <= 4
        ):
            raise ValueError(
                f"fixture entry {index} relevance must be a number from 0 to 4"
            )
        if require_human and entry.get("label_source") != "human":
            raise ValueError(
                f"fixture entry {index} is not human-labelled; "
                "promotion comparisons require label_source='human'"
            )
        urls.add(url)
        sources.add(source)

    if len(sources) < min_sources:
        raise ValueError(
            f"fixture contains {len(sources)} sources; at least {min_sources} are required"
        )


def precision_at_k(
    ranked_urls: Sequence[str],
    relevance: Mapping[str, float],
    k: int,
    *,
    relevant_threshold: float = 1.0,
) -> float:
    """Return the fraction of the first k results judged relevant."""
    if k <= 0:
        raise ValueError("k must be greater than zero")
    selected = ranked_urls[:k]
    if not selected:
        return 0.0
    relevant = sum(relevance.get(url, 0.0) >= relevant_threshold for url in selected)
    return relevant / len(selected)


def ndcg_at_k(
    ranked_urls: Sequence[str],
    relevance: Mapping[str, float],
    k: int,
) -> float:
    """Return normalized discounted cumulative gain for the first k results."""
    if k <= 0:
        raise ValueError("k must be greater than zero")
    actual = [relevance.get(url, 0.0) for url in ranked_urls[:k]]
    ideal = sorted(relevance.values(), reverse=True)[:k]

    def dcg(values: Sequence[float]) -> float:
        return sum(value / math.log2(index + 2) for index, value in enumerate(values))

    ideal_gain = dcg(ideal)
    return dcg(actual) / ideal_gain if ideal_gain else 0.0


def reciprocal_rank(
    ranked_urls: Sequence[str],
    relevance: Mapping[str, float],
    *,
    relevant_threshold: float = 1.0,
) -> float:
    """Return the reciprocal rank of the first relevant result."""
    for index, url in enumerate(ranked_urls, 1):
        if relevance.get(url, 0.0) >= relevant_threshold:
            return 1.0 / index
    return 0.0


def evaluate_ranked_items(
    ranked_items: Sequence[DigestItem],
    relevance: Mapping[str, float],
    k: int,
    *,
    relevant_threshold: float = 1.0,
) -> RankingMetrics:
    """Evaluate ranker output using human-labelled URL relevance scores."""
    urls = [item.url for item in ranked_items]
    return RankingMetrics(
        precision_at_k=precision_at_k(
            urls, relevance, k, relevant_threshold=relevant_threshold
        ),
        ndcg_at_k=ndcg_at_k(urls, relevance, k),
        reciprocal_rank=reciprocal_rank(
            urls, relevance, relevant_threshold=relevant_threshold
        ),
    )

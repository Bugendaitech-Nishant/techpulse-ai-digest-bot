import json
from pathlib import Path

import pytest

from src.evaluation import (
    evaluate_ranked_items,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
    validate_label_entries,
)
from src.models import DigestItem, RawItem
from src.ranking import rank_items


def _item(url: str) -> DigestItem:
    return DigestItem(
        title=url,
        url=url,
        source="test",
        category="Must Read",
        summary="Test item",
        why_it_matters="Test relevance",
    )


def test_ranking_metrics_reward_relevant_items_at_the_top():
    ranked = [_item("https://x/b"), _item("https://x/a"), _item("https://x/c")]
    relevance = {
        "https://x/a": 3,
        "https://x/b": 0,
        "https://x/c": 1,
    }

    metrics = evaluate_ranked_items(ranked, relevance, k=2)

    assert metrics.precision_at_k == 0.5
    assert 0 < metrics.ndcg_at_k < 1
    assert metrics.reciprocal_rank == 0.5


def test_metrics_validate_k_and_handle_no_relevant_items():
    with pytest.raises(ValueError):
        precision_at_k([], {}, 0)
    with pytest.raises(ValueError):
        ndcg_at_k([], {}, 0)
    assert ndcg_at_k(["https://x/a"], {"https://x/a": 0}, 1) == 0.0
    assert reciprocal_rank(["https://x/a"], {"https://x/a": 0}) == 0.0


def test_ndcg_is_one_for_ideal_order():
    relevance = {"https://x/a": 3, "https://x/b": 2, "https://x/c": 0}
    assert ndcg_at_k(["https://x/a", "https://x/b", "https://x/c"], relevance, 3) == 1.0


def test_label_validation_rejects_unlabelled_duplicate_and_small_fixtures():
    base = {"url": "https://x/a", "source": "github", "relevance": 3}
    with pytest.raises(ValueError, match="number from 0 to 4"):
        validate_label_entries([{**base, "relevance": None}])
    with pytest.raises(ValueError, match="duplicate url"):
        validate_label_entries([base, base])
    with pytest.raises(ValueError, match="at least 2"):
        validate_label_entries([base], min_items=2)


def test_label_validation_enforces_source_coverage():
    entry = {"url": "https://x/a", "source": "github", "relevance": 3}
    with pytest.raises(ValueError, match="at least 2"):
        validate_label_entries([entry], min_sources=2)


def test_promotion_validation_requires_human_provenance():
    entry = {
        "url": "https://x/a",
        "source": "github",
        "relevance": 3,
        "label_source": "assistant_provisional",
    }
    with pytest.raises(ValueError, match="not human-labelled"):
        validate_label_entries([entry], require_human=True)


def test_v1_ranker_meets_labelled_digest_baseline():
    fixture = Path(__file__).parent / "fixtures" / "ranking_labels.json"
    labels = json.loads(fixture.read_text(encoding="utf-8"))
    items = [
        DigestItem(
            title=entry["title"],
            url=entry["url"],
            source=entry["source"],
            category="Must Read" if entry["relevance"] >= 3 else "Inspiration",
            summary=entry["title"],
            why_it_matters="Labelled evaluation item.",
        )
        for entry in labels
    ]
    raw_items = [
        RawItem(
            title=entry["title"],
            url=entry["url"],
            source=entry["source"],
            score=entry["score"],
        )
        for entry in labels
    ]
    relevance = {entry["url"]: entry["relevance"] for entry in labels}

    ranked = rank_items(items, raw_items)
    metrics = evaluate_ranked_items(ranked, relevance, k=5, relevant_threshold=2)

    assert metrics.precision_at_k >= 0.6
    assert metrics.ndcg_at_k >= 0.8

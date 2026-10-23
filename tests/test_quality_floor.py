"""Offline quality floor: runs on every push without any network or model call.

The deterministic ranker is the production fallback and the metric code is what the weekly
model evaluation relies on, so both are pinned here. The numbers sit a little below what the
code scores today; a drop below them means a real regression, not noise.
"""

from pathlib import Path

from scripts.eval_curation import evaluate, ndcg
from scripts.evaluate_ranking import _load_fixture
from src.backends import DeterministicV1Backend
from src.evaluation import evaluate_ranked_items

FIXTURE = Path(__file__).parent / "fixtures" / "ranking_labels_human.json"


def test_deterministic_ranker_stays_above_its_measured_floor():
    items, raw, relevance = _load_fixture(FIXTURE, min_items=100, min_sources=4, require_human=True)
    ranked = DeterministicV1Backend().rank(items, raw)
    metrics = evaluate_ranked_items(ranked, relevance, 5)
    assert metrics.ndcg_at_k >= 0.15  # measured 0.215 with no label leakage
    assert ndcg(ranked, relevance, 108) >= 0.60  # measured 0.674


def test_every_labelled_item_survives_ranking():
    items, raw, relevance = _load_fixture(FIXTURE, min_items=100, min_sources=4, require_human=True)
    ranked = DeterministicV1Backend().rank(items, raw)
    assert {i.url for i in ranked} == set(relevance)


def test_evaluate_reports_coverage_and_precision_correctly():
    from src.models import DigestItem

    def item(n, category, why="specific reason"):
        return DigestItem(title=f"T{n}", url=f"u{n}", source="s", category=category, summary="s", why_it_matters=why)

    relevance = {"u1": 4, "u2": 1, "u3": 3, "u4": 0}
    items = [item(1, "Must Read"), item(2, "Must Read"), item(3, "Inspiration", "Not reviewed by the AI curator.")]
    m = evaluate(items, total=4, relevance=relevance)
    assert m["coverage"] == 0.75
    assert m["must_read_precision"] == 0.5  # u1 is relevant, u2 is not
    assert m["must_read_recall"] == 0.5  # u1 found, u3 missed from the two relevant items
    assert m["unreviewed_share"] == 0.333

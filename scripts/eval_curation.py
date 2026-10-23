"""Run the real curation pipeline on the labelled fixture and fail if quality drops.

This is the gate for prompt, profile and model changes. It calls the LLM (about 5 minutes,
a dozen requests), so it runs weekly and on demand in CI, not on every push.

Exit codes: 0 passed, 1 a threshold failed, 2 no GROQ_API_KEY configured.
"""

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings
from scripts.evaluate_ranking import _load_fixture
from src.agents.processor import ProcessorAgent
from src.models import DigestItem

DEFAULT_FIXTURE = Path("tests/fixtures/ranking_labels_human.json")


def ndcg(order: List[DigestItem], relevance: Dict[str, float], k: int) -> float:
    gain = lambda r: 2 ** r - 1
    dcg = sum(gain(relevance[i.url]) / math.log2(n + 2) for n, i in enumerate(order[:k]))
    ideal = sum(gain(r) / math.log2(n + 2) for n, r in enumerate(sorted(relevance.values(), reverse=True)[:k]))
    return dcg / ideal if ideal else 0.0


def evaluate(items: List[DigestItem], total: int, relevance: Dict[str, float]) -> Dict[str, float]:
    must = [i for i in items if i.category == "Must Read"]
    relevant_total = sum(1 for v in relevance.values() if v >= 3)
    hits = sum(1 for i in must if relevance[i.url] >= 3)
    unreviewed = sum(1 for i in items if i.why_it_matters.startswith("Not reviewed"))
    return {
        "items_in": total,
        "items_out": len(items),
        "coverage": round(len({i.url for i in items}) / total, 3),
        "unreviewed_share": round(unreviewed / max(len(items), 1), 3),
        "must_read_count": len(must),
        "must_read_precision": round(hits / max(len(must), 1), 3),
        "must_read_recall": round(hits / max(relevant_total, 1), 3),
        "base_rate": round(relevant_total / total, 3),
        "ndcg_at_10": round(ndcg(items, relevance, 10), 3),
        "ndcg_all": round(ndcg(items, relevance, total), 3),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--min-coverage", type=float, default=1.0)
    parser.add_argument("--max-unreviewed", type=float, default=0.0)
    parser.add_argument("--min-precision", type=float, default=0.55)
    parser.add_argument("--min-ndcg10", type=float, default=0.45)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    if not settings.GROQ_API_KEY:
        print("GROQ_API_KEY is not set; cannot evaluate the model.", file=sys.stderr)
        return 2

    _, raw, relevance = _load_fixture(args.fixture, min_items=100, min_sources=4, require_human=True)
    settings.LLM_MAX_ITEMS = len(raw)  # evaluate every labelled item, not a capped sample
    digest = ProcessorAgent().process(raw, "evaluation")
    metrics = evaluate(digest.items, len(raw), relevance)

    failures = []
    if metrics["coverage"] < args.min_coverage:
        failures.append(f"coverage {metrics['coverage']} < {args.min_coverage}")
    if metrics["unreviewed_share"] > args.max_unreviewed:
        failures.append(f"unreviewed share {metrics['unreviewed_share']} > {args.max_unreviewed}")
    if metrics["must_read_precision"] < args.min_precision:
        failures.append(f"Must Read precision {metrics['must_read_precision']} < {args.min_precision}")
    if metrics["ndcg_at_10"] < args.min_ndcg10:
        failures.append(f"NDCG@10 {metrics['ndcg_at_10']} < {args.min_ndcg10}")

    print(json.dumps({"metrics": metrics, "failures": failures, "passed": not failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

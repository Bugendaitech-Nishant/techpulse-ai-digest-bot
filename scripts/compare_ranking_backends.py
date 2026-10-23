"""Compare deterministic v1 and Laya on one identical labelled fixture."""

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_ranking import _build_backend, _load_fixture
from src.evaluation import evaluate_ranked_items


def _run_backend(
    name: str,
    items: list[Any],
    raw_items: list[Any],
    relevance: dict[str, float],
    k: int,
    device: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        backend = _build_backend(name, device)
        ranked = backend.rank(items, raw_items)
    metrics = evaluate_ranked_items(
        ranked,
        relevance,
        k=k,
        relevant_threshold=2,
    )
    return {
        "backend": {
            "name": backend.metadata.name,
            "version": backend.metadata.version,
        },
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "metrics": {
            "precision_at_k": round(metrics.precision_at_k, 4),
            "ndcg_at_k": round(metrics.ndcg_at_k, 4),
            "reciprocal_rank": round(metrics.reciprocal_rank, 4),
        },
        "warnings": [str(item.message) for item in captured],
        "ranking": [item.url for item in ranked],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/ranking_labels_assistant_provisional.json"),
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-items", type=int, default=25)
    parser.add_argument("--min-sources", type=int, default=4)
    args = parser.parse_args()
    if args.k <= 0:
        raise ValueError("--k must be greater than zero")

    items, raw_items, relevance = _load_fixture(
        args.fixture,
        min_items=args.min_items,
        min_sources=args.min_sources,
        require_human=True,
    )
    deterministic = _run_backend(
        "deterministic", items, raw_items, relevance, args.k, args.device
    )
    laya = _run_backend("laya", items, raw_items, relevance, args.k, args.device)
    ndcg_delta = laya["metrics"]["ndcg_at_k"] - deterministic["metrics"]["ndcg_at_k"]
    precision_delta = (
        laya["metrics"]["precision_at_k"]
        - deterministic["metrics"]["precision_at_k"]
    )
    latency_ratio = laya["latency_ms"] / max(deterministic["latency_ms"], 0.01)
    recommendation = (
        "keep deterministic/v1"
        if ndcg_delta <= 0 or latency_ratio > 10
        else "manual review required"
    )
    print(
        json.dumps(
            {
                "fixture": str(args.fixture),
                "items": len(items),
                "k": args.k,
                "results": {
                    "deterministic": deterministic,
                    "laya": laya,
                },
                "delta": {
                    "laya_minus_deterministic_precision_at_k": round(precision_delta, 4),
                    "laya_minus_deterministic_ndcg_at_k": round(ndcg_delta, 4),
                    "laya_latency_ratio": round(latency_ratio, 2),
                },
                "recommendation": recommendation,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

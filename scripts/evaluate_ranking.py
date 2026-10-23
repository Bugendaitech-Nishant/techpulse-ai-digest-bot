"""Evaluate a ranking backend against a labelled JSON fixture."""

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Any

# Allow direct execution from the repository root without requiring PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backends import DeterministicV1Backend, LayaBackend, RankingBackend
from src.evaluation import evaluate_ranked_items, validate_label_entries
from src.models import DigestItem, RawItem


def _load_fixture(
    path: Path,
    *,
    min_items: int,
    min_sources: int,
    require_human: bool = False,
) -> tuple[list[DigestItem], list[RawItem], dict[str, float]]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("Evaluation fixture must contain a non-empty JSON list")
    validate_label_entries(
        entries,
        min_items=min_items,
        min_sources=min_sources,
        require_human=require_human,
    )

    items: list[DigestItem] = []
    raw_items: list[RawItem] = []
    relevance: dict[str, float] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each evaluation fixture entry must be an object")
        title = entry["title"]
        url = entry["url"]
        source = entry["source"]
        score = entry.get("score", 0)
        label = entry["relevance"]
        items.append(
            DigestItem(
                title=title,
                url=url,
                source=source,
                category="Inspiration",  # neutral: a label-derived category would leak ground truth into the ranker
                summary=title,
                why_it_matters="Labelled evaluation item.",
            )
        )
        raw_items.append(
            RawItem(
                title=title,
                url=url,
                source=source,
                score=score,
                description=entry.get("description", ""),
                language=entry.get("language", ""),
                published_at=entry.get("published_at", ""),
            )
        )
        relevance[url] = label
    return items, raw_items, relevance


def _build_backend(name: str, device: str) -> RankingBackend:
    if name == "deterministic":
        return DeterministicV1Backend()
    if name == "laya":
        return LayaBackend.from_installed(device=device, version="installed")
    raise ValueError(f"Unsupported backend: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/ranking_labels.json"),
    )
    parser.add_argument(
        "--backend",
        choices=("deterministic", "laya"),
        default="deterministic",
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-items", type=int, default=1)
    parser.add_argument("--min-sources", type=int, default=1)
    args = parser.parse_args()
    if args.k <= 0:
        raise ValueError("--k must be greater than zero")

    items, raw_items, relevance = _load_fixture(
        args.fixture,
        min_items=args.min_items,
        min_sources=args.min_sources,
    )
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        backend = _build_backend(args.backend, args.device)
        ranked = backend.rank(items, raw_items)
    warnings_seen = [str(item.message) for item in captured]
    elapsed_ms = (time.perf_counter() - started) * 1000
    metrics = evaluate_ranked_items(
        ranked,
        relevance,
        k=args.k,
        relevant_threshold=2,
    )
    output: dict[str, Any] = {
        "backend": {
            "name": backend.metadata.name,
            "version": backend.metadata.version,
        },
        "fixture": str(args.fixture),
        "items": len(items),
        "k": args.k,
        "latency_ms": round(elapsed_ms, 2),
        "metrics": {
            "precision_at_k": round(metrics.precision_at_k, 4),
            "ndcg_at_k": round(metrics.ndcg_at_k, 4),
            "reciprocal_rank": round(metrics.reciprocal_rank, 4),
        },
        "warnings": warnings_seen,
        "ranking": [
            {
                "rank": item.rank,
                "title": item.title,
                "url": item.url,
                "priority_score": item.priority_score,
                "confidence": item.confidence,
            }
            for item in ranked
        ],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

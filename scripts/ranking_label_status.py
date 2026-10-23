"""Report whether a ranking review fixture is ready for model comparison."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_status(
    entries: list[dict[str, Any]],
    *,
    min_items: int,
    min_sources: int,
) -> dict[str, Any]:
    source_totals = Counter(str(entry.get("source", "")) for entry in entries)
    source_labelled = Counter(
        str(entry.get("source", ""))
        for entry in entries
        if isinstance(entry.get("relevance"), (int, float))
        and not isinstance(entry.get("relevance"), bool)
    )
    provisional = [
        entry.get("url", f"<entry {index}>")
        for index, entry in enumerate(entries)
        if entry.get("label_source") != "human"
    ]
    missing = [
        entry.get("url", f"<entry {index}>")
        for index, entry in enumerate(entries)
        if not isinstance(entry.get("relevance"), (int, float))
        or isinstance(entry.get("relevance"), bool)
    ]
    source_ready = all(source_labelled[source] > 0 for source in source_totals)
    ready = (
        len(entries) >= min_items
        and len(source_totals) >= min_sources
        and not missing
        and not provisional
        and source_ready
    )
    return {
        "items": len(entries),
        "labelled": len(entries) - len(missing),
        "unlabelled": len(missing),
        "sources": dict(sorted(source_totals.items())),
        "labelled_by_source": dict(sorted(source_labelled.items())),
        "missing_urls": missing,
        "non_human_label_urls": provisional,
        "requirements": {
            "min_items": min_items,
            "min_sources": min_sources,
        },
        "ready_for_comparison": ready,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/ranking_review.json"),
    )
    parser.add_argument("--min-items", type=int, default=100)
    parser.add_argument("--min-sources", type=int, default=4)
    args = parser.parse_args()
    if args.min_items <= 0 or args.min_sources <= 0:
        raise ValueError("minimum requirements must be greater than zero")
    entries = json.loads(args.fixture.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("review fixture must contain a JSON list")
    print(
        json.dumps(
            build_status(
                entries,
                min_items=args.min_items,
                min_sources=args.min_sources,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

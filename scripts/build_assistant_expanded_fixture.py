"""Build an auditable expanded provisional ranking fixture from live candidates."""

import argparse
import json
from pathlib import Path


DIRECT_TERMS = (
    "agent",
    "llm",
    "language model",
    "rag",
    "inference",
    "reasoning",
    "tool use",
    "memory",
    "routing",
    "classification",
    "coding",
    "mcp",
    "embedding",
    "multimodal",
)
ADJACENT_TERMS = (
    "robot",
    "embodied",
    "vision",
    "diffusion",
    "reinforcement",
    "planning",
    "world model",
    "speech",
    "privacy",
    "safety",
    "benchmark",
    "neural",
    "model",
)
LOW_VALUE_TERMS = (
    "game",
    "music",
    "fashion",
    "sports",
    "celebrity",
)


def provisional_label(item: dict) -> tuple[int, str]:
    text = f"{item.get('title', '')} {item.get('description', '')}".lower()
    direct_hits = sum(term in text for term in DIRECT_TERMS)
    adjacent_hits = sum(term in text for term in ADJACENT_TERMS)
    low_value_hits = sum(term in text for term in LOW_VALUE_TERMS)

    if direct_hits >= 2 or "agent" in text and "framework" in text:
        return 4, "Directly relevant to agent, LLM, retrieval, or developer-tooling work."
    if direct_hits == 1 or adjacent_hits >= 2:
        return 3, "Strongly relevant adjacent AI/ML capability with plausible agent value."
    if adjacent_hits == 1 or item.get("source") in {"github_trending", "devto_articles"}:
        return 2, "Potentially useful technical signal, but not clearly central to the target stack."
    if low_value_hits:
        return 0, "No meaningful connection to the configured AI engineering focus."
    return 1, "Peripheral technical or research relevance; limited immediate applicability."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--existing",
        type=Path,
        default=Path("tests/fixtures/ranking_labels_assistant_provisional.json"),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("tests/fixtures/live_collection_snapshot.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/ranking_labels_assistant_expanded.json"),
    )
    args = parser.parse_args()

    existing = json.loads(args.existing.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    by_url = {item["url"]: item for item in existing}
    for item in snapshot:
        if item["url"] in by_url:
            continue
        relevance, notes = provisional_label(item)
        by_url[item["url"]] = {
            "title": item["title"],
            "url": item["url"],
            "source": item["source"],
            "description": item.get("description", ""),
            "score": item.get("score", 0),
            "language": item.get("language", ""),
            "published_at": item.get("published_at", ""),
            "relevance": relevance,
            "label_source": "assistant_provisional_rubric",
            "label_notes": notes,
        }

    output = list(by_url.values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(output)} items to {args.output}")


if __name__ == "__main__":
    main()

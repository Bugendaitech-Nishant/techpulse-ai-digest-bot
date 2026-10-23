"""Export historical digest items into a human-labelling review fixture."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def export_review_fixture(database: Path, output: Path) -> int:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT d.date AS digest_date, i.title, i.url, i.source,
                   i.category, i.summary, i.why_it_matters,
                   i.relevance_score, i.impact_score, i.freshness_score,
                   i.novelty_score, i.confidence, i.priority_score, i.rank
            FROM digest_items AS i
            JOIN digests AS d ON d.date = i.digest_date
            ORDER BY d.date DESC, i.rank ASC, i.id ASC
            """
        ).fetchall()

    fixture = [
        {
            "digest_date": row["digest_date"],
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "description": row["summary"],
            "why_it_matters": row["why_it_matters"],
            "suggested_category": row["category"],
            "suggested_priority_score": row["priority_score"],
            "suggested_rank": row["rank"],
            "relevance": None,
            "label_source": None,
            "label_notes": "",
        }
        for row in rows
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    return len(fixture)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/tech_digest.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/ranking_review.json"),
    )
    args = parser.parse_args()
    count = export_review_fixture(args.database, args.output)
    print(f"Exported {count} items to {args.output}")


if __name__ == "__main__":
    main()

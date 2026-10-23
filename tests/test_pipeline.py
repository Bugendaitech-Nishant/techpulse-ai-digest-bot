"""
test_pipeline.py — Integration and end-to-end pipeline tests.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from src.orchestrator import DigestOrchestrator
from src.storage.database import DigestDatabase
from src.agents.harvester import HarvesterAgent
from src.agents.processor import ProcessorAgent
from src.agents.publisher import PublisherAgent
from src.models import RawItem


def test_end_to_end_pipeline_with_mock_data():
    """Verify complete pipeline execution from harvesting to markdown publication."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "digests"

        db = DigestDatabase(db_path, auto_hydrate=False)

        # Mock Harvester
        mock_harvester = MagicMock(spec=HarvesterAgent)
        sample_raw = [
            RawItem(
                title="Google DeepMind / AgentZero",
                url="https://github.com/google/agent-zero",
                description="General purpose autonomous agent framework in Python.",
                source="github_trending",
                score=500,
                language="Python",
            ),
            RawItem(
                title="Hacker News: Next Gen Python JIT",
                url="https://news.ycombinator.com/item?id=9999",
                description="Discussion on Python 3.13 free threading and JIT performance.",
                source="hacker_news",
                score=350,
            ),
        ]
        mock_harvester.harvest.return_value = (sample_raw, {"total_harvested_raw": 2})

        # Real Processor using rule-based fallback (no external network call needed for unit test)
        processor = ProcessorAgent(api_key=None)

        # Real Publisher writing to temp dir
        publisher = PublisherAgent(output_dir=output_dir)

        orchestrator = DigestOrchestrator(
            db=db,
            harvester=mock_harvester,
            processor=processor,
            publisher=publisher,
        )

        res = orchestrator.run(dry_run=False, custom_date="2026-10-22")

        assert res["success"] is True
        assert res["date"] == "2026-10-22"
        assert res["output_file"] is not None
        assert orchestrator.processor.ranking_backend.metadata.name == "deterministic"
        assert orchestrator.processor.ranking_backend.metadata.version == "v1"

        # Verify output file was created and contains expected headers
        out_file = Path(res["output_file"])
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "# TechPulse Daily Digest — 2026-10-22" in content
        assert "Google DeepMind / AgentZero" in content

        # Verify database persisted the digest
        stats = db.get_stats()
        assert stats["total_digests_generated"] == 1


def test_second_run_on_the_same_day_adds_to_the_digest_instead_of_replacing_it():
    from src.models import DigestItem, TechDigest
    from src.orchestrator import DigestOrchestrator

    def item(n, category="Must Read", score=0.0):
        return DigestItem(title=f"T{n}", url=f"https://e.com/{n}", source="s", category=category,
                          summary="s", why_it_matters="w", priority_score=score)

    existing = {"total_harvested": 80, "items": [item(1, score=50).model_dump(), item(2, "Inspiration").model_dump()]}
    new = TechDigest(date="2026-10-23", items=[item(3, score=70), item(1, score=90)], total_harvested=38)
    merged = DigestOrchestrator.merge_same_day(existing, new)
    assert [i.url for i in merged.items] == ["https://e.com/1", "https://e.com/3", "https://e.com/2"]
    assert merged.items[0].priority_score == 90  # the fresh copy of a repeated URL wins
    assert merged.total_harvested == 118 and merged.total_curated == 3
    assert [i.rank for i in merged.items] == [1, 2, 3]

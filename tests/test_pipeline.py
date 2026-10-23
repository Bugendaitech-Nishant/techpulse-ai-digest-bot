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

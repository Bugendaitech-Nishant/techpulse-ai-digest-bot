"""Tests for the run log, failed-source tracking and the feedback figures in insights."""

import tempfile
from pathlib import Path

from src import feedback as fb
from src import runlog
from src.agents.publisher import PublisherAgent
from src.models import DigestItem, TechDigest
from src.orchestrator import DigestOrchestrator
from src.storage.database import DigestDatabase


def test_run_log_round_trip_newest_first_and_skips_corrupt_lines(tmp_path):
    log = tmp_path / "runs.jsonl"
    for date in ("2026-10-21", "2026-10-22"):
        runlog.append_run(runlog.make_record(date=date, duration_seconds=12.34, harvested=90, novel=40, kept=20,
                                             unreviewed=0, security=1, failed_sources=["b", "a"]), log)
    log.write_text(log.read_text() + "garbage\n", encoding="utf-8")
    runs = runlog.read_runs(5, log)
    assert [r["date"] for r in runs] == ["2026-10-22", "2026-10-21"]
    assert runs[0]["failed_sources"] == ["a", "b"] and runs[0]["duration_seconds"] == 12.3


class FakeHarvester:
    def harvest(self):
        stats = {
            "total_harvested_raw": 10, "novel_items_for_curation": 2,
            "collector_breakdown": {"arxiv_ai": {"success": False}, "hacker_news": {"success": True}},
        }
        return [], stats  # no novel items: the run still has to be logged


def test_orchestrator_logs_the_run_and_names_failed_sources():
    with tempfile.TemporaryDirectory() as tmp:
        db = DigestDatabase(Path(tmp) / "t.db", auto_hydrate=False)
        result = DigestOrchestrator(
            db=db, harvester=FakeHarvester(), publisher=PublisherAgent(output_dir=Path(tmp) / "digests")
        ).run()
    assert result["failed_sources"] == ["arxiv_ai"]
    run = runlog.read_runs(1)[0]
    assert run["failed_sources"] == ["arxiv_ai"] and run["date"] == result["date"]


def test_insights_report_useful_rate_overall_and_for_the_top_ten(tmp_path):
    db = DigestDatabase(tmp_path / "t.db", auto_hydrate=False)
    items = [DigestItem(title=f"T{n}", url=f"https://e.com/{n}", source="s", category="Must Read",
                        summary="s", why_it_matters="w", priority_score=100 - n) for n in range(12)]
    db.record_digest(TechDigest(date="2026-10-23", items=items, total_harvested=12))
    for n, rating in ((0, 1), (1, 1), (2, -1), (11, -1)):  # item 11 is outside the top 10
        db.record_feedback(fb.make_event(items[n].url, rating, items[n].title, "s", "s", "Must Read"))
    feedback = db.get_insights()["feedback"]
    assert feedback["up"] == 2 and feedback["down"] == 2 and feedback["useful_rate"] == 0.5
    assert feedback["top10_rated"] == 3 and feedback["top10_useful_rate"] == 0.667


def test_insights_have_no_rate_before_any_rating(tmp_path):
    db = DigestDatabase(tmp_path / "t.db", auto_hydrate=False)
    feedback = db.get_insights()["feedback"]
    assert feedback["useful_rate"] is None and feedback["top10_useful_rate"] is None


def test_an_empty_digest_never_overwrites_a_digest_that_has_items(tmp_path):
    publisher = PublisherAgent(output_dir=tmp_path)
    item = DigestItem(title="Real item", url="https://e.com/1", source="s", category="Must Read",
                      summary="s", why_it_matters="w")
    path = publisher.publish(TechDigest(date="2026-10-23", items=[item], total_harvested=1))
    publisher.publish(TechDigest(date="2026-10-23", items=[], total_harvested=0))
    assert "Real item" in path.read_text(encoding="utf-8")

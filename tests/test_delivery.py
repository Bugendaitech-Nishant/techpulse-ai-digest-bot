"""Tests for the email brief and the daily run script."""

import pytest

from config.settings import settings
from scripts import run_daily
from src import delivery


def _item(n: int, category: str = "Must Read", why: str = "A specific reason", title: str | None = None) -> dict:
    return {
        "title": title or f"Item {n}",
        "url": f"https://example.com/{n}",
        "source": "arxiv_ai",
        "category": category,
        "why_it_matters": why,
    }


def _digest(items: list[dict]) -> dict:
    return {"date": "2026-10-23", "items": items}


def test_brief_takes_top_n_and_skips_filtered_items():
    items = [_item(1), _item(2, "Skip"), _item(3), _item(4), _item(5)]
    brief = delivery.build_brief(_digest(items), top_n=2, feed_url="https://feed.example/")
    assert "Item 1" in brief["text"] and "Item 3" in brief["text"]
    assert "Item 2" not in brief["text"] and "Item 4" not in brief["text"]
    assert "https://feed.example/" in brief["html"]
    assert brief["subject"] == "TechPulse 2026-10-23: 2 items worth your time"


def test_brief_escapes_html_in_titles_and_reasons():
    brief = delivery.build_brief(_digest([_item(1, title="<script>alert(1)</script>", why='"quoted" & <b>')]), top_n=3)
    assert "<script>" not in brief["html"]
    assert "&lt;script&gt;" in brief["html"]


def test_problems_flag_too_few_items_and_unreviewed_runs():
    few = delivery.digest_problems(_digest([_item(1)]), min_kept=5)
    assert any("Only 1 items" in p for p in few)

    unreviewed = [_item(n, why="Not reviewed by the AI curator. Keyword match: x.") for n in range(6)]
    problems = delivery.digest_problems(_digest(unreviewed), min_kept=5)
    assert any("not reviewed" in p for p in problems)

    healthy = [_item(n) for n in range(6)]
    assert delivery.digest_problems(_digest(healthy), min_kept=5) == []


def test_brief_marks_a_problem_run_in_subject_and_body():
    brief = delivery.build_brief(_digest([_item(1)]), top_n=3, problems=["Only 1 items were kept."])
    assert brief["subject"].startswith("[check this run]")
    assert "Only 1 items were kept." in brief["html"]


class FakeSMTP:
    sent: list = []
    started_tls = False
    logged_in: tuple | None = None

    def __init__(self, host, port, timeout=0):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        FakeSMTP.started_tls = True

    def login(self, user, password):
        FakeSMTP.logged_in = (user, password)

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.started_tls, FakeSMTP.logged_in = [], False, None
    monkeypatch.setattr(delivery.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USER", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pw")
    monkeypatch.setattr(settings, "EMAIL_FROM", "bot@example.com")
    monkeypatch.setattr(settings, "EMAIL_TO", "a@example.com, b@example.com")
    return FakeSMTP


def test_send_email_uses_starttls_login_and_all_recipients(smtp):
    delivery.send_email("Subject", "plain", "<p>html</p>")
    assert smtp.started_tls and smtp.logged_in == ("user", "pw")
    message = smtp.sent[0]
    assert message["To"] == "a@example.com, b@example.com"
    assert message.get_body(("html",)) is not None


def test_send_email_refuses_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    with pytest.raises(RuntimeError):
        delivery.send_email("s", "t")


class FakeDb:
    def __init__(self, digest):
        self._digest = digest

    def get_digest_by_date(self, date):
        return self._digest


def _patch_pipeline(monkeypatch, digest, crash=False):
    class FakeOrchestrator:
        def __init__(self):
            self.db = FakeDb(digest)

        def run(self, dry_run=False):
            if crash:
                raise RuntimeError("boom")
            return {"date": "2026-10-23"}

    monkeypatch.setattr(run_daily, "DigestOrchestrator", FakeOrchestrator)


def test_run_daily_sends_brief_and_exits_zero_when_healthy(smtp, monkeypatch):
    _patch_pipeline(monkeypatch, _digest([_item(n) for n in range(6)]))
    assert run_daily.main([]) == 0
    assert len(smtp.sent) == 1


def test_run_daily_exits_3_on_a_suspect_run_but_still_sends(smtp, monkeypatch):
    _patch_pipeline(monkeypatch, _digest([_item(1)]))
    assert run_daily.main([]) == 3
    assert smtp.sent[0]["Subject"].startswith("[check this run]")


def test_run_daily_alerts_by_email_when_the_pipeline_crashes(smtp, monkeypatch):
    _patch_pipeline(monkeypatch, None, crash=True)
    assert run_daily.main([]) == 1
    assert "failed" in smtp.sent[0]["Subject"]


def test_run_daily_reports_email_failure_with_exit_2(smtp, monkeypatch):
    _patch_pipeline(monkeypatch, _digest([_item(n) for n in range(6)]))

    def boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr(delivery, "send_email", boom)
    assert run_daily.main([]) == 2

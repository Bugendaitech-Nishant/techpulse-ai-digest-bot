"""The critic and reviser loop: verdicts, rewrite acceptance, and failing safely."""

import json

from config.settings import settings
from src.agents.critic import review_digest, review_item
from src.models import DigestItem, TechDigest

SOURCE = "x" * 400


def _item(n=1, **kw):
    return DigestItem(**{"title": f"T{n}", "url": f"https://x.dev/{n}", "source": "hacker_news", "category": "Must Read",
                         "summary": "orig", "why_it_matters": "why", "rank": n, **kw})


def _claims(*labels):
    return json.dumps({"claims": [{"claim": f"c{n}", "label": label} for n, label in enumerate(labels)]})


def _script(*replies):
    queue = list(replies)

    def ask(prompt, models=None):
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return ask


REWRITE = json.dumps({"summary": "new", "why_it_matters": "newwhy"})


def test_clean_entry_is_verified_and_unchanged():
    out = review_item(_item(), SOURCE, _script(_claims("supported")))
    assert (out.verification, out.summary) == ("verified", "orig")


def test_a_clean_rewrite_replaces_the_entry():
    out = review_item(_item(), SOURCE, _script(_claims("unsupported"), REWRITE, _claims("supported")))
    assert (out.verification, out.summary, out.why_it_matters) == ("corrected", "new", "newwhy")


def test_a_rewrite_that_is_no_better_is_thrown_away_and_the_problem_is_shown():
    out = review_item(_item(), SOURCE, _script(_claims("contradicted"), REWRITE, _claims("unsupported", "unsupported")))
    assert (out.verification, out.summary, out.verification_note) == ("unverified", "orig", "c0")


def test_a_better_but_imperfect_rewrite_is_kept_and_still_flagged():
    out = review_item(_item(), SOURCE, _script(_claims("unsupported", "unsupported"), REWRITE, _claims("unsupported")))
    assert (out.verification, out.summary, out.verification_note) == ("unverified", "new", "c0")


def test_an_empty_rewrite_changes_nothing():
    out = review_item(_item(), SOURCE, _script(_claims("unsupported"), "{}"))
    assert (out.verification, out.summary) == ("unverified", "orig")


def _digest(*items):
    return TechDigest(date="2026-10-30", items=list(items), total_harvested=len(items))


def test_rate_limit_stops_the_pass_but_keeps_earlier_results(monkeypatch):
    monkeypatch.setattr(settings, "CRITIC_PAUSE_SECONDS", 0)
    ask = _script(_claims("supported"), RuntimeError("Error code: 429"))
    out = review_digest(_digest(_item(1), _item(2), _item(3)), ask, read=lambda u: SOURCE, limit=3)
    assert [i.verification for i in out.items] == ["verified", "not_checked", "not_checked"]


def test_bad_json_skips_one_item_and_an_unreadable_page_is_never_accused(monkeypatch):
    monkeypatch.setattr(settings, "CRITIC_PAUSE_SECONDS", 0)
    ask = _script("not json", _claims("supported"))
    items = [_item(1), _item(2), _item(3)]
    out = review_digest(_digest(*items), ask, read=lambda u: "" if u.endswith("3") else SOURCE, limit=3)
    assert [i.verification for i in out.items] == ["not_checked", "verified", "not_checked"]


def test_patch_items_go_first_and_skips_and_advisories_are_left_out(monkeypatch):
    monkeypatch.setattr(settings, "CRITIC_PAUSE_SECONDS", 0)
    seen = []
    items = [_item(1), _item(2, next_step="Patch", rank=9), _item(3, category="Skip", next_step="Ignore"),
             _item(4, source="security_advisories", next_step="Patch")]
    review_digest(_digest(*items), _script(_claims("supported")), read=lambda u: seen.append(u) or SOURCE, limit=1)
    assert seen == ["https://x.dev/2"]

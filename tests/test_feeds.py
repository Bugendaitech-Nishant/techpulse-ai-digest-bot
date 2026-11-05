"""Official feeds: parsing, freshness, hostile input, and one dead feed not taking the rest down."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from config.settings import settings
from src.collectors import feeds
from src.collectors.feeds import OfficialFeedsCollector, parse_feed

NOW = datetime.now(timezone.utc)


def _rss(*entries):
    items = "".join(f"<item><title>{t}</title><link>{l}</link><description>&lt;p&gt;{d}&lt;/p&gt;</description>"
                    f"<pubDate>{format_datetime(p)}</pubDate></item>" for t, l, d, p in entries)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{items}</channel></rss>'.encode()


def _atom(*entries):
    items = "".join(f'<entry><title>{t}</title><link rel="alternate" href="{l}"/><link rel="self" href="https://x/self"/>'
                    f"<summary>{d}</summary><updated>{p.isoformat()}</updated></entry>" for t, l, d, p in entries)
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{items}</feed>'.encode()


def test_rss_and_atom_are_both_read_and_html_is_stripped():
    rss = parse_feed(_rss(("Release", "https://x.test/r", "Big &lt;b&gt;change&lt;/b&gt;", NOW)))
    assert rss[0]["title"] == "Release" and rss[0]["text"] == "Big change" and rss[0]["published"] is not None
    atom = parse_feed(_atom(("Post", "https://x.test/p", "Summary here", NOW)))
    assert atom[0]["link"] == "https://x.test/p"  # the alternate link, not rel=self


def test_entity_declarations_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><rss><channel><item><title>&b;</title></item></channel></rss>'
    with pytest.raises(ValueError):
        parse_feed(bomb)


class _Resp:
    def __init__(self, content=b"", status=200):
        self.content, self.status_code = content, status


@pytest.fixture
def two_feeds(monkeypatch):
    monkeypatch.setattr(settings, "FEEDS", [("Good", "https://good.test/f"), ("Dead", "https://dead.test/f")])
    monkeypatch.setattr(settings, "FEED_PER_FEED", 2)


def _serve(monkeypatch, pages):
    def get(url, **kw):
        page = pages[url]
        if isinstance(page, Exception):
            raise page
        return page
    monkeypatch.setattr(feeds.requests, "get", get)


def test_only_fresh_dated_entries_become_items_newest_first_and_capped(two_feeds, monkeypatch):
    body = _rss(("Old", "https://x.test/old", "d", NOW - timedelta(days=30)), ("Mid", "https://x.test/mid", "d", NOW - timedelta(hours=30)),
                ("New", "https://x.test/new", "d", NOW - timedelta(hours=1)), ("Newer", "https://x.test/newer", "d", NOW),
                ("Bad link", "javascript:alert(1)", "d", NOW))
    _serve(monkeypatch, {"https://good.test/f": _Resp(body), "https://dead.test/f": requests.ConnectionError("down")})
    items = OfficialFeedsCollector()._fetch_items()
    assert [i.title for i in items] == ["Newer", "New"]  # capped at 2, stale and unsafe-link entries excluded
    assert items[0].source == "official_blogs" and items[0].description.startswith("Good: ") and items[0].published_at


def test_one_dead_feed_is_skipped_but_all_dead_is_a_failure(two_feeds, monkeypatch):
    _serve(monkeypatch, {"https://good.test/f": _Resp(_rss(("Alpha post", "https://x.test/a", "d", NOW))), "https://dead.test/f": _Resp(status=500)})
    assert len(OfficialFeedsCollector()._fetch_items()) == 1
    _serve(monkeypatch, {"https://good.test/f": _Resp(b"<not xml"), "https://dead.test/f": _Resp(status=404)})
    with pytest.raises(RuntimeError, match="all 2 feeds failed"):
        OfficialFeedsCollector()._fetch_items()


def test_oversized_responses_are_skipped(two_feeds, monkeypatch):
    _serve(monkeypatch, {"https://good.test/f": _Resp(b"x" * (feeds.MAX_BYTES + 1)), "https://dead.test/f": _Resp(status=500)})
    label, items, why = OfficialFeedsCollector()._read(("Good", "https://good.test/f"))
    assert items == [] and why == "response too large"


def test_a_one_letter_title_is_skipped_instead_of_breaking_the_feed(two_feeds, monkeypatch):
    body = _rss(("A", "https://x.test/a", "d", NOW), ("Proper title", "https://x.test/b", "d", NOW))
    _serve(monkeypatch, {"https://good.test/f": _Resp(body), "https://dead.test/f": _Resp(status=500)})
    assert [i.title for i in OfficialFeedsCollector()._fetch_items()] == ["Proper title"]

"""
Browser tests for the briefing and archive. They read a running server (default http://127.0.0.1:8000)
and never change team state, so they are safe to run against a shared instance.

    python -m uvicorn api:app --port 8000 &
    pytest tests/test_ui_playwright.py
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

BASE = os.getenv("TECHPULSE_URL", "http://127.0.0.1:8000")
SCREENSHOTS = Path(__file__).parent / "screenshots"
SCREENSHOTS.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto(BASE, timeout=15000)
    pg.wait_for_selector(".brief-card", timeout=10000)
    yield pg
    pg.close()


def test_headline_answers_what_needs_attention(page):
    headline = page.locator("#headline").inner_text()
    assert headline and "Reading" not in headline  # replaced by a real sentence
    assert "harvested" in page.locator("#lede-sub").inner_text()
    page.screenshot(path=str(SCREENSHOTS / "1_briefing.png"))


def test_stack_strip_lists_the_stack_and_lights_only_real_hits(page):
    chips = page.locator(".stack-chip")
    assert chips.count() >= 1
    for chip in chips.all():
        if "is-hit" in (chip.get_attribute("class") or ""):
            assert chip.locator("b").count() == 1  # a lit chip carries its count


def test_briefing_is_short_and_the_rest_is_collapsed(page):
    featured = page.locator(".tier .brief-card").count()
    assert 1 <= featured <= 12
    assert page.locator("#rest-more").count() in (0, 1)
    assert page.locator("#rest-filtered").count() in (0, 1)
    rest = page.locator("#rest-filtered")
    if rest.count():
        assert not rest.evaluate("el => el.open")
        rest.locator("summary").click()
        expect(rest.locator(".rest-list li").first).to_be_visible()


def test_only_actionable_items_offer_to_be_taken(page):
    for section in ("stack", "pick"):
        for card in page.locator(f".tier-{section} .brief-card").all():
            if card.locator("[data-triage='doing']").count():
                assert card.locator(".action").count() == 1  # a take button needs a real action beside it
    for card in page.locator(".tier-alert .brief-card").all():
        assert card.locator("[data-triage]").count() >= 1


def test_every_card_can_be_rated(page):
    first = page.locator(".brief-card").first
    expect(first.locator(".rate-btn").first).to_be_visible()


def test_day_navigation_walks_back_and_forth(page):
    prev, nxt = page.locator("#day-prev"), page.locator("#day-next")
    expect(nxt).to_be_disabled()  # already on the latest day
    if prev.is_enabled():
        label = page.locator("#day-label").inner_text()
        prev.click()
        page.wait_for_function("(l) => document.getElementById('day-label').textContent !== l", arg=label)
        expect(nxt).to_be_enabled()
        nxt.click()
        page.wait_for_function("document.getElementById('day-label').textContent.includes('latest')")


def test_harvest_controls_live_under_admin(page):
    expect(page.locator("#quota-pill")).not_to_be_visible()
    page.locator("#admin-menu > summary").click()
    expect(page.locator("#quota-pill")).to_be_visible()
    expect(page.locator("#btn-harvest")).to_be_visible()


def test_archive_search_finds_items_across_days(browser):
    pg = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto(f"{BASE}/curated-digests", timeout=15000)
    pg.wait_for_selector(".result-row", timeout=10000)
    total = pg.locator(".result-row").count()
    pg.fill("#q", "zzzzzz-no-such-thing")
    expect(pg.locator(".state-panel h3")).to_have_text("Nothing matches that")
    pg.fill("#q", "")
    pg.wait_for_selector(".result-row")
    assert pg.locator(".result-row").count() == total
    pg.locator("#health > summary").click()
    expect(pg.locator("#readings")).to_be_visible()
    pg.screenshot(path=str(SCREENSHOTS / "2_archive.png"))
    pg.close()


def test_phone_width_has_no_sideways_scroll(browser):
    pg = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    pg.goto(BASE, timeout=15000)
    pg.wait_for_selector(".brief-card")
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    pg.close()

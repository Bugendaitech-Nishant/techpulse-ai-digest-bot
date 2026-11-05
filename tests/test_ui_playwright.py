"""
Browser tests for the briefing and Find. They read a running server (default http://127.0.0.1:8000)
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


def test_headline_states_what_the_day_holds(page):
    headline = page.locator("#headline").inner_text()
    assert headline and "Reading" not in headline  # replaced by a real sentence
    assert "kept" in page.locator("#lede-sub").inner_text()
    page.screenshot(path=str(SCREENSHOTS / "1_briefing.png"))


def test_major_updates_are_few_and_the_rest_is_grouped_by_area(page):
    assert 1 <= page.locator(".tier-major .brief-card").count() <= 5
    assert page.locator(".area-group").count() >= 1
    for group in page.locator(".area-group").all():
        assert group.locator("ul.rest-list").first.locator("li").count() <= 4  # the rest sits behind "more in ..."


def test_picking_an_area_narrows_the_whole_page_and_the_link_keeps_it(page):
    chips = page.locator(".area-chip[data-area]:not([data-area='all'])")
    assert chips.count() >= 2
    name = chips.first.get_attribute("data-area")
    chips.first.click()
    assert "area=" in page.url
    for group in page.locator(".area-group").all():
        assert group.get_attribute("aria-label") == name  # only the chosen area's group remains
    page.reload()
    page.wait_for_selector(".area-chip.is-active")
    assert page.locator(".area-chip.is-active").get_attribute("data-area") == name
    page.locator(".area-chip[data-area='all']").click()
    assert "area=" not in page.url


def test_the_watchlist_is_optional_and_lit_only_for_real_hits(page):
    strip = page.locator("#stack-strip")
    if strip.is_hidden():
        return  # no watchlist configured: no strip, no alerts
    for chip in page.locator(".stack-chip.is-hit").all():
        assert chip.locator("b").count() == 1


def test_only_actionable_items_offer_to_be_taken(page):
    for card in page.locator(".brief-card").all():
        if card.locator("[data-triage='doing']").count():
            in_alerts = card.evaluate("el => !!el.closest('.tier-alert')")
            assert in_alerts or card.locator(".action").count() == 1  # outside alerts a patch carries its concrete action


def test_every_featured_card_can_be_rated(page):
    expect(page.locator(".brief-card").first.locator(".rate-btn").first).to_be_visible()


def test_filtered_items_are_collapsed_with_their_reason(page):
    rest = page.locator("#rest-filtered")
    if rest.count():
        assert not rest.evaluate("el => el.open")
        rest.locator("summary").click()
        expect(rest.locator(".rest-list li p").first).to_be_visible()


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


def test_find_answers_from_the_digests_and_offers_github(browser):
    pg = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto(f"{BASE}/find", timeout=15000)
    pg.wait_for_selector(".result-row", timeout=10000)  # empty query lists recent items
    pg.fill("#q", "zzzzzz-no-such-thing")
    expect(pg.locator("#results .state-panel h3")).to_have_text("Nothing in your digests matches that")
    pg.fill("#q", "")
    pg.wait_for_selector("#results .result-row")
    expect(pg.locator("#github-section")).to_be_hidden()  # nothing to ask GitHub without a query
    pg.fill("#q", "postgres")
    pg.wait_for_selector("#github-section:not([hidden])")
    pg.select_option("#kind", "paper")
    expect(pg.locator("#github-section")).to_be_hidden()  # papers are not repositories
    pg.screenshot(path=str(SCREENSHOTS / "2_find.png"))
    pg.close()


def test_ask_is_a_deliberate_click_and_is_disabled_without_a_model(browser):
    import json
    import urllib.request

    status = json.load(urllib.request.urlopen(f"{BASE}/api/ask/status"))
    pg = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto(f"{BASE}/find", timeout=15000)
    pg.wait_for_selector(".result-row")
    pg.fill("#q", "vector database for RAG")
    pg.keyboard.press("Enter")  # Enter searches; it must never spend a model question
    pg.wait_for_timeout(800)
    expect(pg.locator("#ask-panel")).to_be_hidden()
    if status["available"]:
        expect(pg.locator("#btn-ask")).to_be_enabled()
    else:
        expect(pg.locator("#btn-ask")).to_be_disabled()
        assert "GROQ_API_KEY" in pg.locator("#btn-ask").get_attribute("title")
    pg.close()


def test_old_archive_address_still_works(browser):
    pg = browser.new_context().new_page()
    assert pg.goto(f"{BASE}/curated-digests").status == 200
    pg.close()


def test_phone_width_has_no_sideways_scroll(browser):
    pg = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    for path in ("/", "/find"):
        pg.goto(BASE + path, timeout=15000)
        pg.wait_for_selector(".brief-card, .result-row")
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), path
    pg.close()

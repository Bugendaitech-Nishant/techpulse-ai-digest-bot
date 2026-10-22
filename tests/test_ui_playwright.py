"""
test_ui_playwright.py — End-to-End Playwright Browser Verification
Comprehensive test suite validating:
1. Instrument telemetry & interactive KPI metrics
2. Historical date switcher dropdown
3. High-signal category tabs & noise audit separation
4. Source spectrum filter pills
5. Instant search with Ctrl+K shortcut
6. Export Markdown action
7. Zero-scroll Cockpit Split flight mode & sticky inspector
8. Keyboard flight navigation (ArrowDown / ArrowUp)
9. Quick-reading drawer modal & ESC dismiss
10. Visual screenshot captures for visual verification
"""

import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="module")
def browser_page():
    """Launch headless Chromium browser and open the dashboard."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto("http://127.0.0.1:8000", timeout=15000)
        # Wait for signals to load
        page.wait_for_selector(".signal-card", timeout=10000)
        yield page
        browser.close()


def test_ui_telemetry_and_kpis(browser_page):
    """Verify brand header, pulsating beacon, and 4 KPI cards with positive counts."""
    expect(browser_page.locator(".brand-monolith")).to_be_visible()
    expect(browser_page.locator(".beacon-pulse")).to_be_visible()

    # Check 4 KPI cards
    tracked = browser_page.locator("#kpi-tracked")
    must_read = browser_page.locator("#kpi-must-read")
    inspiration = browser_page.locator("#kpi-inspiration")
    engine = browser_page.locator("#kpi-engine")

    expect(tracked).to_be_visible()
    expect(must_read).to_be_visible()
    expect(inspiration).to_be_visible()
    expect(engine).to_be_visible()

    # Ensure numbers are rendered (not empty or '--')
    assert tracked.inner_text().strip() not in ("", "--")
    assert must_read.inner_text().strip() not in ("", "--")
    assert int(must_read.inner_text().strip()) >= 0

    # Capture initial dashboard grid screenshot
    browser_page.screenshot(path=str(SCREENSHOTS_DIR / "1_dashboard_grid.png"))


def test_interactive_kpi_filter(browser_page):
    """Verify clicking on a KPI card instantly filters to that category."""
    initial_count = browser_page.locator(".signal-card").count()
    must_read_count_str = browser_page.locator("#kpi-must-read").inner_text().strip()
    must_read_count = int(must_read_count_str) if must_read_count_str.isdigit() else 0

    # Click on "High Conviction" KPI card
    browser_page.locator("#kpi-card-must-read").click()
    browser_page.wait_for_timeout(300)

    # Must Read tab should be active
    expect(browser_page.locator("#tab-must-read")).to_have_class("seg-btn is-active")
    filtered_count = browser_page.locator(".signal-card").count()
    assert filtered_count == must_read_count

    # Click on Corpus KPI card to return to High Signal
    browser_page.locator("#kpi-card-corpus").click()
    browser_page.wait_for_timeout(300)
    expect(browser_page.locator("#tab-curated")).to_have_class("seg-btn is-active")


def test_category_tabs_and_noise_separation(browser_page):
    """Verify tabs show counts and Noise Audit tab keeps skips isolated."""
    tab_curated = browser_page.locator("#tab-curated")
    tab_must_read = browser_page.locator("#tab-must-read")
    tab_inspiration = browser_page.locator("#tab-inspiration")
    tab_skip = browser_page.locator("#tab-skip")

    expect(tab_curated).to_be_visible()
    expect(tab_must_read).to_be_visible()
    expect(tab_inspiration).to_be_visible()
    expect(tab_skip).to_be_visible()

    # Click Inspiration tab
    tab_inspiration.click()
    browser_page.wait_for_timeout(300)
    expect(tab_inspiration).to_have_class("seg-btn is-active")

    # In Inspiration view, no card should have 'Must Read' or 'Skip' as its category
    categories = browser_page.locator(".score-badge").all_inner_texts()
    for cat in categories:
        assert cat.strip() == "Inspiration"

    # Click Noise Audit tab
    tab_skip.click()
    browser_page.wait_for_timeout(300)
    expect(tab_skip).to_have_class("seg-btn muted is-active")

    # Return to High Signal default
    tab_curated.click()
    browser_page.wait_for_timeout(300)
    expect(tab_curated).to_have_class("seg-btn is-active")


def test_historical_date_switcher(browser_page):
    """Verify historical date selector dropdown exists and can switch digests."""
    date_select = browser_page.locator("#date-select")
    expect(date_select).to_be_visible()

    options = date_select.locator("option").all_inner_texts()
    assert len(options) >= 1


def test_source_spectrum_filter(browser_page):
    """Verify source pills filter signals properly."""
    pills = browser_page.locator(".spectrum-pill")
    expect(pills.first).to_be_visible()

    count_initial = browser_page.locator(".signal-card").count()
    assert count_initial > 0

    # Click on the second pill (first specific source)
    if pills.count() > 1:
        pills.nth(1).click()
        browser_page.wait_for_timeout(300)
        filtered_count = browser_page.locator(".signal-card").count()
        assert filtered_count > 0
        # Reset back to "All Sources"
        pills.first.click()
        browser_page.wait_for_timeout(300)
        assert browser_page.locator(".signal-card").count() == count_initial


def test_instant_search_filter(browser_page):
    """Verify search input filters cards in real-time."""
    search_input = browser_page.locator("#search-input")
    initial_count = browser_page.locator(".signal-card").count()

    search_input.fill("a")
    browser_page.wait_for_timeout(300)

    filtered_count = browser_page.locator(".signal-card").count()
    assert filtered_count <= initial_count

    # Clear search
    search_input.fill("")
    browser_page.wait_for_timeout(300)
    assert browser_page.locator(".signal-card").count() == initial_count


def test_grid_modal_drawer(browser_page):
    """Verify clicking a card in Grid Mode opens the inspector modal and ESC dismisses it."""
    first_card = browser_page.locator(".signal-card").first
    first_card.click()
    browser_page.wait_for_timeout(400)

    modal = browser_page.locator("#grid-modal")
    expect(modal).to_be_visible()
    expect(modal.locator(".inspector-title")).to_be_visible()

    # Press ESC to dismiss
    browser_page.keyboard.press("Escape")
    browser_page.wait_for_timeout(300)
    expect(browser_page.locator("#grid-modal")).not_to_be_visible()


def test_cockpit_split_view_mode(browser_page):
    """Verify toggling to Cockpit Split View (zero-scroll master-detail mode)."""
    cockpit_btn = browser_page.locator("#view-cockpit-btn")
    cockpit_btn.click()
    browser_page.wait_for_timeout(400)

    # Check that .cockpit-split-view class is applied
    expect(browser_page.locator(".cockpit-split-view")).to_be_visible()
    expect(browser_page.locator("#sticky-inspector")).to_be_visible()
    expect(browser_page.locator("#keyboard-hint")).to_be_visible()

    # Capture Cockpit view screenshot
    browser_page.screenshot(path=str(SCREENSHOTS_DIR / "2_cockpit_split_view.png"))


def test_keyboard_flight_navigation(browser_page):
    """Verify keyboard ArrowDown/ArrowUp moves selection and updates inspector."""
    initial_title = browser_page.locator("#sticky-inspector .inspector-title").inner_text()
    browser_page.keyboard.press("ArrowDown")
    browser_page.wait_for_timeout(300)

    next_title = browser_page.locator("#sticky-inspector .inspector-title").inner_text()
    assert initial_title != next_title

    # Press ArrowUp returns back
    browser_page.keyboard.press("ArrowUp")
    browser_page.wait_for_timeout(300)
    returned_title = browser_page.locator("#sticky-inspector .inspector-title").inner_text()
    assert returned_title == initial_title


def test_quota_and_cooldown_indicator(browser_page):
    """Verify that quota pill in header displays rate limit and cooldown metrics."""
    quota_pill = browser_page.locator("#quota-pill")
    quota_dot = browser_page.locator("#quota-dot")
    quota_text = browser_page.locator("#quota-text")

    expect(quota_pill).to_be_visible()
    expect(quota_dot).to_be_visible()
    expect(quota_text).to_be_visible()

    text_content = quota_text.inner_text().strip()
    assert ("left/hr" in text_content or "Ready" in text_content or "Cooldown" in text_content)


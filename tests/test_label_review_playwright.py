from playwright.sync_api import expect, sync_playwright


def test_label_review_workspace_loads_and_reports_completion():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto("http://127.0.0.1:8000/label-review", timeout=15000)
            expect(page.locator("h1")).to_have_text("Human relevance review")
            expect(page.locator("#progress-count")).to_have_text("108 / 108 labelled")
            expect(page.locator("#complete")).to_be_visible()
            expect(page.locator("#review-card")).to_be_hidden()
        finally:
            browser.close()

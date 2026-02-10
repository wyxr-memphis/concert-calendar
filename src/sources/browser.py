"""Browser automation helpers for JavaScript-heavy sites."""

from typing import Optional
from playwright.sync_api import sync_playwright, Page
from bs4 import BeautifulSoup


def get_page_with_js(url: str, timeout: int = 30000) -> Optional[BeautifulSoup]:
    """
    Fetch a page with JavaScript rendering using Playwright.

    Args:
        url: The URL to fetch
        timeout: Timeout in milliseconds (default 30s)

    Returns:
        BeautifulSoup object of rendered HTML, or None if failed
    """
    try:
        with sync_playwright() as p:
            # Launch browser with args to avoid detection
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]
            )
            page = browser.new_page()

            # Hide automation indicators
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
            """)

            # Set headers to look like a real browser
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })

            # Navigate to page - use 'load' instead of 'networkidle' to be faster
            page.goto(url, wait_until="load", timeout=timeout)

            # Wait a bit for dynamic content
            page.wait_for_timeout(1000)

            # Get rendered HTML
            html = page.content()

            # Close browser
            browser.close()

            # Parse and return
            return BeautifulSoup(html, "html.parser")

    except Exception as e:
        print(f"Browser error fetching {url}: {str(e)[:100]}")
        return None

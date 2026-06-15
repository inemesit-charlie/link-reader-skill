"""
Headless browser page fetcher using Playwright.
Renders JavaScript-heavy pages and returns full visible text content.
Usage: python fetch_page.py <url>
"""

import sys
from playwright.sync_api import sync_playwright

def fetch_rendered_page(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Extra wait for any deferred rendering
            page.wait_for_timeout(2000)
            content = page.inner_text("body")
            return content
        except Exception as e:
            return f"ERROR: {str(e)}"
        finally:
            browser.close()

if __name__ == "__main__":
    url = sys.argv[1]
    print(fetch_rendered_page(url))

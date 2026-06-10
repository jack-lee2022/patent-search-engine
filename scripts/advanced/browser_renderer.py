"""
browser_renderer.py — Playwright-based browser renderer for Google Patents.

Provides three capabilities:
  1. fetch_api_json(url)      — call XHR API with browser cookies (bypasses 503)
  2. get_patent_detail(id)    — extract PDF URL, claims, images from detail page
  3. render_page(url)         — raw HTML render (backward-compatible)
"""

import json
import time
import random
from typing import Optional, Dict, Any

from playwright.sync_api import sync_playwright, Browser, BrowserContext
try:
    from playwright_stealth import stealth_sync as _stealth
    _HAS_STEALTH = True
except ImportError:
    _HAS_STEALTH = False

# ---------------------------------------------------------------------------
# Internal singleton — reuses one browser context across all calls
# ---------------------------------------------------------------------------

_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_playwright = None
_warmed_up: bool = False

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _get_context() -> BrowserContext:
    global _browser, _context, _playwright
    if _context is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        _context = _browser.new_context(
            user_agent=_UA,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )
    return _context


def _new_stealth_page():
    """Create a new page with stealth patches applied."""
    page = _get_context().new_page()
    if _HAS_STEALTH:
        _stealth(page)
    return page


def _human_delay(lo: float = 1.5, hi: float = 3.5) -> None:
    time.sleep(random.uniform(lo, hi))


def warmup() -> None:
    """Visit patents.google.com to establish session cookies. Called automatically."""
    global _warmed_up
    if _warmed_up:
        return
    page = _new_stealth_page()
    try:
        print("[BROWSER] Warming up session on patents.google.com ...")
        page.goto("https://patents.google.com", wait_until="domcontentloaded", timeout=30000)
        title = page.title()
        if "Sorry" in title:
            print("[BROWSER BLOCKED] Google IP block detected during warmup. "
                  "Wait 30-60 minutes and retry.")
        else:
            _warmed_up = True
            print(f"[BROWSER] Session warmed up (title='{title}').")
    except Exception as e:
        print(f"[BROWSER WARN] warmup failed: {e}")
    finally:
        page.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_api_json(api_url: str) -> Optional[Dict]:
    """
    Use the browser's fetch() with session cookies to call Google Patents XHR API.
    Bypasses the 503 that direct requests.get() receives.
    """
    warmup()
    page = _new_stealth_page()
    try:
        print(f"[BROWSER] fetch_api_json: {api_url[:80]}...")
        # Navigate to patents.google.com so the fetch runs in the right origin
        page.goto("https://patents.google.com", wait_until="domcontentloaded", timeout=30000)
        _human_delay()

        # Use browser's fetch() — carries cookies, correct Origin/Referer
        escaped = api_url.replace('"', '\\"')
        result = page.evaluate(f"""
            async () => {{
                const resp = await fetch("{escaped}", {{
                    headers: {{
                        "Accept": "application/json, text/javascript, */*",
                        "X-Requested-With": "XMLHttpRequest"
                    }},
                    credentials: "include"
                }});
                if (!resp.ok) return null;
                return await resp.json();
            }}
        """)
        return result
    except Exception as e:
        print(f"[BROWSER ERROR] fetch_api_json: {e}")
        return None
    finally:
        page.close()


def get_patent_detail(patent_id: str) -> Optional[Dict[str, Any]]:
    """
    Navigate to a Google Patents detail page and extract structured data:
    pdf_url, claims, description, citation_count, image_urls.
    """
    warmup()
    page = _new_stealth_page()
    url = f"https://patents.google.com/patent/{patent_id}/en"
    try:
        print(f"[BROWSER] get_patent_detail: {patent_id}")
        page.goto(url, wait_until="networkidle", timeout=60000)
        # Detect IP block / CAPTCHA page
        title = page.title()
        if "Sorry" in title or len(page.content()) < 5000:
            print(f"[BROWSER BLOCKED] Google returned bot-detection page for {patent_id}. "
                  f"IP may be temporarily blocked. Wait 30-60 min and retry.")
            return None
        # Wait for Angular to populate meta tags
        try:
            page.wait_for_selector("meta[name='citation_title']", timeout=10000)
        except Exception:
            pass
        _human_delay()

        result: Dict[str, Any] = {}

        # PDF URL — meta[name="citation_pdf_url"]
        pdf_url = page.evaluate("""
            () => {
                const m = document.querySelector("meta[name='citation_pdf_url']");
                return m ? m.content : null;
            }
        """)
        result["pdf_url"] = pdf_url

        # Claims
        claims = page.evaluate("""
            () => {
                const sel = ["div.claims", "section[itemprop='claims']"];
                for (const s of sel) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.length > 50) return el.innerText.trim();
                }
                return null;
            }
        """)
        result["claims"] = claims

        # Description
        desc = page.evaluate("""
            () => {
                const sel = ["section[itemprop='description']", "div.description"];
                for (const s of sel) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.length > 100) return el.innerText.trim();
                }
                return null;
            }
        """)
        result["description"] = desc

        # Image URLs
        image_urls = page.evaluate("""
            () => {
                const imgs = [];
                document.querySelectorAll("li[itemprop='images'] meta[itemprop='full']")
                    .forEach(m => { if (m.content) imgs.push(m.content); });
                return imgs;
            }
        """)
        result["image_urls"] = json.dumps(image_urls) if image_urls else None

        # Citation count
        citation_count = page.evaluate("""
            () => {
                const els = document.querySelectorAll("th, td, div");
                for (const el of els) {
                    if (el.innerText && el.innerText.includes("Patent Citations")) {
                        const parent = el.closest("tr, div, li");
                        if (parent) {
                            const nums = parent.innerText.match(/[0-9]+/);
                            if (nums) return parseInt(nums[0]);
                        }
                    }
                }
                return null;
            }
        """)
        result["citation_count"] = citation_count

        if pdf_url:
            print(f"[BROWSER] {patent_id}: pdf_url={pdf_url[:60]}...")
        else:
            print(f"[BROWSER] {patent_id}: no pdf_url found")

        return result

    except Exception as e:
        print(f"[BROWSER ERROR] get_patent_detail {patent_id}: {e}")
        return None
    finally:
        page.close()


def get_patent_pdf_url(patent_id: str) -> Optional[str]:
    """Convenience wrapper — returns only the PDF URL for a given patent ID."""
    detail = get_patent_detail(patent_id)
    return detail.get("pdf_url") if detail else None


def render_page(url: str) -> Optional[str]:
    """Render a page and return HTML. Kept for backward compatibility."""
    warmup()
    page = _new_stealth_page()
    print(f"[BROWSER] render_page: {url}")
    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
        _human_delay()
        return page.content()
    except Exception as e:
        print(f"[BROWSER ERROR] render_page: {e}")
        return None
    finally:
        page.close()


def close() -> None:
    """Release browser resources. Call when done with all downloads."""
    global _browser, _context, _playwright, _warmed_up
    if _context:
        _context.close()
        _context = None
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None
    _warmed_up = False


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.startswith("US") or arg.startswith("EP"):
            detail = get_patent_detail(arg)
            print(json.dumps(detail, indent=2, ensure_ascii=False))
        else:
            print(render_page(arg))
    close()

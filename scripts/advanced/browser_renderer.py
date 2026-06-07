from playwright.sync_api import sync_playwright

def render_page(url):
    """使用 Playwright 渲染頁面並返回 HTML"""
    print(f"[BROWSER] 正在使用 Playwright 渲染頁面: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # 設置模擬真實用戶的 User-Agent
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            content = page.content()
            browser.close()
            return content
        except Exception as e:
            print(f"[BROWSER ERROR] {e}")
            browser.close()
            return None

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(render_page(sys.argv[1]))

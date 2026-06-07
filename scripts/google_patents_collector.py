#!/usr/bin/env python3
"""
GooglePatentsCollector — Reference implementation for patent-search-engine skill.

Supports:
- XHR API list search (by assignee, keyword, IPC)
- Detail page enrichment (claims, description, citations, images, PDF)
- Patent PDF download
- Tor proxy integration

Usage:
    python google_patents_collector.py --query "tongue pressure" --max 50
    python google_patents_collector.py --assignee "Somnics" --max 25
    python google_patents_collector.py --enrich --limit 50
"""

import argparse
import json
import time
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TOR_ENABLED = True
TOR_PROXY = "socks5://127.0.0.1:9050"
REQUEST_DELAY = 1.0
GOOGLE_PATENTS_URL = "https://patents.google.com/patent"

try:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from advanced.random_delay import human_like_sleep
    HAS_RANDOM_DELAY = True
except ImportError:
    HAS_RANDOM_DELAY = False

# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class GooglePatentsCollector:
    """Collect patents via Google Patents internal XHR API."""

    API_BASE = "https://patents.google.com/xhr/query"

    def __init__(self, tor_enabled: bool = TOR_ENABLED):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        })
        if tor_enabled:
            self.session.proxies = {"http": TOR_PROXY, "https": TOR_PROXY}
            print(f"[COLLECTOR] Tor proxy enabled: {TOR_PROXY}")
        else:
            print("[COLLECTOR] Direct connection (no proxy)")

    def _sleep(self):
        """Execute delay between requests."""
        if HAS_RANDOM_DELAY:
            human_like_sleep(mu=8.0, sigma=3.0)  # Conservative human speed
        else:
            self._sleep()

    # -- URL builders -------------------------------------------------------

    def _build_url(self, assignee: str, page: int = 0, num: int = 25) -> str:
        inner = urllib.parse.urlencode({
            "q": f"assignee:{urllib.parse.quote(assignee)}",
            "language": "ENGLISH",
            "type": "PATENT",
            "num": str(num),
            "page": str(page),
        })
        params = urllib.parse.urlencode({"url": inner})
        return f"{self.API_BASE}?{params}"

    def _build_keyword_url(self, query: str, page: int = 0, num: int = 25) -> str:
        inner = urllib.parse.urlencode({
            "q": query,
            "language": "ENGLISH",
            "type": "PATENT",
            "num": str(num),
            "page": str(page),
        })
        params = urllib.parse.urlencode({"url": inner})
        return f"{self.API_BASE}?{params}"

    def _build_ipc_url(self, ipc_code: str, page: int = 0, num: int = 25) -> str:
        inner = urllib.parse.urlencode({
            "q": f"classification/ipc:{ipc_code}",
            "language": "ENGLISH",
            "type": "PATENT",
            "num": str(num),
            "page": str(page),
        })
        params = urllib.parse.urlencode({"url": inner})
        return f"{self.API_BASE}?{params}"

    # -- Core fetch methods -------------------------------------------------

    def _fetch_page(self, url: str) -> Optional[Dict]:
        try:
            resp = self.session.get(url, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            print(f"[ERROR] Request failed (trying Browser fallback): {e}")
            try:
                from advanced.browser_renderer import render_page
                html_content = render_page(url)
                if html_content:
                    # 嘗試從渲染出的 HTML 中解析 JSON (如果 API 返回的是內嵌 JSON)
                    # 或是返回解析後的結構
                    soup = BeautifulSoup(html_content, "lxml")
                    # Placeholder: 當前僅能解析 HTML 結構或返回 raw html
                    return {"results": {"cluster": []}, "html": html_content}
            except Exception as e2:
                print(f"[CRITICAL ERROR] Fallback failed: {e2}")
            return None

    def _extract_results(self, data: Optional[Dict]) -> List[Dict]:
        if not data:
            return []
        results = data.get("results", {})
        clusters = results.get("cluster", [])
        items = []
        for cluster in clusters:
            for item in cluster.get("result", []):
                items.append(item)
        return items

    # -- Public search methods ----------------------------------------------

    def fetch_list(self, assignee: str, max_results: int = 100) -> List[Dict]:
        all_items, page, per_page = [], 0, 25
        while len(all_items) < max_results:
            url = self._build_url(assignee, page=page, num=per_page)
            data = self._fetch_page(url)
            items = self._extract_results(data)
            if not items:
                break
            all_items.extend(items)
            print(f"[LIST] page {page}: {len(items)} items (total: {len(all_items)})")
            if len(items) < per_page:
                break
            page += 1
            self._sleep()
        return all_items[:max_results]

    def fetch_by_keywords(self, query: str, max_results: int = 100) -> List[Dict]:
        queries = [query] if isinstance(query, str) else query
        all_items, seen_ids = [], set()
        for q in queries:
            page, per_page, query_items = 0, 25, 0
            while len(all_items) < max_results:
                url = self._build_keyword_url(q, page=page, num=per_page)
                data = self._fetch_page(url)
                items = self._extract_results(data)
                if not items:
                    break
                for item in items:
                    pid = item.get("patent", {}).get("publication_number")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        all_items.append(item)
                query_items += len(items)
                if len(items) < per_page:
                    break
                page += 1
                self._sleep()
            print(f"[KEYWORD] query='{q}' contributed {query_items} items")
        return all_items[:max_results]

    def fetch_by_ipc(self, ipc_code: str, max_results: int = 100) -> List[Dict]:
        all_items, page, per_page = [], 0, 25
        while len(all_items) < max_results:
            url = self._build_ipc_url(ipc_code, page=page, num=per_page)
            data = self._fetch_page(url)
            items = self._extract_results(data)
            if not items:
                break
            all_items.extend(items)
            print(f"[IPC] page {page}: {len(items)} items (total: {len(all_items)})")
            if len(items) < per_page:
                break
            page += 1
            self._sleep()
        return all_items[:max_results]

    # -- Search preview & smart search --------------------------------------

    def search_preview(self, query: str) -> dict:
        """Preview total result count for a query without downloading all data.

        Only fetches the first page (1 item) to read the total count from
        Google Patents metadata. Useful for deciding whether to refine keywords.
        """
        url = self._build_keyword_url(query, page=0, num=1)
        data = self._fetch_page(url)
        if not data:
            return {"query": query, "total_found": 0, "warning": False, "error": True}
        results = data.get("results", {})
        total = results.get("total_num_results", 0)
        return {
            "query": query,
            "total_found": total,
            "estimated_pages": (total + 24) // 25,
            "warning": total > 200,
            "error": False,
        }

    def smart_search(self, query: str, max_results: int = 100,
                     relevance_threshold: float = 0.2,
                     auto_limit: bool = True) -> dict:
        """Smart search with preview, refinement suggestions, and relevance filtering.

        Returns:
            dict with keys:
                - status: "preview" | "success" | "error"
                - total_found: int (raw total from Google Patents)
                - items: List[Dict] (only present when status="success")
                - suggestions: List[str] (only present when status="preview")
                - message: str (human-readable status)
        """
        # 1. Preview
        preview = self.search_preview(query)
        if preview.get("error"):
            return {"status": "error", "message": "Preview request failed", "total_found": 0}

        total = preview["total_found"]
        print(f"[SMART SEARCH] Preview: {total} patents for '{query}'")

        # 2. If too many, suggest refinements
        if auto_limit and total > max_results * 2:
            suggestions = self._generate_refinements(query)
            return {
                "status": "preview",
                "total_found": total,
                "message": f"Found {total} patents — too many. Consider refining with one of the suggestions below.",
                "suggestions": suggestions,
            }

        # 3. Fetch and score
        items = self.fetch_by_keywords(query, max_results=max_results)

        # 4. Sort by relevance if keyword_translator available (optional)
        try:
            from result_merger import ResultMerger
            items = ResultMerger.sort_by_relevance(items, [query])
            # Filter by threshold
            scored = [(item, ResultMerger.score_relevance(item, [query])) for item in items]
            items = [item for item, score in scored if score >= relevance_threshold]
        except ImportError:
            pass

        return {
            "status": "success",
            "total_found": total,
            "downloaded": len(items),
            "message": f"Downloaded {len(items)} of {total} patents (sorted by relevance).",
            "items": items,
        }

    @staticmethod
    def _generate_refinements(query: str) -> List[str]:
        """Generate keyword refinement suggestions for overly broad queries."""
        base = query.strip()
        suggestions = []
        # 1. Add device/apparatus qualifier
        if "device" not in base.lower() and "apparatus" not in base.lower():
            suggestions.append(f"{base} device")
            suggestions.append(f"{base} apparatus")
        # 2. Add IPC classification (common medical device class)
        suggestions.append(f"{base} classification/ipc:A61B5/00")
        # 3. Add date filter (last 10 years)
        suggestions.append(f"{base} after:2015-01-01")
        # 4. Add country filter
        suggestions.append(f"{base} country:US")
        # 5. Add method/technology qualifier
        suggestions.append(f"{base} method")
        suggestions.append(f"{base} sensor")
        return suggestions

    # -- Normalization ------------------------------------------------------

    @staticmethod
    def _normalize_list_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        patent = item.get("patent", {})
        pub_num = patent.get("publication_number")
        if not pub_num:
            return None

        country = pub_num[:2] if len(pub_num) >= 2 else "US"
        kind_code = pub_num[-2:] if len(pub_num) >= 2 else ""

        family_size = None
        countries = patent.get("family_metadata", {}).get("aggregated", {}).get("country_status", [])
        if countries:
            family_size = len(countries)

        legal_status = "Unknown"
        if countries:
            active = sum(1 for c in countries if c.get("best_patent_stage", {}).get("state") == "ACTIVE")
            legal_status = "Active" if active > 0 else "Not Active"

        inventors = []
        inv = patent.get("inventor", "")
        if inv:
            inventors = [{"name": inv}]

        assignee_raw = patent.get("assignee", "").replace("<b>", "").replace("</b>", "").strip()
        assignee = assignee_raw if assignee_raw else "Unknown"

        return {
            "patent_id": pub_num,
            "title": patent.get("title", "").strip(),
            "abstract": patent.get("snippet", "").strip(),
            "claims": None,
            "description": None,
            "publication_date": patent.get("publication_date", ""),
            "filing_date": patent.get("filing_date", ""),
            "assignee": assignee,
            "assignee_raw": assignee_raw,
            "inventors": json.dumps(inventors, ensure_ascii=False),
            "country": country,
            "kind_code": kind_code,
            "patent_family_size": family_size,
            "citation_count": None,
            "legal_status": legal_status,
            "source": "google_patents",
            "image_urls": None,      # ⚠️ CRITICAL: must match DB schema
            "pdf_url": None,
            "raw_json": json.dumps(item, ensure_ascii=False),
        }


# ---------------------------------------------------------------------------
# Detail Enricher
# ---------------------------------------------------------------------------

class GooglePatentsDetailEnricher:
    """Scrape claims, description, citations, images, PDF from detail pages."""

    def __init__(self, tor_enabled: bool = TOR_ENABLED):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })
        if tor_enabled:
            self.session.proxies = {"http": TOR_PROXY, "https": TOR_PROXY}

    def fetch_detail(self, patent_id: str) -> Optional[Dict[str, Any]]:
        url = f"{GOOGLE_PATENTS_URL}/{patent_id}/en"
        try:
            resp = self.session.get(url, timeout=40)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[DETAIL ERROR] {patent_id}: {e}")
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        result = {}

        # Claims
        claims = None
        for sel in ["div.claims", "section[itemprop='claims']"]:
            elem = soup.select_one(sel)
            if elem:
                text = elem.get_text(separator="\n", strip=True)
                if len(text) > 50:
                    claims = text
                    break
        result["claims"] = claims

        # Description
        desc = None
        for sel in ["section[itemprop='description']", "div.description"]:
            elem = soup.select_one(sel)
            if elem:
                text = elem.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    desc = text
                    break
        result["description"] = desc

        # Citation count
        citation_count = None
        for th in soup.find_all(["th", "td", "div"]):
            text = th.get_text(strip=True)
            if "Patent Citations" in text or "patent citations" in text.lower():
                parent = th.find_parent(["tr", "div", "li"])
                if parent:
                    nums = [s for s in parent.stripped_strings if s.isdigit()]
                    if nums:
                        citation_count = int(nums[0])
                        break
        result["citation_count"] = citation_count

        # Image URLs
        image_urls = []
        for li in soup.find_all("li", attrs={"itemprop": "images"}):
            meta = li.find("meta", attrs={"itemprop": "full"})
            if meta and meta.get("content"):
                image_urls.append(meta["content"])
        result["image_urls"] = json.dumps(image_urls) if image_urls else None

        # PDF URL
        pdf_url = None
        meta_pdf = soup.find("meta", attrs={"name": "citation_pdf_url"})
        if meta_pdf and meta_pdf.get("content"):
            pdf_url = meta_pdf["content"]
        result["pdf_url"] = pdf_url

        return result


# ---------------------------------------------------------------------------
# PDF Downloader
# ---------------------------------------------------------------------------

class PatentPDFDownloader:
    """Download patent PDFs from Google Patents."""

    def __init__(self, pdf_dir: Optional[Path] = None):
        self.pdf_dir = pdf_dir or Path("pdfs")
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    def download(self, patent_id: str, pdf_url: Optional[str] = None) -> Optional[Path]:
        pdf_path = self.pdf_dir / f"{patent_id}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            print(f"[PDF] {patent_id}: already exists")
            return pdf_path

        if not pdf_url:
            enricher = GooglePatentsDetailEnricher(tor_enabled=False)
            detail = enricher.fetch_detail(patent_id)
            if detail:
                pdf_url = detail.get("pdf_url")
        if not pdf_url:
            print(f"[PDF] {patent_id}: no PDF URL")
            return None

        try:
            resp = self.session.get(pdf_url, timeout=120)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").lower() != "application/pdf":
                print(f"[PDF] {patent_id}: unexpected content-type")
                return None
            if len(resp.content) < 1000:
                print(f"[PDF] {patent_id}: too small")
                return None
            pdf_path.write_bytes(resp.content)
            print(f"[PDF] {patent_id}: downloaded {len(resp.content)} bytes")
            return pdf_path
        except requests.RequestException as e:
            print(f"[PDF ERROR] {patent_id}: {e}")
            return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google Patents Collector")
    parser.add_argument("--query", "-q", help="Keyword query")
    parser.add_argument("--assignee", "-a", help="Assignee name")
    parser.add_argument("--ipc", "-i", help="IPC/CPC classification code")
    parser.add_argument("--max", "-m", type=int, default=100, help="Max results")
    parser.add_argument("--enrich", action="store_true", help="Enrich first N patents")
    parser.add_argument("--limit", "-l", type=int, default=50, help="Enrichment limit")
    parser.add_argument("--no-tor", action="store_true", help="Disable Tor proxy")
    args = parser.parse_args()

    tor = not args.no_tor
    collector = GooglePatentsCollector(tor_enabled=tor)

    if args.query:
        items = collector.fetch_by_keywords(args.query, max_results=args.max)
        print(f"\nTotal items: {len(items)}")
        for item in items[:5]:
            p = item.get("patent", {})
            print(f"  {p.get('publication_number')}: {p.get('title', '')[:60]}")

    elif args.assignee:
        items = collector.fetch_list(args.assignee, max_results=args.max)
        print(f"\nTotal items: {len(items)}")
        for item in items[:5]:
            p = item.get("patent", {})
            print(f"  {p.get('publication_number')}: {p.get('title', '')[:60]}")

    elif args.ipc:
        items = collector.fetch_by_ipc(args.ipc, max_results=args.max)
        print(f"\nTotal items: {len(items)}")
        for item in items[:5]:
            p = item.get("patent", {})
            print(f"  {p.get('publication_number')}: {p.get('title', '')[:60]}")

    elif args.enrich:
        enricher = GooglePatentsDetailEnricher(tor_enabled=tor)
        # NOTE: requires PatentDB integration; placeholder here
        print("Enrichment mode requires PatentDB. See skill documentation.")
    else:
        parser.print_help()

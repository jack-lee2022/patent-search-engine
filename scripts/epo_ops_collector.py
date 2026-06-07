#!/usr/bin/env python3
"""
EPOOPSCollector — EPO Open Patent Services API integration.

Official, stable alternative to Google Patents scraping.
Use when Google Patents returns 503 from cloud VMs.

Usage:
    export EPO_OPS_CLIENT_ID="your_client_id"
    export EPO_OPS_CLIENT_SECRET="your_client_secret"
    python epo_ops_collector.py "ti=sleep apnea"

Or import into your project:
    from scripts.epo_ops_collector import EPOOPSCollector
    collector = EPOOPSCollector(client_id, client_secret)
    items = collector.search("ti=sleep apnea", max_results=50)
    for item in items:
        norm = collector._normalize_item(item)
        db.insert_patent(norm)
"""

import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import requests


class EPOOPSCollector:
    """Collect patents via EPO Open Patent Services (OPS) REST API."""

    AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
    SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"
    RETRIEVAL_URL = "https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc"

    # Rate limits: 1,000/week, ~4/min
    REQUEST_DELAY = 15.0
    MAX_PER_REQUEST = 100

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PatentSearchEngine/1.0",
        })
        self._refresh_token()

    # ── Authentication ────────────────────────────────────────────────────

    def _refresh_token(self) -> None:
        """Obtain OAuth 2.0 access token via client credentials flow."""
        auth = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        try:
            resp = self.session.post(
                self.AUTH_URL,
                headers={"Authorization": f"Basic {auth}"},
                data={"grant_type": "client_credentials"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self.token = data["access_token"]
            expires_in = data.get("expires_in", 1200)
            self.token_expires = datetime.utcnow() + timedelta(seconds=expires_in - 60)
            print(f"[EPO OPS] Token refreshed, expires in {expires_in}s")
        except requests.RequestException as e:
            print(f"[EPO OPS ERROR] Token refresh failed: {e}")
            raise
        except (KeyError, json.JSONDecodeError) as e:
            print(f"[EPO OPS ERROR] Invalid token response: {e}")
            raise

    def _ensure_token(self) -> None:
        """Refresh token if expired or about to expire."""
        if not self.token or (self.token_expires and datetime.utcnow() >= self.token_expires):
            self._refresh_token()

    def _get_auth_header(self) -> Dict[str, str]:
        """Return Authorization header with current token."""
        self._ensure_token()
        return {"Authorization": f"Bearer {self.token}"}

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search patents via EPO OPS.

        Args:
            query: EPO OPS query string (e.g. "ti=sleep apnea", "pa=Somnics")
            max_results: Max patents to return (1-100)

        Returns:
            List of raw EPO OPS exchange-document items
        """
        all_items = []
        per_page = min(self.MAX_PER_REQUEST, max_results)
        start = 1

        while len(all_items) < max_results:
            end = min(start + per_page - 1, max_results)
            range_header = f"{start}-{end}"

            try:
                resp = self.session.get(
                    self.SEARCH_URL,
                    headers=self._get_auth_header(),
                    params={"q": query, "Range": range_header},
                    timeout=60,
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"[EPO OPS SEARCH ERROR] {e}")
                break

            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining:
                print(f"[EPO OPS] Rate limit remaining: {remaining}")

            data = resp.json()
            items = self._extract_items(data)
            if not items:
                break

            all_items.extend(items)
            print(f"[EPO OPS] Range {range_header}: {len(items)} items (total: {len(all_items)})")

            if len(items) < per_page:
                break

            start += per_page
            time.sleep(self.REQUEST_DELAY)

        return all_items[:max_results]

    def _extract_items(self, data: Dict) -> List[Dict]:
        """Extract patent items from EPO OPS JSON response."""
        try:
            root = data.get("ops:world-patent-data", {})
            biblio = root.get("ops:biblio-search", {})
            result = biblio.get("ops:search-result", {})
            docs = result.get("ops:exchange-documents", [])
            if not isinstance(docs, list):
                docs = [docs] if docs else []
            return [d.get("ops:exchange-document", {}) for d in docs if d]
        except Exception as e:
            print(f"[EPO OPS ERROR] Failed to extract items: {e}")
            return []

    # ── Search Preview ────────────────────────────────────────────────────

    def search_preview(self, query: str) -> dict:
        """Preview total result count for an EPO OPS query.

        Fetches only the first 1-item range to read the total count from
        the response metadata, without consuming the full rate limit.
        """
        try:
            resp = self.session.get(
                self.SEARCH_URL,
                headers=self._get_auth_header(),
                params={"q": query, "Range": "1-1"},
                timeout=60,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[EPO OPS PREVIEW ERROR] {e}")
            return {"query": query, "total_found": 0, "warning": False, "error": True}

        data = resp.json()
        try:
            root = data.get("ops:world-patent-data", {})
            biblio = root.get("ops:biblio-search", {})
            total = int(biblio.get("@total-result-count", 0))
        except (ValueError, TypeError):
            total = 0

        return {
            "query": query,
            "total_found": total,
            "estimated_pages": (total + 99) // 100,
            "warning": total > 200,
            "error": False,
        }

    # ── Query Builder ─────────────────────────────────────────────────────

    @staticmethod
    def build_query(keywords: List[str], assignee: Optional[str] = None,
                    date_from: Optional[str] = None, date_to: Optional[str] = None) -> str:
        """
        Build EPO OPS query string from keyword list and optional filters.

        Args:
            keywords: List of English keywords
            assignee: Optional applicant name
            date_from: Optional filing date from (YYYY)
            date_to: Optional filing date to (YYYY)

        Returns:
            EPO OPS query string
        """
        keyword_clauses = []
        for kw in keywords:
            keyword_clauses.append(f"ti={kw}")
            keyword_clauses.append(f"ab={kw}")

        keyword_clauses = list(dict.fromkeys(keyword_clauses))
        query_parts = [f"({' OR '.join(keyword_clauses)})"]

        if assignee:
            query_parts.append(f"pa={assignee}")

        if date_from:
            query_parts.append(f"pd>={date_from}")
        if date_to:
            query_parts.append(f"pd<={date_to}")

        return " AND ".join(query_parts)

    # ── Normalization (EPO OPS → Google Patents Schema) ───────────────────

    @staticmethod
    def _normalize_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert EPO OPS exchange-document into Google Patents-compatible schema.
        """
        if not item:
            return None

        biblio = item.get("ops:bibliographic-data", {})

        # Publication number
        pub_ref = biblio.get("publication-reference", {})
        doc_ids = pub_ref.get("document-id", [])
        if not isinstance(doc_ids, list):
            doc_ids = [doc_ids] if doc_ids else []

        pub_doc_id = None
        for did in doc_ids:
            if isinstance(did, dict) and did.get("kind"):
                pub_doc_id = did
                break
        if not pub_doc_id and doc_ids:
            pub_doc_id = doc_ids[0]

        if not pub_doc_id:
            return None

        country = pub_doc_id.get("country", "")
        doc_number = pub_doc_id.get("doc-number", "")
        kind = pub_doc_id.get("kind", "")
        patent_id = f"{country}{doc_number}{kind}" if kind else f"{country}{doc_number}"

        # Title
        title = ""
        titles = biblio.get("invention-title", [])
        if not isinstance(titles, list):
            titles = [titles] if titles else []
        for t in titles:
            if isinstance(t, dict):
                lang = t.get("@lang", "")
                text = t.get("$", "")
                if lang == "en" or not title:
                    title = text
                if lang == "en":
                    break

        # Abstract
        abstract = ""
        abstracts = biblio.get("abstract", [])
        if not isinstance(abstracts, list):
            abstracts = [abstracts] if abstracts else []
        for ab in abstracts:
            if isinstance(ab, dict):
                lang = ab.get("@lang", "")
                p = ab.get("p", {})
                text = p.get("$", "") if isinstance(p, dict) else ""
                if not text and isinstance(p, list):
                    text = " ".join(x.get("$", "") for x in p if isinstance(x, dict))
                if lang == "en" or not abstract:
                    abstract = text
                if lang == "en":
                    break

        # Assignee
        assignee = "Unknown"
        parties = biblio.get("parties", {})
        applicants = parties.get("applicants", {}).get("applicant", [])
        if not isinstance(applicants, list):
            applicants = [applicants] if applicants else []
        for app in applicants:
            if isinstance(app, dict):
                name = app.get("addressbook", {}).get("name", {}).get("$", "")
                if name:
                    assignee = name
                    break

        # Dates
        pub_date = ""
        for did in doc_ids:
            if isinstance(did, dict) and did.get("date"):
                d = did["date"]
                if len(d) == 8:
                    pub_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                break

        filing_date = ""
        app_ref = biblio.get("application-reference", {})
        app_docs = app_ref.get("document-id", [])
        if not isinstance(app_docs, list):
            app_docs = [app_docs] if app_docs else []
        for did in app_docs:
            if isinstance(did, dict) and did.get("date"):
                d = did["date"]
                if len(d) == 8:
                    filing_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                break

        # Inventors
        inventors = []
        inv_list = parties.get("inventors", {}).get("inventor", [])
        if not isinstance(inv_list, list):
            inv_list = [inv_list] if inv_list else []
        for inv in inv_list:
            if isinstance(inv, dict):
                name = inv.get("addressbook", {}).get("name", {}).get("$", "")
                if name:
                    inventors.append({"name": name})

        # Family size
        family_size = None
        family = biblio.get("patent-family", {})
        members = family.get("family-member", [])
        if not isinstance(members, list):
            members = [members] if members else []
        if members:
            family_size = len(members)

        # Classifications
        classifications = []
        ipc_section = biblio.get("classifications-ipcr", {}).get("classification-ipcr", [])
        if not isinstance(ipc_section, list):
            ipc_section = [ipc_section] if ipc_section else []
        for c in ipc_section:
            if isinstance(c, dict):
                text = c.get("text", {}).get("$", "")
                if text:
                    classifications.append(text)

        return {
            "patent_id": patent_id,
            "title": title.strip(),
            "abstract": abstract.strip(),
            "claims": None,
            "description": None,
            "publication_date": pub_date,
            "filing_date": filing_date,
            "assignee": assignee,
            "assignee_raw": assignee,
            "inventors": json.dumps(inventors, ensure_ascii=False),
            "country": country,
            "kind_code": kind,
            "patent_family_size": family_size,
            "citation_count": None,
            "legal_status": "Unknown",
            "source": "epo_ops",
            "image_urls": None,
            "pdf_url": None,
            "raw_json": json.dumps(item, ensure_ascii=False),
            "classifications": json.dumps(classifications, ensure_ascii=False),
            "epo_ops_doc_number": doc_number,
        }

    # ── Document Retrieval ────────────────────────────────────────────────

    def fetch_bibliography(self, patent_id: str) -> Optional[Dict]:
        """Retrieve full bibliography for a patent by EPODOC number."""
        self._ensure_token()
        try:
            resp = self.session.get(
                f"{self.RETRIEVAL_URL}/{patent_id}/biblio",
                headers=self._get_auth_header(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"[EPO OPS RETRIEVAL ERROR] {patent_id}: {e}")
            return None

    # ── Image & PDF URLs ──────────────────────────────────────────────────

    @staticmethod
    def get_image_url(country: str, doc_number: str, kind: str, page: int = 1) -> str:
        """Build EPO OPS image URL for patent drawings."""
        return f"https://ops.epo.org/3.2/rest-services/published-data/images/{country}/{doc_number}/{kind}/{page}.pdf"

    @staticmethod
    def get_pdf_url(country: str, doc_number: str, kind: str) -> str:
        """Build EPO OPS PDF URL."""
        return f"https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc/{country}{doc_number}{kind}/pdf"


# ── Standalone test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    client_id = os.getenv("EPO_OPS_CLIENT_ID", "")
    client_secret = os.getenv("EPO_OPS_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("Usage: EPO_OPS_CLIENT_ID=xxx EPO_OPS_CLIENT_SECRET=xxx python epo_ops_collector.py <query>")
        print("Example: EPO_OPS_CLIENT_ID=xxx EPO_OPS_CLIENT_SECRET=xxx python epo_ops_collector.py 'ti=sleep apnea'")
        sys.exit(1)

    query = sys.argv[1] if len(sys.argv) > 1 else "ti=sleep apnea"

    collector = EPOOPSCollector(client_id, client_secret)
    items = collector.search(query, max_results=10)

    print(f"\nFound {len(items)} patents")
    for item in items:
        norm = collector._normalize_item(item)
        if norm:
            print(f"  {norm['patent_id']}: {norm['title'][:60]} ({norm['country']})")

---
name: patent-search-engine
description: >
  Multi-source patent search engine skill focused on Google Patents (primary) with
  EPO OPS fallback. Use this skill whenever the user asks to search patents,
  collect patent data, scrape Google Patents, bypass patent site IP blocking,
  build a patent collector, or set up patent search infrastructure. Also trigger
  when the user mentions patent landscape, prior art search, patent scraping,
  patent XHR API, or Google Patents anti-scraping. This skill covers keyword
  translation, entity extraction, proxy management (Tor), result merging,
  deduplication, and structured storage. Always consult this skill before
  attempting to write any patent collection code from scratch.
category: patent-agent
version: 1.0.0
---

# Patent Search Engine

## Overview

A reproducible, multi-source patent search pipeline. **Primary source**: Google Patents
internal XHR API. **Planned fallback**: EPO Open Patent Services (OPS).

This skill encapsulates everything learned from production use on Oracle Cloud VMs
(where Google Patents actively blocks cloud IPs), including all known pitfalls,
workarounds, and architectural patterns.

---

## When to Use

- Building a new patent collection pipeline from scratch
- Google Patents returns 503 / 429 / reCAPTCHA from a cloud VM
- Need to translate Chinese patent topics into English search queries
- Need to extract company names / product names from topic text for assignee search
- Need to merge results from multiple queries while deduplicating by patent family
- Need to download patent PDFs or figure images from Google Patents
- Setting up Tor proxy for patent scraping

---

## Architecture

```
User Topic (Chinese or English)
    ↓
KeywordTranslator ──→ LLM translation + Entity extraction + Manual fallback map
    ↓
Search Queries ──→ [technical keywords] + [entity:CompanyName] markers
    ↓
ProxyManager ──→ Tor SOCKS5 rotation / direct / future: residential proxy
    ↓
GooglePatentsCollector ──→ XHR API (list + detail + images + PDF)
    ↓
ResultMerger ──→ Cross-query dedup + relevance scoring + family aggregation
    ↓
PatentDB ──→ SQLite with ON CONFLICT upsert
    ↓
Enricher ──→ Claims, description, citation count, image URLs, PDF URL
```

---

## Core Components

### 1. GooglePatentsCollector

**API endpoint**: `https://patents.google.com/xhr/query`

**URL construction rule (CRITICAL)**:
The `url` parameter accepts an **inner query string**. Do **NOT** double-encode:

```python
# CORRECT
inner = urllib.parse.urlencode({
    "q": query,
    "language": "ENGLISH",
    "type": "PATENT",
    "num": str(num),
    "page": str(page),
})
params = urllib.parse.urlencode({"url": inner})

# WRONG (double-encodes)
encoded_query = urllib.parse.quote(query)
params = urllib.parse.urlencode({
    "url": f"q={encoded_query}&language=ENGLISH..."
})
```

**Verify**:
```python
parsed = urllib.parse.parse_qs(urllib.parse.parse_qs(parsed.query)['url'][0])
assert 'q' in parsed
```

**Search methods**:
- `fetch_list(assignee, ...)` — by assignee name
- `fetch_by_keywords(query, ...)` — by keyword(s), supports single string or list
- `fetch_by_ipc(ipc_code, ...)` — by IPC/CPC classification

**Session headers**:
```python
{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ... Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
```

**Rate limiting**: 0.5–1.0s delay between requests. Use `time.sleep(REQUEST_DELAY)`.

---

### 2. KeywordTranslator

**Four-layer fallback strategy**:

| Layer | Mechanism | When it triggers |
|-------|-----------|------------------|
| 1 | Entity extraction (regex) | Always — extracts company/product names |
| 2 | English passthrough | Topic has <30% CJK characters |
| 3 | SQLite cache | Exact topic match exists |
| 4 | Manual keyword map | `MANUAL_KEYWORD_MAP` has matching key |
| 5 | LLM translation (NVIDIA NIM) | All above miss — calls `meta/llama-3.3-70b-instruct` |

**Entity extraction rules**:

```python
def extract_entities(topic: str) -> List[str]:
    entities = []
    # 1. All-caps acronyms (2-6 letters), but filter common non-entities
    for match in re.finditer(r'(?<![A-Za-z])[A-Z]{2,6}(?![A-Za-z])', topic):
        candidate = match.group()
        if candidate not in {"PDF", "URL", "HTTP", "HTML", "API", "JSON",
                             "USA", "UK", "EU", "JP", "CN", "TW", "US", "EN",
                             "MD", "PHD", "ETC", "VS", "IP", "AI", "IoT"}:
            entities.append(candidate)

    # 2. English phrases inside parentheses
    paren_pattern = re.findall(
        r'[\(（]([A-Za-z][A-Za-z0-9\s\-/]+(?:Device|System|Apparatus|Instrument|'
        r'Meter|Gauge|Tool|Method|Technology|Ltd|Limited|Inc|Co\.?|Corp\.?|'
        r'LLC|GmbH|AG|KK|株式会社)?)[\)）]',
        topic
    )

    # 3. Capitalized word groups (product/brand names)
    for match in re.finditer(r'\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*){1,3})\b', topic):
        candidate = match.group()
        if candidate.lower() not in {"the", "and", "for", "with", "from", "this", "that"}:
            if len(candidate) > 3:
                entities.append(candidate)

    # Deduplicate preserving order
    seen = set()
    return [e for e in entities if not (e.lower() in seen or seen.add(e.lower()))]
```

**⚠️ CRITICAL BUG PATTERN**: When adding new features that modify the return value
of `translate()`, audit **ALL** return paths (cache hit, manual fallback, LLM path,
error fallback). Cached translations created before the feature will lack the new
keys. Always re-attach entities on cache hit.

```python
# CORRECT — cache hit re-attaches entities
cached = self._get_cache(topic)
if cached:
    result = list(cached)
    entities = self.extract_entities(topic)
    for e in entities:
        marker = f"entity:{e}"
        if marker not in result:
            result.append(marker)
    return result
```

**Entity marker convention**:
```python
queries = [
    "tongue pressure measurement",
    "tongue pressure meter",
    "entity:JMS",          # ← routed to assignee search
    "entity:ResMed",       # ← routed to assignee search
]
```

---

### 3. ProxyManager

**Tor setup**:
```bash
sudo dnf install -y tor
sudo systemctl enable --now tor
# Verify: ss -tlnp | grep 9050
```

**Configuration**:
```python
TOR_ENABLED = True
TOR_PROXY = "socks5://127.0.0.1:9050"

session.proxies = {
    "http": TOR_PROXY,
    "https": TOR_PROXY,
}
```

**⚠️ LIMITATION**: Tor is a free workaround but unreliable. Google Patents may still
block some Tor exit nodes. For production, consider Bright Data / ScrapingBee
residential proxies (not included in this skill yet).

**Proxy rotation strategy** (if implementing):
- Maintain a pool of 3–5 Tor circuits
- On 503/429, rotate circuit via `torctl` or restart Tor
- Track per-circuit success rate, blacklist failing exits

---

### 4. ResultMerger

**Dual-track search strategy** (when entities detected):

| Strategy | Logic | When to use |
|----------|-------|-------------|
| **OR (union)** | `keyword_ids ∪ assignee_ids` | Broad discovery, risk of noise |
| **Hard AND** | `keyword_ids ∩ assignee_ids` | When terminology is consistent |
| **Weak AND (recommended)** | `assignee search` → local `_filter_by_keywords()` | Tolerates terminology drift (e.g., "tongue pressure" vs "oral cavity pressure") |

**Weak AND implementation**:
```python
def _filter_by_keywords(items, keywords, threshold=1):
    keyword_words = set()
    for kw in keywords:
        keyword_words.update(w.lower() for w in kw.split() if len(w) > 2)
    filtered = []
    for item in items:
        text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
        match_count = sum(1 for w in keyword_words if w in text)
        if match_count >= threshold:
            filtered.append(item)
    return filtered
```

**Why this works for terminology drift**:
- Keywords: `["tongue pressure measurement", "oral pressure sensor"]`
- Keyword words: `{"tongue", "pressure", "measurement", "oral", "sensor"}`
- JMS patent title: `"Balloon for measuring pressure related to oral cavity"`
- Matches: `"pressure"`, `"oral"` → `match_count = 2 ≥ threshold=1` → **kept** ✅

**Deduplication**:
```python
seen = set()
unique = []
for item in items:
    pid = item.get("patent", {}).get("publication_number")
    if pid and pid not in seen:
        seen.add(pid)
        unique.append(item)
```

---

### 5. PatentDB (SQLite)

**Schema** (`patents` table):
```sql
CREATE TABLE patents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patent_id TEXT UNIQUE NOT NULL,
    title TEXT,
    abstract TEXT,
    claims TEXT,
    description TEXT,
    publication_date TEXT,
    filing_date TEXT,
    assignee TEXT,
    assignee_raw TEXT,
    inventors TEXT,        -- JSON array
    country TEXT,
    kind_code TEXT,
    patent_family_size INTEGER,
    citation_count INTEGER,
    legal_status TEXT,
    source TEXT DEFAULT 'google_patents',
    image_urls TEXT,       -- JSON array of figure URLs
    pdf_url TEXT,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**Upsert pattern** (critical for idempotency):
```sql
INSERT INTO patents (...) VALUES (...)
ON CONFLICT(patent_id) DO UPDATE SET
    title=excluded.title,
    ...
    image_urls=COALESCE(excluded.image_urls, patents.image_urls),
    ...
```

**⚠️ CRITICAL BUG**: `INSERT` SQL lists `image_urls` column, but `_normalize_list_item()`
must return `"image_urls": None` in its dict. If the key is missing, SQLite parameter
binding fails silently → `insert_patent()` returns False → 0 patents stored → downstream
"LLM analysis failed" even though the search found results.

**Always audit dict keys against INSERT SQL columns after any schema change.**

---

## Execution Flow

### Standard Search (No Entities)
```
1. translate(topic) → [keyword1, keyword2, ...]
2. fetch_by_keywords(keywords, max_results=100)
3. normalize_list_item() for each result
4. insert_patent() into DB
5. enrich() claims/description for patents missing claims
```

### Entity-Aware Search (e.g., "JMS舌壓測定儀")
```
1. translate(topic) → [keywords..., "entity:JMS", ...]
2. Split into keyword_queries and entity_queries
3. Run fetch_by_keywords(keyword_queries)
4. Run fetch_list(assignee="JMS") → filter by _filter_by_keywords()
5. Merge and deduplicate by patent_id
6. normalize + insert
7. enrich
```

---

## Known Pitfalls & Solutions

| Pitfall | Root Cause | Solution |
|---------|-----------|----------|
| **Google Patents 503 from cloud VM** | IP range blacklisted | Use Tor proxy; or EPO OPS (future); or residential proxy |
| **URL double-encoding in XHR API** | Calling `quote()` then `urlencode()` | Build inner query with `urlencode()`, wrap once |
| **SOTA still uses assignee search** | Added `fetch_by_keywords` but forgot to update mode consumer | Audit all mode files after adding new collector methods |
| **Missing class alias breaks import** | Class named `StateOfTheArtSearch` but `__init__.py` exports `SOTASearch` | Add `SOTASearch = StateOfTheArtSearch` alias |
| **Cache hit loses entity markers** | Old cache entries lack new keys | Re-attach entities on every cache hit |
| **Empty-result dict missing keys** | Early return omits `patent_ids` | Add ALL expected keys to every return path |
| **Insert fails silently (0 patents)** | `_normalize_list_item()` missing `image_urls` key | Add key; audit dict keys vs SQL columns; add fatal log when `inserted == 0` |
| **Google Patents detail page changes class names** | HTML scraping fragility | Use multiple selectors with fallback; prefer XHR API for list data |
| **Japanese text in claims** | JP/EN interleaved in Google Patents | ASCII-ratio filter (≥30%) removes JP lines |
| **Spanish/French dependent claims misclassified** | Regex only catches English "according to claim" | Extend regex for `según la reivindicación`, `selon la revendication` |
| **LLM key missing in poller** | Key only in `~/.bashrc`, not `.env` | Centralize all secrets in `.env` with Python-level fallback loader |
| **Tor too slow for batch downloads** | 500KB PDF over Tor = 30s+ | Download PDFs directly (no proxy) if Google Patents CDN works; CDN often bypasses WAF |
| **Assignee search noise** | `fetch_list(assignee="JMS")` returns ALL 50 patents, only 2 relevant | Use `_filter_by_keywords()` with threshold=1; or LLM relevance scoring |
| **JSON not serializable** | numpy int32 from sklearn | Cast all numpy scalars: `int(x)`, `str(x)` before `json.dump` |

---

## Multi-Source Extension (Future: EPO OPS)

**Architecture is already designed for multi-source**:

```python
class BaseCollector(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 100) -> List[Dict]: ...

class GooglePatentsCollector(BaseCollector): ...
class EPOOPSCollector(BaseCollector): ...
class LensOrgCollector(BaseCollector): ...
```

**EPO OPS** (to be implemented):
- Register: https://developers.epo.org/
- Free tier: 1,000 requests/week
- OAuth 2.0 (Client ID + Secret)
- Endpoint: `https://ops.epo.org/3.2/rest-services/published-data/search`

**Why EPO OPS is the right fallback**:
- Official API (no scraping fragility)
- Global coverage (DOCDB database)
- Not blocked from Oracle VMs (verified)
- Patent images via separate endpoint

**Data source priority** (configurable):
```python
SOURCE_PRIORITY = ["epo_ops", "google_patents", "lens_org"]
```

---

## Report Generation

After collection, generate a structured Markdown report:

```markdown
# Patent Search Report: {topic}

## Search Method
- Keyword search: {queries}
- Assignee search: {entities} (if any)
- Total patents found: {count}
- Total unique stored: {stored}

## Key Players
| Assignee | Patents | Relevant |
|----------|---------|----------|
| ... | ... | ... |

## Sample Results
| Patent ID | Title | Date | Assignee |
|-----------|-------|------|----------|
| ... | ... | ... | ... |

## Data Quality
- With abstract: {N} ({pct}%)
- With claims: {N} ({pct}%)
- Date range: {min} to {max}
```

Use the template in `templates/search_report_template.md`.

---

## Reference Files

- `references/google_patents_api.md` — XHR API internals, URL formats, response schema
- `references/anti_scraping.md` — Google Patents blocking mechanisms, detection methods, evasion strategies
- `references/epo_ops.md` — EPO OPS API docs (placeholder for future)

---

## Scripts

- `scripts/google_patents_collector.py` — Reference implementation of collector
- `scripts/keyword_translator.py` — Reference implementation of translator
- `scripts/proxy_manager.py` — Tor setup, rotation, health check
- `scripts/result_merger.py` — Deduplication, filtering, relevance scoring
- `scripts/search_report.py` — Report generator from DB

---

## Example Usage

```python
from core.config import TOR_ENABLED, REQUEST_DELAY
from core.collector import GooglePatentsCollector
from core.keyword_translator import KeywordTranslator
from core.database import PatentDB

db = PatentDB()
translator = KeywordTranslator()
collector = GooglePatentsCollector()

# Example 1: Chinese topic → English keywords → search
topic = "舌肌力訓練"
queries = translator.translate(topic)
# → ['tongue strength training', 'tongue muscle exercise', ...]

items = collector.fetch_by_keywords(queries, max_results=100)
for item in items:
    norm = collector._normalize_list_item(item)
    if norm:
        db.insert_patent(norm)

# Example 2: Entity-aware search
topic = "JMS舌壓測定儀"
queries = translator.translate(topic)
# → ['tongue pressure measurement', 'entity:JMS', ...]

# Run dual-track search in the mode consumer
# (see ResultMerger section above)

# Example 3: Enrich missing claims
from core.collector import GooglePatentsDetailEnricher
enricher = GooglePatentsDetailEnricher()
enricher.enrich(db, limit=50)
```

---

## Environment Notes

- **Python**: 3.10+
- **Package manager**: `uv` (preferred over system pip)
- **Required packages**: `requests`, `beautifulsoup4`, `lxml`, `urllib3`
- **Optional**: `pymupdf` (PDF extraction), `pytesseract` + `pdf2image` (OCR for scanned PDFs)
- **Tor**: `sudo dnf install -y tor && sudo systemctl enable --now tor`
- **VM-specific**: Oracle Cloud Rocky Linux ARM64 cannot run Playwright browsers natively — use `requests` + BeautifulSoup, not browser automation

---

## Version History

- **v1.0.0** (2026-06-07): Google Patents primary, Tor proxy, keyword translation,
  entity extraction, dual-track search, result merging, SQLite storage.
  EPO OPS placeholder for future integration.

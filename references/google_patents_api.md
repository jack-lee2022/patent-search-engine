# Google Patents XHR API Reference

## Endpoint

```
https://patents.google.com/xhr/query
```

This is **NOT** an official public API. It is an internal XHR endpoint used by
the Google Patents web frontend. Google actively blocks automated access,
especially from cloud provider IP ranges (Oracle, AWS, Azure).

---

## Request Format

### URL Parameter: `url`

The `url` parameter contains an **inner query string** that Google Patents
parses server-side. The inner string uses standard `application/x-www-form-urlencoded`
format.

```
GET https://patents.google.com/xhr/query?url=q%3Dtongue%2Bpressure%26language%3DENGLISH%26type%3DPATENT%26num%3D25%26page%3D0
```

**Construction**:
```python
import urllib.parse

inner = urllib.parse.urlencode({
    "q": query,
    "language": "ENGLISH",
    "type": "PATENT",
    "num": str(num),
    "page": str(page),
})
params = urllib.parse.urlencode({"url": inner})
url = f"https://patents.google.com/xhr/query?{params}"
```

### Inner Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (see query syntax below) |
| `language` | string | `ENGLISH` (or `CHINESE`, `JAPANESE`, etc.) |
| `type` | string | `PATENT` or `APPLICATION` |
| `country` | string | `US`, `EP`, `JP`, `CN`, `TW`, etc. |
| `num` | int | Results per page (max 100) |
| `page` | int | 0-indexed page number |
| `sort` | string | `new` (by date) or `relevance` |
| `before` | string | `filing:YYYY-MM-DD` |
| `after` | string | `filing:YYYY-MM-DD` |

### Query Syntax (`q` parameter)

| Syntax | Example | Description |
|--------|---------|-------------|
| Plain text | `sleep apnea` | Full-text search |
| Assignee | `assignee:Somnics` | By company name |
| Inventor | `inventor:John Smith` | By inventor name |
| Classification | `classification/ipc:A61B5/00` | IPC/CPC code |
| Patent number | `patent/US11311692B2` | Exact match |
| Before date | `before:filing:2020-01-01` | Filing before date |
| After date | `after:filing:2020-01-01` | Filing after date |

**Combined queries**:
```
q=assignee:Somnics+sleep+apnea+before:filing:2020-01-01
```

---

## Response Format

```json
{
  "results": {
    "total_num_results": 123,
    "cluster": [
      {
        "result": [
          {
            "patent": {
              "publication_number": "US11311692B2",
              "title": "System and method for treating sleep apnea",
              "snippet": "Abstract snippet...",
              "publication_date": "2022-04-26",
              "filing_date": "2020-01-15",
              "assignee": "Somnics, Inc.",
              "inventor": "John Smith",
              "country": "US",
              "kind_code": "B2",
              "family_metadata": {
                "aggregated": {
                  "country_status": [
                    {"country": "US", "best_patent_stage": {"state": "ACTIVE"}},
                    {"country": "EP", "best_patent_stage": {"state": "ACTIVE"}},
                    {"country": "JP", "best_patent_stage": {"state": "ACTIVE"}}
                  ]
                }
              }
            }
          }
        ]
      }
    ]
  }
}
```

### Key Fields

| Field | Path | Notes |
|-------|------|-------|
| Publication number | `results.cluster[].result[].patent.publication_number` | e.g. `US11311692B2` |
| Title | `...patent.title` | HTML may contain `<b>` tags |
| Abstract snippet | `...patent.snippet` | Truncated abstract |
| Publication date | `...patent.publication_date` | `YYYY-MM-DD` |
| Filing date | `...patent.filing_date` | `YYYY-MM-DD` |
| Assignee | `...patent.assignee` | Raw HTML, strip `<b>` tags |
| Inventor | `...patent.inventor` | Single string in list view |
| Country | `...patent.country` | 2-letter code |
| Kind code | `...patent.kind_code` | e.g. `B2`, `A1` |
| Family countries | `...patent.family_metadata.aggregated.country_status` | Array |
| Family size | `len(country_status)` | Number of countries |

### Legal Status Heuristic

```python
countries = patent.get("family_metadata", {}).get("aggregated", {}).get("country_status", [])
active_count = sum(1 for c in countries if c.get("best_patent_stage", {}).get("state") == "ACTIVE")
legal_status = "Active" if active_count > 0 else "Not Active"
```

---

## Detail Page Scraping

### Endpoint

```
https://patents.google.com/patent/{publication_number}/en
```

### Claims Extraction

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(resp.text, "lxml")
claims = None
for sel in ["div.claims", "section[itemprop='claims']"]:
    elem = soup.select_one(sel)
    if elem:
        text = elem.get_text(separator="\n", strip=True)
        if len(text) > 50:
            claims = text
            break
```

### Description Extraction

```python
desc = None
for sel in ["section[itemprop='description']", "div.description"]:
    elem = soup.select_one(sel)
    if elem:
        text = elem.get_text(separator="\n", strip=True)
        if len(text) > 100:
            desc = text
            break
```

### Citation Count

```python
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
```

### Image URLs

```python
image_urls = []
for li in soup.find_all("li", attrs={"itemprop": "images"}):
    meta = li.find("meta", attrs={"itemprop": "full"})
    if meta and meta.get("content"):
        image_urls.append(meta["content"])
# Result: ["https://patentimages.storage.googleapis.com/.../US11311692-20220426-D00000.png", ...]
```

### PDF URL

```python
pdf_url = None
meta_pdf = soup.find("meta", attrs={"name": "citation_pdf_url"})
if meta_pdf and meta_pdf.get("content"):
    pdf_url = meta_pdf["content"]
# Result: "https://patentimages.storage.googleapis.com/.../US11311692.pdf"
```

---

## Anti-Scraping & Blocking

| Mechanism | Trigger | Result | Workaround |
|-----------|---------|--------|------------|
| IP blacklist | Cloud VM IPs (Oracle, AWS, Azure) | 503 Service Unavailable | Tor proxy, residential proxy, or EPO OPS |
| Rate limiting | >1 req/sec sustained | 429 Too Many Requests | 0.5–1.0s delay between requests |
| Missing browser fingerprint | No cookies, no JS execution | 503 or reCAPTCHA | Full browser headers + session cookies |
| TLS fingerprint | curl/python-requests vs real browser | Silent drop | `requests` with `urllib3` ≥ 2.0 |

**Verified blocked (Oracle Cloud VM, May 2026)**:
- `patents.google.com/xhr/query` → 503
- `patents.google.com/patent/{ID}` → 503
- `patents.google.com/` homepage → 503

**Still working**:
- `patentimages.storage.googleapis.com` (CDN) → 200 OK ✅

---

## Rate Limits

| Endpoint | Safe Delay | Burst Limit |
|----------|-----------|-------------|
| XHR API (list) | 0.5s | 25 results/page |
| Detail page (HTML) | 1.0s | 40s timeout |
| PDF download | 2.0s | 120s timeout |
| Image CDN | No delay | Direct CDN, no WAF |

---

## Error Handling

```python
try:
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
except requests.RequestException as e:
    if resp.status_code == 503:
        # IP blocked — rotate proxy or abort
        pass
    elif resp.status_code == 429:
        # Rate limited — increase delay
        time.sleep(5.0)
    else:
        print(f"[ERROR] {e}")
    break
except json.JSONDecodeError:
    # Likely HTML error page (not JSON)
    print(f"[JSON ERROR] Non-JSON response: {resp.text[:200]}")
    break
```

---

## Family ID vs Publication Number

- **Publication number**: `US11311692B2` — jurisdiction-specific, changes with every publication stage
- **Family ID**: Google Patents does not expose a canonical family ID in the XHR API
- **Family size**: inferred from `family_metadata.aggregated.country_status` array length

For true family deduplication, use **EPO OPS** or **Lens.org** which expose DOCDB family IDs.

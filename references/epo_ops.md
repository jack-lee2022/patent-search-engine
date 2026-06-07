# EPO Open Patent Services (OPS) — Integration Guide

## Status

**Placeholder for future integration.** Not yet implemented in v1.0.0.

Planned as the **primary fallback** when Google Patents is blocked.

---

## Registration

1. Visit https://developers.epo.org/
2. Create an account
3. Register an application to get **Client ID** and **Client Secret**
4. Request access to **OPS** API

---

## Authentication

### OAuth 2.0 Client Credentials

```python
import requests
import base64

CLIENT_ID = "your_client_id"
CLIENT_SECRET = "your_client_secret"

auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
resp = requests.post(
    "https://ops.epo.org/3.2/auth/accesstoken",
    headers={"Authorization": f"Basic {auth}"},
    data={"grant_type": "client_credentials"},
)
token = resp.json()["access_token"]
```

Token expires in ~20 minutes. Refresh as needed.

---

## Search Endpoint

```python
resp = requests.get(
    "https://ops.epo.org/3.2/rest-services/published-data/search",
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    },
    params={
        "q": "ti=sleep apnea",  # title contains
        "Range": "1-25",         # result range
    },
)
```

### Query Syntax

| Syntax | Example | Description |
|--------|---------|-------------|
| `ti=` | `ti=sleep apnea` | Title |
| `ab=` | `ab=negative pressure` | Abstract |
| `pa=` | `pa=Somnics` | Applicant (assignee) |
| `in=` | `in=Smith` | Inventor |
| `pn=` | `pn=US11311692` | Publication number |
| `cpc=` | `cpc=A61B5/00` | CPC classification |
| `ic=` | `ic=A61B5/00` | IPC classification |
| `pd=` | `pd=2020` | Publication date |
| `ap=` | `ap=2020` | Application date |

**Combined**:
```
ti=sleep AND pa=Somnics AND pd=2020
```

---

## Response Format

```json
{
  "ops:world-patent-data": {
    "ops:biblio-search": {
      "ops:search-result": {
        "ops:exchange-documents": [
          {
            "ops:exchange-document": {
              "ops:bibliographic-data": {
                "publication-reference": {
                  "document-id": [
                    {"country": "US", "doc-number": "11311692", "kind": "B2"}
                  ]
                },
                "invention-title": {"$": "System and method for treating sleep apnea"},
                "abstract": {"p": {"$": "Abstract text..."}},
                "parties": {
                  "applicants": {
                    "applicant": [{"addressbook": {"name": {"$": "Somnics, Inc."}}}]
                  }
                }
              }
            }
          }
        ]
      }
    }
  }
}
```

**Note**: EPO OPS uses XML namespaces. JSON conversion adds `ops:` prefix to keys.

---

## Rate Limits (Free Tier)

| Limit | Value |
|-------|-------|
| Requests per week | 1,000 |
| Requests per minute | ~4 |
| Results per request | 100 max |

**Track usage**:
```python
# Check remaining from response headers
remaining = resp.headers.get("X-RateLimit-Remaining")
```

---

## Data Source Comparison

| Feature | Google Patents | EPO OPS |
|---------|---------------|---------|
| Official API | ❌ No | ✅ Yes |
| Free | ✅ Yes | ✅ Yes (limited) |
| Cloud VM blocked | ❌ Often | ✅ No |
| Full text | ✅ Yes (HTML) | ⚠️ Abstract only (free) |
| Claims | ✅ Yes (HTML) | ❌ No (requires paid) |
| Citations | ✅ Yes (HTML) | ❌ No |
| Family data | ✅ Yes (inferred) | ✅ Yes (DOCDB) |
| Images | ✅ Yes (CDN) | ✅ Yes (separate endpoint) |
| PDF | ✅ Yes | ✅ Yes (separate endpoint) |

---

## Implementation Plan

```python
class EPOOPSCollector(BaseCollector):
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self._refresh_token()

    def _refresh_token(self):
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = requests.post(
            "https://ops.epo.org/3.2/auth/accesstoken",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
        )
        self.token = resp.json()["access_token"]

    def search(self, query: str, max_results: int = 100) -> List[Dict]:
        # Implement EPO OPS search
        # Normalize response to Google Patents schema for compatibility
        pass
```

**Normalization**: Convert EPO OPS response fields to match Google Patents schema
so downstream `ResultMerger` and `PatentDB` work without modification.

---

## When to Implement

Implement EPO OPS integration when:
- Google Patents 503 rate exceeds 50% of requests
- Tor proxy is too slow/unreliable for production
- You need DOCDB family data for deduplication
- You need official API reliability for client reports

**Priority**: Medium — Google Patents + Tor works for current use case.

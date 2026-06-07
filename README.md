# Patent Search Engine

A multi-source patent search engine skill for Hermes Agent. Primary source: Google Patents
internal XHR API. Designed for production use on cloud VMs (Oracle, AWS, Azure) where
Google Patents actively blocks data center IPs.

## Status

- ✅ **Google Patents** — XHR API search, detail enrichment, PDF download, image extraction
- ✅ **Tor Proxy** — IP rotation and bypass for cloud VM blocks
- ✅ **Keyword Translation** — Chinese → English, entity extraction, caching
- ✅ **Result Merging** — Dual-track search (keyword + assignee), deduplication, relevance scoring
- ✅ **Report Generation** — Structured Markdown reports from SQLite database
- 🔹 **EPO OPS** — Planned as primary fallback (see `references/epo_ops.md`)

## Structure

```
patent-search-engine/
├── SKILL.md                          # Core skill instructions
├── README.md                         # This file
├── scripts/
│   ├── google_patents_collector.py   # XHR API collector + detail enricher
│   ├── keyword_translator.py         # Translation + entity extraction
│   ├── proxy_manager.py             # Tor setup, rotation, health check
│   ├── result_merger.py             # Deduplication + relevance filtering
│   └── search_report.py             # Markdown report generator
├── references/
│   ├── google_patents_api.md        # XHR API internals
│   ├── anti_scraping.md             # Blocking mechanisms + countermeasures
│   └── epo_ops.md                   # EPO OPS integration guide (placeholder)
└── templates/
    └── search_report_template.md     # Report template
```

## Quick Start

### 1. Install dependencies

```bash
uv pip install requests beautifulsoup4 lxml
# Optional: for PDF extraction
uv pip install pymupdf pytesseract pdf2image pillow
```

### 2. Install and start Tor

```bash
sudo dnf install -y tor
sudo systemctl enable --now tor
```

### 3. Search patents

```bash
# By keyword
python scripts/google_patents_collector.py --query "tongue pressure" --max 50

# By assignee
python scripts/google_patents_collector.py --assignee "Somnics" --max 25

# By IPC classification
python scripts/google_patents_collector.py --ipc "A61B5/00" --max 50
```

### 4. Translate Chinese topics

```bash
python scripts/keyword_translator.py "舌肌力訓練"
# → ['tongue strength training', 'tongue muscle exercise', ...]

python scripts/keyword_translator.py "JMS舌壓測定儀"
# → ['tongue pressure measurement', 'entity:JMS', ...]
```

### 5. Check proxy status

```bash
python scripts/proxy_manager.py --check
python scripts/proxy_manager.py --test
```

## Key Features

### Entity-Aware Search

When a topic contains company names (e.g., "JMS舌壓測定儀"), the translator extracts
`JMS` as an entity and produces a marker like `entity:JMS`. The downstream search
can then run dual-track:

1. Keyword search: `tongue pressure measurement`, `oral pressure sensor`
2. Assignee search: `fetch_list(assignee="JMS")` → filter by keyword relevance

This solves **terminology drift** (e.g., JMS calls it "oral cavity pressure" but
keywords search for "tongue pressure measurement").

### Weak AND Filtering

Assignee searches return ALL patents by a company — mostly unrelated. The
`_filter_by_keywords()` method tolerates terminology drift by checking if the
title+abstract contains at least 1 keyword fragment:

```python
# Keywords: ["tongue pressure measurement", "oral pressure sensor"]
# Keyword words: {"tongue", "pressure", "measurement", "oral", "sensor"}
# JMS patent: "Balloon for measuring pressure related to oral cavity"
# Matches: "pressure", "oral" → kept ✅
```

### Known Pitfalls Documented

Every known bug and workaround from production use is documented:

| Pitfall | File |
|---------|------|
| URL double-encoding in XHR API | `SKILL.md` § Core Components |
| `image_urls` key missing → 0 inserts | `SKILL.md` § PatentDB |
| Cache hit loses entity markers | `SKILL.md` § KeywordTranslator |
| Empty-result dict missing keys | `SKILL.md` § Known Pitfalls |
| Google Patents 503 from cloud VM | `references/anti_scraping.md` |
| Assignee search noise (48/50 unrelated) | `SKILL.md` § ResultMerger |
| Japanese text in claims | `SKILL.md` § Known Pitfalls |

## Integration with Hermes

Install as a skill:

```bash
# In Hermes session
/skill install patent-search-engine
```

Or clone directly:

```bash
git clone https://github.com/jack-lee2022/patent-search-engine.git
```

## License

MIT

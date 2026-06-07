# Patent Search Engine

A multi-source patent search engine skill for Hermes Agent. Primary source: Google Patents
internal XHR API. Designed for production use on cloud VMs (Oracle, AWS, Azure) where
Google Patents actively blocks data center IPs.

**Version:** 1.0.3 — Full 5-step patent search workflow

---

## Status

| Feature | Status |
|---------|--------|
| **Google Patents** | ✅ XHR API search, detail enrichment, PDF download, image extraction |
| **EPO OPS** | ✅ OAuth + search + query builder |
| **Tor Proxy** | ✅ IP rotation and bypass for cloud VM blocks |
| **Keyword Translation** | ✅ Chinese → English, entity extraction, caching |
| **Synonym Expansion** | ✅ Synonyms + hyponyms + hypernyms |
| **Boolean Query Builder** | ✅ AND/OR/NOT + field filters for Google Patents / EPO OPS / USPTO |
| **Classification Analysis** | ✅ IPC/CPC extraction + frequency analysis + reverse search loop |
| **Result Merging** | ✅ Dual-track search (keyword + assignee), deduplication, relevance scoring |
| **Three-Layer Filtering** | ✅ Abstract → Claims → Description |
| **Report Generation** | ✅ Structured Markdown reports from SQLite database |

---

## Structure

```
patent-search-engine/
├── SKILL.md                          # Core skill documentation (645+ lines)
├── README.md                         # This file
├── scripts/
│   ├── google_patents_collector.py   # XHR API collector + search_preview + smart_search
│   ├── epo_ops_collector.py          # EPO OPS API with OAuth + search_preview
│   ├── keyword_translator.py         # Translation + entity extraction + caching
│   ├── synonym_expander.py           # Synonym / hyponym / hypernym expansion
│   ├── boolean_query_builder.py      # Boolean AND/OR/NOT + field filters
│   ├── search_query_composer.py      # Purpose-aware search config (novelty/fto/invalidity/landscape)
│   ├── classification_analyzer.py    # IPC/CPC extraction + frequency + reverse search
│   ├── patent_filter.py              # Three-layer filtering (abstract → claims → description)
│   ├── proxy_manager.py              # Tor setup, rotation, health check
│   ├── result_merger.py              # Deduplication + relevance filtering
│   └── search_report.py              # Markdown report generator
├── references/
│   ├── google_patents_api.md         # XHR API internals
│   ├── anti_scraping.md              # Blocking mechanisms + countermeasures
│   └── epo_ops.md                    # EPO OPS integration guide
└── templates/
    └── search_report_template.md      # Report template
```

---

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

### 3. Basic Search

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

---

## 5-Step Patent Search Workflow

### Step 1: Define Search Purpose

Use `SearchQueryComposer` to auto-configure search parameters based on your goal:

```python
from boolean_query_builder import SearchQueryComposer

composer = SearchQueryComposer()

# FTO (Freedom to Operate) — before product launch
queries = composer.from_purpose(
    purpose="fto",
    keywords=["tongue pressure measurement", "oral sensor"],
    target_countries=["US", "EP"],
)

# Novelty search — check if invention is patentable
queries = composer.from_purpose(
    purpose="novelty",
    keywords=["negative pressure therapy", "mesh nebulizer"],
)

# Landscape — technology overview
queries = composer.from_purpose(
    purpose="landscape",
    keywords=["sleep apnea", "CPAP", "oral appliance"],
)

# Access all three database formats
print(queries["google_patents"])
print(queries["epo_ops"])
print(queries["uspto"])
```

| Purpose | Default filters |
|---------|-----------------|
| `novelty` | All countries, all statuses, no date limit |
| `fto` | Target countries, active only, last 20 years |
| `invalidity` | All countries, all statuses, no date limit |
| `landscape` | All countries, all statuses, last 10 years |

---

### Step 2: Expand Keywords

```python
from synonym_expander import SynonymExpander

expander = SynonymExpander()
keywords = ["tongue pressure", "sensor", "negative pressure"]

# Expand with synonyms, hyponyms, hypernyms
expanded = expander.expand(keywords)
# {
#   "tongue pressure": ["oral pressure", "lingual pressure", "palatal pressure"],
#   "sensor": ["pressure sensor", "force sensor", "transducer"],
#   "negative pressure": ["vacuum", "suction", "reduced pressure"],
# }

# Generate all query variants
all_queries = expander.generate_expanded_queries(keywords)
# → ["tongue pressure", "oral pressure", "lingual pressure", "sensor", "pressure sensor", ...]

# Generate Boolean OR groups
or_groups = expander.generate_boolean_groups(keywords)
# {
#   "tongue pressure": ["tongue pressure", "oral pressure", "lingual pressure", "palatal pressure"],
#   "sensor": ["sensor", "pressure sensor", "force sensor", "transducer"],
# }
```

---

### Step 3: Build Boolean Queries

```python
from boolean_query_builder import BooleanQueryBuilder

# Simple example
b = BooleanQueryBuilder()
b.add_or(["negative pressure", "vacuum", "suction"])
b.add_or(["sensor", "controller", "transducer"])
b.add_and("device")
b.add_not("biomedical")
b.add_ipc("A61B5/00")
b.add_country("US")

q_google = b.build_google_patents()
# → (negative pressure OR vacuum OR suction) AND (sensor OR controller OR transducer) AND device
#    NOT biomedical AND classification/ipc:A61B5/00 AND country:US

q_epo = b.build_epo_ops()
# → (ti=negative pressure OR ab=negative pressure OR ti=vacuum OR ...) AND (ti=sensor OR ab=sensor OR ...)
#    AND ti=device AND ic=A61B5/00 AND pa=US NOT (ti=biomedical OR ab=biomedical)

q_uspto = b.build_uspto()
# → (ABST/negative pressure OR TTL/negative pressure OR ...) AND (ABST/sensor OR TTL/sensor OR ...)
```

**Combine with expanded keywords and purpose config:**

```python
from boolean_query_builder import SearchQueryComposer

queries = composer.compose(
    keywords=["tongue pressure"],
    synonyms={
        "tongue pressure": ["oral pressure", "lingual pressure"],
        "sensor": ["pressure sensor", "transducer"],
    },
    assignee="JMS",
    ipc="A61B5/00",
    country="US",
    date_after="2020-01-01",
    exclusions=["animal", "veterinary"],
)
```

---

### Step 4: Search with Preview

```python
from google_patents_collector import GooglePatentsCollector

collector = GooglePatentsCollector()

# Preview search volume (fetches 1 item only)
preview = collector.search_preview("tongue pressure measurement")
print(preview)
# {
#   "query": "tongue pressure measurement",
#   "total_found": 1247,
#   "estimated_pages": 50,
#   "warning": True,
# }

# Smart search with auto-limiting
result = collector.smart_search("tongue pressure measurement", max_results=100)

# If too many patents:
# result = {
#   "status": "preview",
#   "total_found": 1247,
#   "suggestions": [
#       "tongue pressure measurement device",
#       "tongue pressure measurement classification/ipc:A61B5/00",
#       "tongue pressure measurement after:2015-01-01",
#       "tongue pressure measurement country:US",
#   ],
# }

# After refining with a suggestion:
result = collector.smart_search("tongue pressure measurement device", max_results=100)
# result = {
#   "status": "success",
#   "total_found": 89,
#   "downloaded": 50,
#   "items": [...],  # sorted by relevance
# }
```

---

### Step 5: Classification Reverse Search

```python
from classification_analyzer import ClassificationAnalyzer
from google_patents_collector import GooglePatentsCollector

collector = GooglePatentsCollector()
analyzer = ClassificationAnalyzer()

# Full reverse search loop
result = analyzer.reverse_search(
    collector,
    keywords=["tongue pressure"],
    seed_max_results=20,      # Start with 20 seed patents
    top_n_ipc=3,              # Use top 3 IPC codes
    top_n_cpc=3,              # Use top 3 CPC codes
    max_results_per_code=50,  # 50 patents per classification
)

print(f"Seed patents: {len(result['seed_items'])}")
print(f"Reverse search patents: {len(result['reverse_items'])}")
print(f"Total unique: {len(result['merged_items'])}")

# Analyze classification codes
codes = result["codes"]
print(codes.top_ipc(5))
# [("A61B5/00", 12), ("A61B5/01", 8), ("A61B5/103", 5), ...]

print(codes.top_cpc(5))
# [("A61B5/0245", 5), ("A61B5/11", 3), ...]

# Recommend codes from keywords
rec = analyzer.recommend_from_keywords(["tongue pressure", "sensor", "sleep apnea"])
print(rec["ipc"])   # ["A61B5/00", "A61B5/01", "A61F5/56", "A61M16/00"]
print(rec["cpc"])   # ["A61B5/0245", "A61B5/103", "A61F5/56", "A61M16/0051"]
```

---

## Three-Layer Filtering

```python
from patent_filter import PatentFilter

filter = PatentFilter()

# Run all three layers
result = filter.filter_pipeline(
    items=result["merged_items"],  # from reverse search
    keywords=["tongue pressure", "sensor"],
    target_features=["tongue", "pressure", "sensor", "measurement"],
    purpose="fto",                # "novelty", "fto", "invalidity"
    l1_threshold=0.3,               # Layer 1: abstract relevance
    l2_min_match=1,               # Layer 2: claim feature match
    l3_min_detail=0.5,            # Layer 3: description detail
)

print(result["stats"])
# {
#   "input": 500,
#   "layer1_pass": 150,
#   "layer2_pass": 40,
#   "layer3_pass": 25,
#   "rejection_reasons": {"layer1": 350, "layer2": 110, "layer3": 15}
# }

# Generate report
print(PatentFilter.generate_filter_report(result))
```

**Filtering flow:**

```
Input: 500 patents
    ↓
Layer 1: Abstract + Title screening
    - Relevance score ≥ 0.3 (fast pass/fail)
    → 150 patents
    ↓
Layer 2: Independent Claims analysis
    - Extract independent claims
    - Match target technical features
    - FTO: any match = potential infringement
    → 40 patents
    ↓
Layer 3: Detailed Description
    - Feature presence in description
    - Detail level: word count, figure references, embodiment refs
    → 25 patents
```

---

## Complete Workflow Example

```python
from keyword_translator import KeywordTranslator
from synonym_expander import SynonymExpander
from boolean_query_builder import SearchQueryComposer
from google_patents_collector import GooglePatentsCollector
from classification_analyzer import ClassificationAnalyzer
from patent_filter import PatentFilter

# Step 1: Translate
translator = KeywordTranslator()
queries = translator.translate("舌壓測定裝置")
# → ['tongue pressure measurement', 'tongue pressure meter', 'entity:JMS']

# Step 2: Expand
expander = SynonymExpander()
expanded = expander.expand(queries)

# Step 3: Compose query
composer = SearchQueryComposer()
search_queries = composer.compose(
    keywords=queries,
    synonyms=expanded,
    ipc="A61B5/00",
    country="US",
    date_after="2020-01-01",
)

# Step 4: Search with preview
collector = GooglePatentsCollector()
result = collector.smart_search(search_queries["google_patents"])

# Step 5: Reverse search
analyzer = ClassificationAnalyzer()
reverse_result = analyzer.reverse_search(
    collector,
    queries,
    seed_max_results=20,
    top_n_ipc=3,
)

# Step 6: Filter
filter = PatentFilter()
filtered = filter.filter_pipeline(
    reverse_result["merged_items"],
    keywords=queries,
    target_features=["tongue", "pressure", "measurement", "sensor"],
    purpose="fto",
)

print(f"Final: {filtered['stats']['layer3_pass']} patents")
```

---

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

### Search Preview

Avoid downloading hundreds of irrelevant patents:

```python
preview = collector.search_preview("sleep apnea")
# { "total_found": 5432, "warning": True }

# Refine before downloading
result = collector.smart_search("sleep apnea mandibular advancement device")
# { "total_found": 156, "status": "success", "downloaded": 100 }
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

---

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

---

## License

MIT

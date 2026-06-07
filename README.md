# Patent Search Engine

A professional-grade patent analysis engine designed for patent engineers, IP researchers, and R&D teams.

## Key Features
- **Smart Search**: Hybrid search (Keyword + Semantic expansion).
- **Anti-Blocking**: Built-in Playwright renderer with automatic fallback and normal-distribution based random request delays.
- **Expert Analysis**: Native support for Claim Chart generation (Element-by-Element), Legal Status tracking, and Citation Snowballing.
- **Portfolio Management**: Automated patent family grouping and visual landscape generation.

## Installation
1. Clone the repository.
2. Install dependencies: `pip install requests beautifulsoup4 playwright numpy pandas seaborn matplotlib plotly`
3. Install browser engine: `python -m playwright install chromium`

## Usage
- Search: `python scripts/google_patents_collector.py --query "your query" --max 50`
- Enrich: `python scripts/google_patents_collector.py --enrich --max 10`
- Advanced: Check `scripts/advanced/` for Claim Chart generators and Visualizers.

## Professional Workflow
Standard Operating Procedure (SOP) is defined in the associated `pro-patent-search` skill.

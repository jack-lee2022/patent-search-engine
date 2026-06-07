#!/usr/bin/env python3
"""
SearchReport — Generate structured Markdown reports from patent search results.

Usage:
    python search_report.py --db data/patents.db --output reports/search_report.md
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List


class SearchReport:
    """Generate a Markdown report from patent search results."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM patents").fetchone()[0]
            with_abstract = conn.execute(
                "SELECT COUNT(*) FROM patents WHERE abstract IS NOT NULL AND abstract != ''"
            ).fetchone()[0]
            with_claims = conn.execute(
                "SELECT COUNT(*) FROM patents WHERE claims IS NOT NULL AND claims != ''"
            ).fetchone()[0]
            with_pdf = conn.execute(
                "SELECT COUNT(*) FROM patents WHERE pdf_url IS NOT NULL"
            ).fetchone()[0]
            date_range = conn.execute(
                "SELECT MIN(publication_date), MAX(publication_date) FROM patents"
            ).fetchone()
            top_assignees = conn.execute(
                """SELECT assignee, COUNT(*) as cnt FROM patents
                   WHERE assignee != 'Unknown' AND assignee != ''
                   GROUP BY assignee ORDER BY cnt DESC LIMIT 10"""
            ).fetchall()
            return {
                "total": total,
                "with_abstract": with_abstract,
                "with_claims": with_claims,
                "with_pdf": with_pdf,
                "date_range": (date_range[0], date_range[1]) if date_range else (None, None),
                "top_assignees": [dict(r) for r in top_assignees],
            }

    def get_sample_patents(self, limit: int = 20) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT patent_id, title, abstract, publication_date, assignee,
                          country, kind_code, patent_family_size, citation_count, legal_status
                   FROM patents ORDER BY publication_date DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def generate(self, topic: str, queries: List[str], entities: List[str],
                 search_method: str = "keyword") -> str:
        stats = self.get_stats()
        samples = self.get_sample_patents(limit=20)

        lines = []
        lines.append(f"# Patent Search Report: {topic}")
        lines.append("")
        lines.append(f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")

        # Search Method
        lines.append("## Search Method")
        lines.append("")
        if search_method == "dual":
            lines.append(f"- **Keyword search:** {', '.join(queries)}")
            lines.append(f"- **Assignee search:** {', '.join(entities)}")
        else:
            lines.append(f"- **Keyword search:** {', '.join(queries)}")
        lines.append(f"- **Total patents found:** {stats['total']}")
        lines.append(f"- **With abstract:** {stats['with_abstract']} ({stats['with_abstract']/max(stats['total'],1)*100:.1f}%)")
        lines.append(f"- **With claims:** {stats['with_claims']} ({stats['with_claims']/max(stats['total'],1)*100:.1f}%)")
        lines.append(f"- **With PDF URL:** {stats['with_pdf']}")
        if stats['date_range'][0]:
            lines.append(f"- **Date range:** {stats['date_range'][0]} to {stats['date_range'][1]}")
        lines.append("")

        # Key Players
        if stats['top_assignees']:
            lines.append("## Key Players")
            lines.append("")
            lines.append("| Assignee | Patents |")
            lines.append("|----------|---------|")
            for a in stats['top_assignees']:
                lines.append(f"| {a['assignee']} | {a['cnt']} |")
            lines.append("")

        # Sample Results
        if samples:
            lines.append("## Sample Results")
            lines.append("")
            lines.append("| Patent ID | Title | Date | Assignee | Country | Status |")
            lines.append("|-----------|-------|------|----------|---------|--------|")
            for p in samples[:20]:
                title = (p['title'] or '')[:50]
                assignee = (p['assignee'] or 'Unknown')[:20]
                lines.append(
                    f"| {p['patent_id']} | {title} | {p['publication_date'] or 'N/A'} | "
                    f"{assignee} | {p['country'] or 'N/A'} | {p['legal_status'] or 'N/A'} |"
                )
            lines.append("")

        # Data Quality
        lines.append("## Data Quality")
        lines.append("")
        lines.append(f"- **Total patents:** {stats['total']}")
        lines.append(f"- **With abstract:** {stats['with_abstract']} ({stats['with_abstract']/max(stats['total'],1)*100:.1f}%)")
        lines.append(f"- **With claims:** {stats['with_claims']} ({stats['with_claims']/max(stats['total'],1)*100:.1f}%)")
        lines.append(f"- **With PDF URL:** {stats['with_pdf']}")
        lines.append("")

        return "\n".join(lines)

    def save(self, topic: str, queries: List[str], entities: List[str],
             output_path: str, search_method: str = "keyword"):
        content = self.generate(topic, queries, entities, search_method)
        Path(output_path).write_text(content, encoding="utf-8")
        print(f"[REPORT] Saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search Report Generator")
    parser.add_argument("--db", required=True, help="Path to SQLite database")
    parser.add_argument("--output", "-o", required=True, help="Output Markdown file")
    parser.add_argument("--topic", "-t", default="Patent Search", help="Search topic")
    parser.add_argument("--queries", "-q", default="", help="Comma-separated queries")
    parser.add_argument("--entities", "-e", default="", help="Comma-separated entities")
    args = parser.parse_args()

    report = SearchReport(args.db)
    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    entities = [e.strip() for e in args.entities.split(",") if e.strip()]
    search_method = "dual" if entities else "keyword"

    report.save(
        topic=args.topic,
        queries=queries,
        entities=entities,
        output_path=args.output,
        search_method=search_method,
    )

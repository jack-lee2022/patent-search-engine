#!/usr/bin/env python3
"""
Patent Search Manager
=====================

Search preview, volume control, and 4-dimension keyword refinement.

Provides:
  - search_preview()  — fetch 1 item to determine total count
  - smart_search()    — preview → suggest refinements → download top-N by relevance
  - score_relevance() — simple keyword-based relevance scoring
  - generate_refinements() — 4-dimension keyword suggestions

Usage:
    python scripts/search_manager.py --preview "tongue pressure measurement"
    python scripts/search_manager.py --smart "tongue pressure measurement" --max 50
"""

import re
import time
from typing import List, Dict, Any, Optional

# Adjust import path for standalone use
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.google_patents_collector import GooglePatentsCollector


class SearchManager:
    """Orchestrates preview, refinement, and smart download for patent searches."""

    def __init__(self, collector: Optional[GooglePatentsCollector] = None):
        self.collector = collector or GooglePatentsCollector()

    # ------------------------------------------------------------------
    # Search preview
    # ------------------------------------------------------------------
    def search_preview(self, query: str) -> Dict[str, Any]:
        """Fetch only 1 item to determine total result count without heavy download."""
        url = self.collector._build_keyword_url(query, page=0, num=1)
        data = self.collector._fetch_page(url)
        total = data.get("results", {}).get("total_num_results", 0) if data else 0
        return {
            "query": query,
            "total_found": total,
            "estimated_pages": (total + 24) // 25,
            "warning": total > 200,
        }

    # ------------------------------------------------------------------
    # Smart search with volume control
    # ------------------------------------------------------------------
    def smart_search(
        self,
        keywords: List[str],
        max_results: int = 100,
        relevance_threshold: float = 0.2,
    ) -> Dict[str, Any]:
        """
        1. Preview count
        2. If too many, suggest refinements
        3. If confirmed, fetch top-N by relevance
        """
        if not keywords:
            return {"status": "error", "message": "No keywords provided"}

        preview = self.search_preview(keywords[0])

        # Too many → return warning + suggestions
        if preview["total_found"] > max_results * 2:
            return {
                "status": "too_many",
                "query": keywords[0],
                "total": preview["total_found"],
                "suggestions": self.generate_refinements(keywords),
            }

        # Acceptable → fetch, score, truncate
        items = self.collector.fetch_by_keywords(
            keywords, max_results=preview["total_found"]
        )

        scored = [
            (item, self.score_relevance(item, keywords))
            for item in items
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        top_items = [
            item for item, score in scored[:max_results]
            if score >= relevance_threshold
        ]

        return {
            "status": "success",
            "query": keywords[0],
            "total_found": preview["total_found"],
            "downloaded": len(top_items),
            "relevance_threshold": relevance_threshold,
            "items": top_items,
        }

    # ------------------------------------------------------------------
    # Relevance scoring
    # ------------------------------------------------------------------
    def score_relevance(self, item: Dict[str, Any], keywords: List[str]) -> float:
        """
        Simple keyword-based relevance score (0.0–1.0).
        Looks at title, snippet, and assignee.
        """
        patent = item.get("patent", {})
        title = patent.get("title", "").lower()
        snippet = patent.get("snippet", "").lower()
        assignee = patent.get("assignee", "").lower()
        text = f"{title} {snippet} {assignee}"

        # Build keyword word set
        keyword_words = set()
        for kw in keywords:
            for w in kw.split():
                w_clean = w.strip(",.():;")
                if len(w_clean) > 2:
                    keyword_words.add(w_clean.lower())

        if not keyword_words:
            return 0.0

        # Count matches
        matches = sum(1 for w in keyword_words if w in text)
        # Normalize by keyword word count
        base_score = matches / len(keyword_words)

        # Bonus: title match (more important)
        title_matches = sum(1 for w in keyword_words if w in title)
        title_bonus = min(title_matches * 0.15, 0.5)

        return min(base_score + title_bonus, 1.0)

    # ------------------------------------------------------------------
    # 4-dimension refinement suggestions
    # ------------------------------------------------------------------
    def generate_refinements(self, keywords: List[str]) -> List[str]:
        """
        Generate 4-dimension refinement suggestions:
        1. Technical qualifier  2. IPC  3. Date  4. Country
        """
        base = " ".join(keywords)
        return [
            f"{base} device",
            f"{base} sensor",
            f"{base} apparatus",
            f"{base} classification:A61B5/00",
            f"{base} classification:A61B5/103",
            f"{base} after:2020-01-01",
            f"{base} after:2015-01-01",
            f"{base} country:US",
            f"{base} country:WO",
        ]

    # ------------------------------------------------------------------
    # Interactive CLI helper
    # ------------------------------------------------------------------
    def run_interactive(self, keywords: List[str], max_results: int = 100) -> None:
        """Run full preview → refine → download workflow with CLI prompts."""
        preview = self.search_preview(keywords[0])
        print(f"\n[Preview] Query: {keywords[0]}")
        print(f"          Total found: {preview['total_found']} patents")
        print(f"          Estimated pages: {preview['estimated_pages']}")

        if preview["warning"]:
            print(f"\n⚠️  Warning: {preview['total_found']} is a lot. Consider refinement.")
            print("\nSuggested refinements:")
            for i, sug in enumerate(self.generate_refinements(keywords), 1):
                print(f"  {i}. {sug}")
            print("\nOptions:")
            print("  [1-9] Pick a refinement suggestion")
            print("  [0]   Continue with current query anyway")
            print("  [c]   Custom query")
            print("  [q]   Quit")
            choice = input("\nChoice: ").strip()

            if choice == "q":
                return
            elif choice == "c":
                custom = input("Enter custom query: ").strip()
                keywords = [custom]
            elif choice.isdigit() and 1 <= int(choice) <= 9:
                keywords = [self.generate_refinements(keywords)[int(choice) - 1]]
            # else: continue with current

        # Run smart search
        result = self.smart_search(keywords, max_results=max_results)

        if result["status"] == "too_many":
            print(f"\n⚠️  Still too many ({result['total']}). Please refine further.")
            return

        print(f"\n✅ Downloaded {result['downloaded']} / {result['total_found']} patents")
        print(f"   (Relevance threshold: {result['relevance_threshold']})")
        print("\nTop 5 by relevance:")
        for i, item in enumerate(result["items"][:5], 1):
            patent = item.get("patent", {})
            title = patent.get("title", "N/A")
            pub = patent.get("publication_number", "N/A")
            score = self.score_relevance(item, keywords)
            print(f"  {i}. [{pub}] {title[:60]}... (score: {score:.2f})")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Patent Search Manager")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--preview", action="store_true", help="Only preview count")
    parser.add_argument("--smart", action="store_true", help="Run smart search")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--max", type=int, default=100, help="Max results to download")
    parser.add_argument("--threshold", type=float, default=0.2, help="Relevance threshold")
    args = parser.parse_args()

    manager = SearchManager()
    keywords = [args.query]

    if args.preview:
        preview = manager.search_preview(args.query)
        print(preview)
    elif args.smart:
        result = manager.smart_search(keywords, max_results=args.max, relevance_threshold=args.threshold)
        print(f"Status: {result['status']}")
        print(f"Total found: {result.get('total_found', 0)}")
        print(f"Downloaded: {result.get('downloaded', 0)}")
        if result["status"] == "too_many":
            print("\nSuggestions:")
            for s in result["suggestions"]:
                print(f"  - {s}")
    elif args.interactive:
        manager.run_interactive(keywords, max_results=args.max)
    else:
        print("Use --preview, --smart, or --interactive")

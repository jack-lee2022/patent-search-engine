#!/usr/bin/env python3
"""
ResultMerger — Reference implementation for patent-search-engine skill.

Merges patent results from multiple queries, deduplicates by patent_id,
filter assignee results by keyword relevance, and scores relevance.

Usage:
    python result_merger.py --keyword "tongue pressure" --assignee "JMS" --max 50
"""

import argparse
import json
from typing import List, Dict, Any, Optional


class ResultMerger:
    """Merge and deduplicate patent results from multiple sources."""

    @staticmethod
    def deduplicate(items: List[Dict]) -> List[Dict]:
        """Deduplicate by patent_id, preserving order."""
        seen = set()
        unique = []
        for item in items:
            pid = item.get("patent", {}).get("publication_number")
            if pid and pid not in seen:
                seen.add(pid)
                unique.append(item)
        return unique

    @staticmethod
    def filter_by_keywords(items: List[Dict], keywords: List[str], threshold: int = 1) -> List[Dict]:
        """Filter items whose title+snippet contain at least `threshold` keyword fragments.

        Tolerates terminology drift (e.g., "tongue pressure" vs "oral cavity pressure").
        """
        keyword_words = set()
        for kw in keywords:
            keyword_words.update(w.lower() for w in kw.split() if len(w) > 2)
        if not keyword_words:
            return items

        filtered = []
        for item in items:
            patent = item.get("patent", {})
            text = (patent.get("title", "") + " " + patent.get("snippet", "")).lower()
            match_count = sum(1 for w in keyword_words if w in text)
            if match_count >= threshold:
                filtered.append(item)
        return filtered

    @staticmethod
    def score_relevance(item: Dict, keywords: List[str]) -> float:
        """Score a single item's relevance to keywords (0.0–1.0)."""
        patent = item.get("patent", {})
        text = (patent.get("title", "") + " " + patent.get("snippet", "")).lower()
        keyword_words = set()
        for kw in keywords:
            keyword_words.update(w.lower() for w in kw.split() if len(w) > 2)
        if not keyword_words:
            return 0.5
        matches = sum(1 for w in keyword_words if w in text)
        return min(matches / len(keyword_words), 1.0)

    @staticmethod
    def merge(keyword_items: List[Dict], assignee_items: List[Dict],
              keywords: List[str], threshold: int = 1) -> List[Dict]:
        """Merge keyword results and filtered assignee results.

        Strategy: Weak AND — fetch assignee patents, then local filter by keywords.
        """
        filtered_assignee = ResultMerger.filter_by_keywords(assignee_items, keywords, threshold)
        merged = keyword_items + filtered_assignee
        return ResultMerger.deduplicate(merged)

    @staticmethod
    def sort_by_relevance(items: List[Dict], keywords: List[str]) -> List[Dict]:
        """Sort items by relevance score descending."""
        scored = [(item, ResultMerger.score_relevance(item, keywords)) for item in items]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [item for item, score in scored]

    @staticmethod
    def split_entities(queries: List[str]) -> tuple:
        """Split query list into keyword queries and entity markers."""
        keyword_queries = []
        entity_queries = []
        for q in queries:
            if q.startswith("entity:"):
                entity_queries.append(q[7:])
            else:
                keyword_queries.append(q)
        return keyword_queries, entity_queries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Result Merger")
    parser.add_argument("--keyword", "-k", help="Keyword query")
    parser.add_argument("--assignee", "-a", help="Assignee name")
    parser.add_argument("--max", "-m", type=int, default=100, help="Max results")
    parser.add_argument("--threshold", "-t", type=int, default=1, help="Keyword filter threshold")
    args = parser.parse_args()

    # This is a standalone demo; in production, collector outputs feed into this
    print("ResultMerger standalone mode:")
    print("  In production, import ResultMerger and call:")
    print("    merged = ResultMerger.merge(keyword_items, assignee_items, keywords)")
    print("    sorted_results = ResultMerger.sort_by_relevance(merged, keywords)")

#!/usr/bin/env python3
"""
PatentFilter — Reference implementation for patent-search-engine skill.

Step 5: "Screen, read, and analyze results" — implements three-layer filtering:

Layer 1: Abstract + Title filter (fast pass/fail)
Layer 2: Independent Claim filter (patent scope analysis)
Layer 3: Detailed Description filter (embodiment verification)

Usage:
    from patent_filter import PatentFilter
    from result_merger import ResultMerger

    filter = PatentFilter()

    # Layer 1: Quick abstract screening
    layer1 = filter.layer1_abstract_filter(items, keywords, threshold=0.3)

    # Layer 2: Independent claim analysis
    layer2 = filter.layer2_claims_filter(layer1, target_features)

    # Layer 3: Description detail check
    layer3 = filter.layer3_description_filter(layer2, min_detail_score=0.5)
"""

import re
from typing import List, Dict, Optional, Any, Tuple
from collections import Counter

from result_merger import ResultMerger


class PatentFilter:
    """Three-layer patent filtering system for search results."""

    # Layer 1: Abstract/Title screening
    def layer1_abstract_filter(
        self,
        items: List[Dict],
        keywords: List[str],
        threshold: float = 0.3,
    ) -> List[Dict]:
        """Layer 1: Quick filter by abstract + title relevance.

        Fast pass/fail. Removes obviously unrelated patents.
        Scores based on keyword presence in title and abstract.
        """
        filtered = []
        for item in items:
            score = ResultMerger.score_relevance(item, keywords)
            if score >= threshold:
                item["_layer1_score"] = score
                filtered.append(item)
        print(f"[FILTER L1] {len(items)} → {len(filtered)} (threshold={threshold})")
        return filtered

    # Layer 2: Independent Claims filter
    def layer2_claims_filter(
        self,
        items: List[Dict],
        target_features: List[str],
        min_match_count: int = 1,
    ) -> List[Dict]:
        """Layer 2: Filter by independent claim analysis.

        Extracts independent claims and checks for target technical features.
        This is the core of FTO and patentability analysis.

        Args:
            items: Patents with claims text (from enricher)
            target_features: List of technical features to look for
            min_match_count: Minimum number of features that must match

        Returns:
            Items with at least min_match_count features in claims
        """
        filtered = []
        for item in items:
            claims = self._extract_independent_claims(item)
            if not claims:
                # If no claims available, skip (keep for manual review)
                item["_layer2_score"] = 0.0
                item["_layer2_claims"] = []
                item["_layer2_matches"] = []
                filtered.append(item)
                continue

            # Check which target features appear in independent claims
            matches = []
            for feature in target_features:
                feature_lower = feature.lower()
                for claim in claims:
                    claim_lower = claim.lower()
                    if feature_lower in claim_lower:
                        matches.append(feature)
                        break

            match_count = len(set(matches))
            score = min(match_count / len(target_features), 1.0) if target_features else 0.5

            item["_layer2_score"] = score
            item["_layer2_claims"] = claims
            item["_layer2_matches"] = list(set(matches))

            if match_count >= min_match_count:
                filtered.append(item)

        print(f"[FILTER L2] {len(items)} → {len(filtered)} (min_match={min_match_count})")
        return filtered

    def layer2_claims_filter_by_purpose(
        self,
        items: List[Dict],
        purpose: str,  # "novelty" | "fto" | "invalidity"
        target_features: List[str],
    ) -> List[Dict]:
        """Layer 2 with purpose-aware logic.

        | Purpose | Logic |
        |---------|-------|
        | novelty | Keep if claims describe similar invention (high match) |
        | fto | Keep if claims cover target features (any match = potential infringement) |
        | invalidity | Keep if claims describe prior art (any match) |
        """
        if purpose == "novelty":
            # For novelty: need HIGH match — similar invention already exists
            return self.layer2_claims_filter(items, target_features, min_match_count=2)
        elif purpose == "fto":
            # For FTO: ANY match = potential infringement
            return self.layer2_claims_filter(items, target_features, min_match_count=1)
        elif purpose == "invalidity":
            # For invalidity: look for prior art that covers claims
            return self.layer2_claims_filter(items, target_features, min_match_count=1)
        else:
            return self.layer2_claims_filter(items, target_features, min_match_count=1)

    # Layer 3: Detailed Description filter
    def layer3_description_filter(
        self,
        items: List[Dict],
        target_features: List[str],
        min_detail_score: float = 0.5,
    ) -> List[Dict]:
        """Layer 3: Filter by detailed description coverage.

        Checks if the patent's description actually describes the target features
        in sufficient detail. This eliminates patents that merely mention keywords
        in the abstract but have no technical substance.
        """
        filtered = []
        for item in items:
            description = self._extract_description(item)
            if not description:
                # No description available — keep for manual review
                item["_layer3_score"] = 0.5
                item["_layer3_detail_words"] = 0
                filtered.append(item)
                continue

            # Check feature presence in description
            desc_lower = description.lower()
            feature_hits = 0
            for feature in target_features:
                if feature.lower() in desc_lower:
                    feature_hits += 1

            # Check detail level: word count, figure references, embodiment indicators
            word_count = len(description.split())
            figure_refs = len(re.findall(r"FIG\.?\s*\d+|Figure\s*\d+|\[\d+\]", description))
            embodiment_refs = len(re.findall(r"embodiment|example|exemplary", desc_lower))

            # Detail score: features present + length + figures + embodiments
            feature_score = feature_hits / len(target_features) if target_features else 0.5
            length_score = min(word_count / 500, 1.0)  # 500 words = full score
            figure_score = min(figure_refs / 5, 1.0)
            embodiment_score = min(embodiment_refs / 3, 1.0)

            detail_score = (
                feature_score * 0.4
                + length_score * 0.3
                + figure_score * 0.15
                + embodiment_score * 0.15
            )

            item["_layer3_score"] = detail_score
            item["_layer3_word_count"] = word_count
            item["_layer3_figure_refs"] = figure_refs
            item["_layer3_embodiment_refs"] = embodiment_refs

            if detail_score >= min_detail_score:
                filtered.append(item)

        print(f"[FILTER L3] {len(items)} → {len(filtered)} (min_detail={min_detail_score})")
        return filtered

    # ── Combined 3-layer pipeline ───────────────────────────

    def filter_pipeline(
        self,
        items: List[Dict],
        keywords: List[str],
        target_features: List[str],
        purpose: str = "fto",
        l1_threshold: float = 0.3,
        l2_min_match: int = 1,
        l3_min_detail: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Run all three layers in sequence.

        Returns:
            {
                "layer1": [...],
                "layer2": [...],
                "layer3": [...],
                "stats": {
                    "input": N,
                    "layer1_pass": N,
                    "layer2_pass": N,
                    "layer3_pass": N,
                    "rejection_reasons": {"layer1": N, "layer2": N, "layer3": N}
                }
            }
        """
        stats = {
            "input": len(items),
            "layer1_pass": 0,
            "layer2_pass": 0,
            "layer3_pass": 0,
            "rejection_reasons": {"layer1": 0, "layer2": 0, "layer3": 0},
        }

        # Layer 1
        layer1 = self.layer1_abstract_filter(items, keywords, l1_threshold)
        stats["layer1_pass"] = len(layer1)
        stats["rejection_reasons"]["layer1"] = len(items) - len(layer1)

        # Layer 2
        if purpose:
            layer2 = self.layer2_claims_filter_by_purpose(layer1, purpose, target_features)
        else:
            layer2 = self.layer2_claims_filter(layer1, target_features, l2_min_match)
        stats["layer2_pass"] = len(layer2)
        stats["rejection_reasons"]["layer2"] = len(layer1) - len(layer2)

        # Layer 3
        layer3 = self.layer3_description_filter(layer2, target_features, l3_min_detail)
        stats["layer3_pass"] = len(layer3)
        stats["rejection_reasons"]["layer3"] = len(layer2) - len(layer3)

        return {
            "layer1": layer1,
            "layer2": layer2,
            "layer3": layer3,
            "stats": stats,
        }

    # ── Extractors ────────────────────────────────────────────

    @staticmethod
    def _extract_independent_claims(item: Dict) -> List[str]:
        """Extract independent claims from a patent item.

        Independent claims are those that don't reference another claim.
        """
        claims_text = item.get("claims", "")
        if not claims_text:
            # Try raw_json
            raw = item.get("raw_json", "")
            if raw:
                try:
                    import json
                    data = json.loads(raw)
                    claims_text = data.get("claims", "")
                except (json.JSONDecodeError, TypeError):
                    pass

        if not claims_text:
            return []

        # Split claims
        # Common patterns: "1. A device comprising...", "Claim 1. ...", "(1) ..."
        claims = re.split(r"(?:\n|\r\n|\r)\s*(?:\d+\.|\(\d+\)|Claim\s+\d+\.?)", claims_text)

        independent_claims = []
        for claim in claims:
            claim = claim.strip()
            if not claim:
                continue
            # Independent claims don't reference another claim
            # Patterns: "according to claim", "as in claim", "of claim"
            dependent_patterns = [
                r"according\s+to\s+claim\s+\d+",
                r"as\s+in\s+claim\s+\d+",
                r"of\s+claim\s+\d+",
                r"as\s+recited\s+in\s+claim\s+\d+",
                # Spanish / French
                r"seg\u00fan\s+la\s+reivindicaci\u00f3n\s+\d+",
                r"selon\s+la\s+revendication\s+\d+",
            ]
            is_dependent = any(re.search(p, claim, re.IGNORECASE) for p in dependent_patterns)
            if not is_dependent and len(claim) > 50:
                independent_claims.append(claim)

        return independent_claims

    @staticmethod
    def _extract_description(item: Dict) -> str:
        """Extract description text from a patent item."""
        description = item.get("description", "")
        if not description:
            raw = item.get("raw_json", "")
            if raw:
                try:
                    import json
                    data = json.loads(raw)
                    description = data.get("description", "")
                except (json.JSONDecodeError, TypeError):
                    pass
        return description

    # ── Report generation ────────────────────────────────────

    @staticmethod
    def generate_filter_report(result: Dict[str, Any]) -> str:
        """Generate a human-readable filtering report."""
        stats = result["stats"]
        lines = [
            "# Patent Filtering Report",
            "",
            "## Layer 1: Abstract / Title Screening",
            f"- Input: {stats['input']} patents",
            f"- Passed: {stats['layer1_pass']} patents",
            f"- Rejected: {stats['rejection_reasons']['layer1']} patents (low relevance)",
            "",
            "## Layer 2: Independent Claims Analysis",
            f"- Input: {stats['layer1_pass']} patents",
            f"- Passed: {stats['layer2_pass']} patents",
            f"- Rejected: {stats['rejection_reasons']['layer2']} patents (no matching claims)",
            "",
            "## Layer 3: Detailed Description",
            f"- Input: {stats['layer2_pass']} patents",
            f"- Passed: {stats['layer3_pass']} patents",
            f"- Rejected: {stats['rejection_reasons']['layer3']} patents (insufficient detail)",
            "",
            "## Summary",
            f"- Final: {stats['layer3_pass']} / {stats['input']} patents ({100*stats['layer3_pass']/max(stats['input'],1):.1f}%)",
        ]
        return "\n".join(lines)


if __name__ == "__main__":
    print("=== PatentFilter Demo ===")
    print("This module requires enriched patent items (with claims, description)")
    print("Usage:")
    print("  from patent_filter import PatentFilter")
    print("  filter = PatentFilter()")
    print("  result = filter.filter_pipeline(items, keywords, target_features)")
    print("  print(PatentFilter.generate_filter_report(result))")

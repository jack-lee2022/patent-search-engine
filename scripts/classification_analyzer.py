#!/usr/bin/env python3
"""
ClassificationAnalyzer — Reference implementation for patent-search-engine skill.

Step 3: "Use IPC / CPC classification codes" — enhances keyword search by:
1. Extracting classification codes from seed patents
2. Analyzing code frequency to find the most relevant classes
3. Reversing the search: use top classifications to find MORE patents
4. Recommending classification codes from keywords

Usage:
    from classification_analyzer import ClassificationAnalyzer

    analyzer = ClassificationAnalyzer()

    # 1. Extract from seed patents
    codes = analyzer.extract_from_items(seed_items)
    print(codes.top_ipc())       # [("A61B5/00", 12), ("A61B5/01", 8), ...]
    print(codes.top_cpc())       # [("A61B5/0245", 5), ...]

    # 2. Recommend from keywords
    rec = analyzer.recommend_from_keywords(["tongue pressure", "sensor"])
    print(rec["ipc"])   # ["A61B5/00", "A61B5/01"]
    print(rec["cpc"])   # ["A61B5/0245", ...]

    # 3. Reverse search loop
    new_items = analyzer.reverse_search(
        collector, keywords, top_n_ipc=3, top_n_cpc=3
    )
"""

import re
from collections import Counter
from typing import List, Dict, Optional, Tuple, Any


class ClassificationCodes:
    """Container for extracted classification codes with frequency info."""

    def __init__(self):
        self.ipc: Counter = Counter()
        self.cpc: Counter = Counter()
        self.ipc_detail: Dict[str, List[str]] = {}  # code -> [patent_ids]
        self.cpc_detail: Dict[str, List[str]] = {}  # code -> [patent_ids]

    def add_ipc(self, code: str, patent_id: str):
        """Add an IPC code with its source patent."""
        self.ipc[code] += 1
        self.ipc_detail.setdefault(code, []).append(patent_id)

    def add_cpc(self, code: str, patent_id: str):
        """Add a CPC code with its source patent."""
        self.cpc[code] += 1
        self.cpc_detail.setdefault(code, []).append(patent_id)

    def top_ipc(self, n: int = 10) -> List[Tuple[str, int]]:
        """Return top N IPC codes by frequency."""
        return self.ipc.most_common(n)

    def top_cpc(self, n: int = 10) -> List[Tuple[str, int]]:
        """Return top N CPC codes by frequency."""
        return self.cpc.most_common(n)

    def get_patents_for_ipc(self, code: str) -> List[str]:
        """Return all patent IDs that have this IPC code."""
        return self.ipc_detail.get(code, [])

    def get_patents_for_cpc(self, code: str) -> List[str]:
        """Return all patent IDs that have this CPC code."""
        return self.cpc_detail.get(code, [])

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for reporting."""
        return {
            "total_ipc_codes": len(self.ipc),
            "total_cpc_codes": len(self.cpc),
            "top_ipc": self.top_ipc(5),
            "top_cpc": self.top_cpc(5),
        }


class ClassificationAnalyzer:
    """Extract, analyze, and recommend IPC/CPC classification codes."""

    # Known keyword → classification mappings (built from experience)
    # Can be extended with LLM or database lookups
    KEYWORD_TO_IPC: Dict[str, List[str]] = {
        "tongue pressure": ["A61B5/00", "A61B5/01"],
        "tongue muscle": ["A61B5/00", "A61B5/11"],
        "oral rehabilitation": ["A61F5/00", "A61H1/00"],
        "sleep apnea": ["A61F5/56", "A61M16/00"],
        "cpap": ["A61M16/00", "A61M16/06"],
        "negative pressure": ["A61M1/00", "A61H9/00"],
        "swallowing": ["A61B5/11", "A61B5/103"],
        "sensor": ["A61B5/00", "A61B5/01"],
        "mesh nebulizer": ["A61M11/00", "A61M11/06"],
    }

    KEYWORD_TO_CPC: Dict[str, List[str]] = {
        "tongue pressure": ["A61B5/0245", "A61B5/103"],
        "sleep apnea": ["A61F5/56", "A61M16/00"],
        "cpap": ["A61M16/0051", "A61M16/06"],
        "negative pressure": ["A61H9/0075", "A61M1/00"],
        "sensor": ["A61B5/0245", "A61B2560/0219"],
    }

    def __init__(self):
        self.codes = ClassificationCodes()

    # ── Extraction from Google Patents items ───────────────────────

    def extract_from_items(self, items: List[Dict]) -> ClassificationCodes:
        """Extract IPC/CPC codes from a list of Google Patents items.

        Google Patents item structure for classifications:
        item["patent"]["classification"] = [
            {"code": "A61B5/00", "classification": "CPC", "type": "CPC"},
            {"code": "A61B5/01", "classification": "CPC", "type": "CPC"},
            {"code": "A61B5/00", "classification": "IPC", "type": "IPC"},
        ]
        """
        self.codes = ClassificationCodes()

        for item in items:
            patent = item.get("patent", {})
            patent_id = patent.get("publication_number", "unknown")
            classifications = patent.get("classification", [])

            if not classifications:
                continue

            for cls in classifications:
                if not isinstance(cls, dict):
                    continue
                code = cls.get("code", "")
                cls_type = cls.get("classification", "").upper()

                if not code:
                    continue

                if cls_type == "IPC" or cls_type == "INT":
                    # Normalize IPC: keep first 4 chars + subgroup
                    normalized = self._normalize_ipc(code)
                    self.codes.add_ipc(normalized, patent_id)
                elif cls_type == "CPC":
                    normalized = self._normalize_cpc(code)
                    self.codes.add_cpc(normalized, patent_id)

        return self.codes

    def extract_from_epo_items(self, items: List[Dict]) -> ClassificationCodes:
        """Extract IPC/CPC from EPO OPS items.

        EPO OPS structure:
        item["ops:bibliographic-data"]["classifications-ipcr"]["classification-ipcr"]
        item["ops:bibliographic-data"]["patent-classifications"]["patent-classification"]
        """
        self.codes = ClassificationCodes()

        for item in items:
            biblio = item.get("ops:bibliographic-data", {})
            patent_id = self._extract_patent_id(item)

            # IPC from EPO OPS
            ipcr = biblio.get("classifications-ipcr", {})
            if ipcr:
                ipcr_list = ipcr.get("classification-ipcr", [])
                if not isinstance(ipcr_list, list):
                    ipcr_list = [ipcr_list] if ipcr_list else []
                for ipcr_item in ipcr_list:
                    if isinstance(ipcr_item, dict):
                        text = ipcr_item.get("text", "")
                        if text:
                            normalized = self._normalize_ipc(text)
                            self.codes.add_ipc(normalized, patent_id)

            # CPC from EPO OPS
            patent_cls = biblio.get("patent-classifications", {})
            if patent_cls:
                cls_list = patent_cls.get("patent-classification", [])
                if not isinstance(cls_list, list):
                    cls_list = [cls_list] if cls_list else []
                for cls_item in cls_list:
                    if isinstance(cls_item, dict):
                        scheme = cls_item.get("classification-scheme", "")
                        if scheme and "cpc" in scheme.lower():
                            text = cls_item.get("classification-symbol", "")
                            if text:
                                normalized = self._normalize_cpc(text)
                                self.codes.add_cpc(normalized, patent_id)

        return self.codes

    # ── Normalization ─────────────────────────────────────────────

    @staticmethod
    def _normalize_ipc(code: str) -> str:
        """Normalize IPC code: A61B5/00→0→A61B5/00"""
        code = code.strip()
        # Remove extra spaces
        code = re.sub(r"\s+", "", code)
        # Keep section (A), class (61), subclass (B), group (5), subgroup (/00)
        match = re.match(r"([A-Z])(\d{2})([A-Z])(\d+)(/\d+)", code)
        if match:
            return f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}{match.group(5)}"
        return code

    @staticmethod
    def _normalize_cpc(code: str) -> str:
        """Normalize CPC code. Similar to IPC but more granular."""
        code = code.strip()
        code = re.sub(r"\s+", "", code)
        return code

    # ── Recommendation ───────────────────────────────────────

    def recommend_from_keywords(self, keywords: List[str]) -> Dict[str, List[str]]:
        """Recommend IPC/CPC codes from a list of keywords.

        Looks up in the built-in keyword map. Returns a dict:
        {"ipc": [...], "cpc": [...]}
        """
        ipc_codes = set()
        cpc_codes = set()

        for kw in keywords:
            kw_lower = kw.lower()
            for key, codes in self.KEYWORD_TO_IPC.items():
                if key in kw_lower or kw_lower in key:
                    ipc_codes.update(codes)
            for key, codes in self.KEYWORD_TO_CPC.items():
                if key in kw_lower or kw_lower in key:
                    cpc_codes.update(codes)

        return {
            "ipc": sorted(ipc_codes),
            "cpc": sorted(cpc_codes),
        }

    def recommend_from_analysis(self, codes: ClassificationCodes,
                                 min_freq: int = 2) -> Dict[str, List[str]]:
        """Recommend codes that appear at least min_freq times in the analysis."""
        top_ipc = [code for code, freq in codes.top_ipc(20) if freq >= min_freq]
        top_cpc = [code for code, freq in codes.top_cpc(20) if freq >= min_freq]
        return {
            "ipc": top_ipc,
            "cpc": top_cpc,
        }

    # ── Reverse Search Loop ────────────────────────────────────

    def reverse_search(
        self,
        collector,
        keywords: List[str],
        seed_max_results: int = 20,
        top_n_ipc: int = 3,
        top_n_cpc: int = 3,
        max_results_per_code: int = 50,
    ) -> Dict[str, Any]:
        """
        The reverse-search loop:
        1. Search by keywords to get seed patents
        2. Extract classification codes from seeds
        3. Use top codes to search for MORE patents
        4. Merge and deduplicate

        Args:
            collector: A collector object with fetch_by_keywords() and fetch_by_ipc()
            keywords: Initial keywords for seed search
            seed_max_results: Max seed patents to analyze
            top_n_ipc: How many top IPC codes to reverse-search
            top_n_cpc: How many top CPC codes to reverse-search
            max_results_per_code: Max results per classification code

        Returns:
            dict with:
                - "seed_items": list of seed patents
                - "codes": ClassificationCodes object
                - "reverse_items": list of patents found by classification
                - "merged_items": deduplicated combined list
                - "report": summary dict
        """
        # Step 1: Seed search
        print(f"[REVERSE] Step 1: Seed search with keywords: {keywords}")
        seed_items = collector.fetch_by_keywords(keywords, max_results=seed_max_results)
        print(f"[REVERSE] Got {len(seed_items)} seed items")

        # Step 2: Extract classifications
        print("[REVERSE] Step 2: Extracting classification codes")
        codes = self.extract_from_items(seed_items)
        print(f"[REVERSE] Extracted {len(codes.ipc)} IPC codes, {len(codes.cpc)} CPC codes")
        print(f"[REVERSE] Top IPC: {codes.top_ipc(top_n_ipc)}")
        print(f"[REVERSE] Top CPC: {codes.top_cpc(top_n_cpc)}")

        # Step 3: Reverse search by top IPC codes
        reverse_items = []
        top_ipc_codes = codes.top_ipc(top_n_ipc)
        for ipc_code, freq in top_ipc_codes:
            print(f"[REVERSE] Step 3a: Reverse search IPC {ipc_code} (freq={freq})")
            items = collector.fetch_by_ipc(ipc_code, max_results=max_results_per_code)
            print(f"[REVERSE]   Found {len(items)} items")
            reverse_items.extend(items)

        # Step 4: Reverse search by top CPC codes (if supported)
        # Note: Google Patents XHR API doesn't directly support CPC search via classification
        # But we can use cpc/ prefix in keyword query
        top_cpc_codes = codes.top_cpc(top_n_cpc)
        for cpc_code, freq in top_cpc_codes:
            print(f"[REVERSE] Step 3b: Reverse search CPC {cpc_code} (freq={freq})")
            # Fallback: use cpc/ prefix in keyword search
            cpc_query = f"cpc/{cpc_code}"
            items = collector.fetch_by_keywords(cpc_query, max_results=max_results_per_code)
            print(f"[REVERSE]   Found {len(items)} items")
            reverse_items.extend(items)

        # Step 5: Merge and deduplicate
        from result_merger import ResultMerger
        all_items = seed_items + reverse_items
        merged = ResultMerger.deduplicate(all_items)
        print(f"[REVERSE] Step 4: Merged {len(seed_items)} + {len(reverse_items)} = {len(merged)} unique")

        report = {
            "seed_count": len(seed_items),
            "reverse_count": len(reverse_items),
            "merged_count": len(merged),
            "top_ipc": top_ipc_codes,
            "top_cpc": top_cpc_codes,
        }

        return {
            "seed_items": seed_items,
            "codes": codes,
            "reverse_items": reverse_items,
            "merged_items": merged,
            "report": report,
        }

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _extract_patent_id(item: Dict) -> str:
        """Extract patent ID from an EPO OPS item."""
        biblio = item.get("ops:bibliographic-data", {})
        pub_ref = biblio.get("publication-reference", {})
        doc_ids = pub_ref.get("document-id", [])
        if not isinstance(doc_ids, list):
            doc_ids = [doc_ids] if doc_ids else []
        for did in doc_ids:
            if isinstance(did, dict):
                country = did.get("country", "")
                number = did.get("doc-number", "")
                kind = did.get("kind", "")
                if country and number:
                    return f"{country}{number}{kind}"
        return "unknown"


if __name__ == "__main__":
    import json

    print("=== ClassificationAnalyzer Demo ===")
    analyzer = ClassificationAnalyzer()

    # Demo: recommend from keywords
    rec = analyzer.recommend_from_keywords(["tongue pressure", "sensor", "sleep apnea"])
    print("\nRecommended IPC:", rec["ipc"])
    print("Recommended CPC:", rec["cpc"])

    # Demo: empty reverse search (would need a collector in real use)
    print("\nTo run reverse_search, provide a collector with fetch_by_keywords() and fetch_by_ipc()")

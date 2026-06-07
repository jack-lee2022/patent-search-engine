#!/usr/bin/env python3
"""
SynonymExpander — Reference implementation for patent-search-engine skill.

Step 2: "Extract technical features and build keywords" — expands keywords with:
- Synonyms (e.g., "negative pressure" ↔ "vacuum" ↔ "suction")
- Hyponyms (e.g., "sensor" → "piezoelectric pressure sensor")
- Hypernyms (e.g., "piezoelectric pressure sensor" → "sensor")
- Related technical terms (e.g., "tongue pressure" → "oral pressure", "lingual pressure")

Usage:
    from synonym_expander import SynonymExpander
    from keyword_translator import KeywordTranslator

    translator = KeywordTranslator()
    queries = translator.translate("舌壓測定")

    expander = SynonymExpander()
    expanded = expander.expand(queries)
    # → {"tongue pressure": ["oral pressure", "lingual pressure", ...], ...}

    # Or generate all expanded queries
    all_queries = expander.generate_expanded_queries(queries)
"""

import json
import os
from typing import List, Dict, Optional, Set


class SynonymExpander:
    """Expand patent keywords with synonyms, hyponyms, and related technical terms."""

    # Built-in synonym database for common patent terms
    # Can be extended with LLM or external thesaurus
    SYNONYM_DB: Dict[str, List[str]] = {
        # Pressure measurement
        "tongue pressure": ["oral pressure", "lingual pressure", "palatal pressure", "intraoral pressure"],
        "negative pressure": ["vacuum", "suction", "subatmospheric pressure", "reduced pressure"],
        "pressure sensor": ["pressure transducer", "pressure gauge", "pressure detector", "force sensor"],
        "pressure measurement": ["pressure detection", "pressure monitoring", "force measurement", "pressure sensing"],
        "piezoelectric": ["piezo", "piezoelectric transducer", "PZT", "piezoelectric element"],

        # Muscle / training
        "tongue muscle": ["lingual muscle", "oral muscle", "muscle of tongue", "tongue tissue"],
        "tongue strength": ["tongue force", "lingual strength", "oral strength", "tongue power"],
        "tongue training": ["tongue exercise", "lingual training", "oral rehabilitation", "muscle training"],
        "dysphagia": ["swallowing difficulty", "deglutition disorder", "swallowing dysfunction", "feeding disorder"],
        "swallowing": ["deglutition", "ingestion", "feeding", "oral intake"],

        # Device / apparatus
        "device": ["apparatus", "instrument", "equipment", "machine", "system", "tool"],
        "apparatus": ["device", "instrument", "equipment", "machine"],
        "sensor": ["detector", "transducer", "probe", "sensing element", "pickup"],
        "controller": ["control unit", "control device", "regulator", "processor", "microcontroller"],
        "measurement": ["detection", "sensing", "monitoring", "assessment", "evaluation", "determination"],

        # Medical terms
        "rehabilitation": ["therapy", "treatment", "recovery", "restoration", "training"],
        "therapy": ["treatment", "therapy", "intervention", "care", "management"],
        "oral": ["mouth", "buccal", "intraoral", "dental"],
        "sleep apnea": ["OSA", "obstructive sleep apnea", "sleep disordered breathing", "SDB"],
        "cpap": ["continuous positive airway pressure", "positive airway pressure", "PAP"],

        # Nebulizer
        "nebulizer": ["atomizer", "inhaler", "aerosol generator", "spray device", "mist generator"],
        "mesh": ["membrane", "screen", "perforated plate", "micromesh", "aperture plate"],
        "aerosol": ["mist", "spray", "atomized particles", "droplets", "inhalation"],
        "ultrasonic": ["ultrasound", "piezoelectric", "vibration", "acoustic"],
    }

    # Hyponyms: broader term → narrower terms
    HYPONYMS: Dict[str, List[str]] = {
        "sensor": ["pressure sensor", "force sensor", "strain gauge", "load cell", "piezoelectric sensor", "capacitive sensor"],
        "pressure sensor": ["piezoelectric pressure sensor", "strain gauge pressure sensor", "capacitive pressure sensor", "MEMS pressure sensor"],
        "device": ["medical device", "therapeutic device", "measurement device", "training device", "rehabilitation device"],
        "nebulizer": ["mesh nebulizer", "jet nebulizer", "ultrasonic nebulizer", "vibrating mesh nebulizer", "piezoelectric nebulizer"],
        "controller": ["microcontroller", "PLC", "digital signal processor", "ARM processor", "embedded controller"],
        "material": ["silicone", "elastomer", "polymer", "biocompatible material", "thermoplastic", "metal alloy"],
    }

    # Hypernyms: narrower term → broader terms
    HYPERNYMS: Dict[str, List[str]] = {
        "piezoelectric pressure sensor": ["pressure sensor", "sensor", "transducer"],
        "mesh nebulizer": ["nebulizer", "atomizer", "aerosol generator"],
        "tongue pressure meter": ["pressure measurement device", "medical device", "instrument"],
        "sleep apnea mask": ["respiratory device", "medical device", "therapeutic apparatus"],
    }

    def __init__(self, llm_client=None):
        self.llm = llm_client  # Optional LLM for dynamic expansion

    def expand(self, keywords: List[str]) -> Dict[str, List[str]]:
        """Expand each keyword with synonyms, hyponyms, and hypernyms.

        Returns:
            {"keyword": ["syn1", "syn2", ...], ...}
        """
        result = {}
        for kw in keywords:
            if kw.startswith("entity:"):
                # Don't expand entity markers
                continue
            expanded = self._expand_single(kw)
            if expanded:
                result[kw] = expanded
        return result

    def _expand_single(self, keyword: str) -> List[str]:
        """Expand a single keyword."""
        keyword_lower = keyword.lower()
        expanded = set()

        # 1. Exact match in synonym DB
        for key, syns in self.SYNONYM_DB.items():
            if key in keyword_lower or keyword_lower in key:
                expanded.update(syns)

        # 2. Hyponyms
        for key, hypos in self.HYPONYMS.items():
            if key in keyword_lower or keyword_lower in key:
                expanded.update(hypos)

        # 3. Hypernyms
        for key, hypers in self.HYPERNYMS.items():
            if key in keyword_lower or keyword_lower in key:
                expanded.update(hypers)

        # 4. LLM expansion (if available)
        if self.llm and not expanded:
            llm_syns = self._llm_expand(keyword)
            if llm_syns:
                expanded.update(llm_syns)

        # Remove duplicates and the original keyword
        result = [s for s in expanded if s.lower() != keyword_lower]
        return result

    def _llm_expand(self, keyword: str) -> List[str]:
        """Use LLM to generate synonyms and related terms."""
        if not self.llm:
            return []
        prompt = f"""You are a patent search expert.
For the keyword "{keyword}", list 5-8 synonyms, alternative names, or closely related technical terms
that might be used in patent documents.

Output ONLY a JSON array of strings. No explanation.

Example: ["oral pressure", "lingual pressure", "palatal pressure"]
"""
        try:
            raw = self.llm.call(prompt, temperature=0.1, max_tokens=200)
            if raw:
                parsed = self.llm.extract_json(raw)
                if isinstance(parsed, list):
                    return [str(s).strip() for s in parsed if str(s).strip()]
        except Exception as e:
            print(f"[SYNONYM LLM ERROR] {e}")
        return []

    def generate_expanded_queries(
        self,
        keywords: List[str],
        include_original: bool = True,
        include_synonyms: bool = True,
        include_hyponyms: bool = True,
        include_hypernyms: bool = False,
        max_per_keyword: int = 5,
    ) -> List[str]:
        """Generate a flat list of all expanded queries.

        Args:
            keywords: Original keywords
            include_original: Keep original keywords in output
            include_synonyms: Include synonym expansions
            include_hyponyms: Include hyponym expansions
            include_hypernyms: Include hypernym expansions
            max_per_keyword: Max expansions per keyword

        Returns:
            Flat list of query strings
        """
        expanded = self.expand(keywords)
        all_queries = []

        for kw in keywords:
            if kw.startswith("entity:"):
                all_queries.append(kw)
                continue

            if include_original:
                all_queries.append(kw)

            syns = expanded.get(kw, [])
            for syn in syns:
                syn_lower = syn.lower()
                # Classify as synonym, hyponym, or hypernym
                is_hyponym = any(
                    syn_lower in [h.lower() for h in hypos]
                    for hypos in self.HYPONYMS.values()
                )
                is_hypernym = any(
                    syn_lower in [h.lower() for h in hypers]
                    for hypers in self.HYPERNYMS.values()
                )

                if is_hyponym and include_hyponyms:
                    all_queries.append(syn)
                elif is_hypernym and include_hypernyms:
                    all_queries.append(syn)
                elif not is_hyponym and not is_hypernym and include_synonyms:
                    all_queries.append(syn)

        # Deduplicate and limit
        seen = set()
        unique = []
        for q in all_queries:
            q_lower = q.lower()
            if q_lower not in seen:
                seen.add(q_lower)
                unique.append(q)

        # Limit per keyword
        if max_per_keyword:
            # This is a simple approach; more sophisticated limiting possible
            pass

        return unique

    def generate_boolean_groups(
        self,
        keywords: List[str],
    ) -> Dict[str, List[str]]:
        """Generate OR groups for BooleanQueryBuilder.

        Returns:
            {"tongue pressure": ["tongue pressure", "oral pressure", "lingual pressure", ...], ...}
        """
        expanded = self.expand(keywords)
        groups = {}
        for kw in keywords:
            if kw.startswith("entity:"):
                continue
            syns = expanded.get(kw, [])
            groups[kw] = [kw] + syns
        return groups


if __name__ == "__main__":
    import json

    print("=== SynonymExpander Demo ===")
    expander = SynonymExpander()

    keywords = ["tongue pressure", "sensor", "device", "negative pressure"]
    expanded = expander.expand(keywords)
    print("\nExpanded:")
    for kw, syns in expanded.items():
        print(f"  {kw}: {syns}")

    queries = expander.generate_expanded_queries(keywords)
    print(f"\nAll queries ({len(queries)}):")
    for q in queries:
        print(f"  - {q}")

    groups = expander.generate_boolean_groups(keywords)
    print("\nBoolean OR groups:")
    for base, group in groups.items():
        print(f"  {base}: OR group = {group}")

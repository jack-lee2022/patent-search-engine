#!/usr/bin/env python3
"""
SynonymExpander — Patent keyword expansion for patent-search-engine skill.

Expands input keywords with synonyms, hyponyms, and hypernyms via:
  1. Built-in static database (fast, offline)
  2. Anthropic Claude API (dynamic, covers novel terms — optional)

Usage (CLI):
    python synonym_expander.py "nebulizer"
    python synonym_expander.py "nebulizer" "aerosol" "mesh"
    python synonym_expander.py "nebulizer aerosol mesh"  # auto-splits on spaces

Usage (API):
    from synonym_expander import SynonymExpander
    expander = SynonymExpander()
    expanded = expander.expand(["nebulizer", "mesh"])
    queries   = expander.generate_expanded_queries(["nebulizer", "mesh"])
"""

import json
import sys
import os
from typing import List, Dict, Optional


# ---------------------------------------------------------------------------
# Optional Anthropic LLM client
# ---------------------------------------------------------------------------

class _AnthropicLLMClient:
    """Thin wrapper around the Anthropic SDK for synonym expansion."""

    MODEL = "claude-haiku-4-5-20251001"   # fast, cheap, sufficient for synonym tasks

    def __init__(self):
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            self._client = anthropic.Anthropic(api_key=api_key) if api_key else None
        except ImportError:
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def expand(self, keyword: str) -> List[str]:
        if not self._client:
            return []
        prompt = (
            f'You are a patent search expert specializing in medical devices and drug delivery.\n'
            f'For the patent keyword "{keyword}", list 6-10 synonyms, alternative technical names, '
            f'or closely related terms commonly found in patent documents.\n\n'
            f'Rules:\n'
            f'- Include both broad and narrow terms\n'
            f'- Include abbreviations if common (e.g. VMN for vibrating mesh nebulizer)\n'
            f'- Output ONLY a JSON array of strings. No explanation.\n\n'
            f'Example output: ["oral pressure", "lingual pressure", "palatal pressure"]'
        )
        try:
            msg = self._client.messages.create(
                model=self.MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            # Extract JSON array from response
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
                if isinstance(parsed, list):
                    return [str(s).strip() for s in parsed if str(s).strip()]
        except Exception as e:
            print(f"[SYNONYM LLM ERROR] {e}")
        return []


# ---------------------------------------------------------------------------
# SynonymExpander
# ---------------------------------------------------------------------------

class SynonymExpander:
    """Expand patent keywords using a static database + optional LLM fallback."""

    # ------------------------------------------------------------------
    # Static synonym database
    # ------------------------------------------------------------------

    SYNONYM_DB: Dict[str, List[str]] = {

        # ── Nebulizer types ────────────────────────────────────────────
        "nebulizer": [
            "atomizer", "inhaler", "aerosol generator", "spray device",
            "mist generator", "inhalation device", "aerosol therapy device",
            "nebuliser",                          # British spelling
        ],
        "jet nebulizer": [
            "pneumatic nebulizer", "air-jet nebulizer", "compressor nebulizer",
            "venturi nebulizer", "breath-enhanced nebulizer", "air-driven nebulizer",
            "baffled nebulizer",
        ],
        "ultrasonic nebulizer": [
            "ultrasonic atomizer", "piezoelectric nebulizer", "ultrasound nebulizer",
            "high-frequency nebulizer",
        ],
        "mesh nebulizer": [
            "vibrating mesh nebulizer", "vibrating membrane nebulizer",
            "electronic nebulizer", "aperture plate nebulizer",
            "perforated membrane nebulizer", "VMN",
        ],
        "vibrating mesh": [
            "oscillating mesh", "vibrating membrane", "vibrating plate",
            "vibrating aperture", "resonant mesh", "microporous membrane",
        ],
        "breath-actuated nebulizer": [
            "breath-activated nebulizer", "inspiratory-driven nebulizer",
            "triggered nebulizer", "synchronised nebulizer",
        ],
        "smart nebulizer": [
            "connected nebulizer", "intelligent nebulizer", "digital nebulizer",
            "IoT nebulizer", "electronic nebulizer", "sensor-integrated nebulizer",
        ],
        "portable nebulizer": [
            "handheld nebulizer", "pocket nebulizer", "battery-operated nebulizer",
            "travel nebulizer", "wearable nebulizer",
        ],

        # ── Core components ────────────────────────────────────────────
        "mesh": [
            "membrane", "perforated plate", "aperture plate", "micromesh",
            "screen", "microporous membrane", "porous plate", "sieve plate",
            "orifice plate",
        ],
        "aerosol": [
            "mist", "spray", "atomized particles", "droplets",
            "aerosolized medication", "inhalable particles", "respirable particles",
            "fine particle fraction", "FPF",
        ],
        "droplet": [
            "particle", "aerosol droplet", "liquid droplet", "microdroplet",
            "spray droplet", "atomized droplet",
        ],
        "piezoelectric": [
            "piezo", "PZT", "piezoelectric transducer", "piezoelectric element",
            "piezoelectric actuator", "piezo crystal", "piezoelectric disc",
        ],
        "transducer": [
            "piezoelectric transducer", "ultrasonic transducer", "vibration generator",
            "actuator", "oscillator",
        ],
        "baffle": [
            "impact surface", "deflector", "impactor", "collision plate",
            "impact baffle", "spray baffle",
        ],
        "nozzle": [
            "orifice", "jet", "aperture", "spray nozzle", "fluid nozzle",
        ],
        "reservoir": [
            "medication chamber", "drug reservoir", "liquid chamber",
            "medicine cup", "drug container", "solution container",
        ],

        # ── Drug delivery ──────────────────────────────────────────────
        "drug delivery": [
            "medication delivery", "pharmaceutical delivery",
            "pulmonary drug delivery", "inhalation therapy",
            "therapeutic delivery", "aerosolized drug delivery",
        ],
        "inhalation": [
            "inspiration", "breathing in", "inhaling",
            "respiratory delivery", "pulmonary inhalation",
        ],
        "pulmonary": [
            "lung", "respiratory", "bronchial", "airway", "lower respiratory",
        ],
        "aerosol therapy": [
            "inhalation therapy", "nebulization therapy",
            "respiratory therapy", "aerosol treatment",
        ],
        "drug aerosol": [
            "medication aerosol", "pharmaceutical aerosol", "inhalable drug",
            "aerosolized medicine", "respirable drug",
        ],

        # ── Atomization technology ─────────────────────────────────────
        "ultrasonic": [
            "ultrasound", "high-frequency vibration",
            "acoustic vibration", "sonic", "MHz frequency",
        ],
        "vibration": [
            "oscillation", "resonance", "vibrating", "frequency vibration",
            "mechanical vibration",
        ],
        "atomization": [
            "nebulization", "aerosolization", "spraying",
            "misting", "vaporization", "aerosolizing",
        ],
        "particle size": [
            "droplet size", "aerosol particle size", "mass median aerodynamic diameter",
            "MMAD", "geometric standard deviation", "GSD", "respirable fraction",
        ],

        # ── Monitoring / Smart features ────────────────────────────────
        "monitoring": [
            "tracking", "sensing", "detection", "measurement",
            "surveillance", "real-time monitoring",
        ],
        "compliance": [
            "adherence", "medication adherence", "patient compliance",
            "usage tracking", "treatment adherence",
        ],
        "flow sensor": [
            "airflow sensor", "breath sensor", "inhalation sensor",
            "flow detector", "respiratory flow sensor",
        ],

        # ── Medical conditions / applications ──────────────────────────
        "asthma": [
            "bronchial asthma", "reactive airway disease", "airway hyperresponsiveness",
        ],
        "COPD": [
            "chronic obstructive pulmonary disease", "chronic bronchitis", "emphysema",
            "obstructive lung disease",
        ],
        "cystic fibrosis": [
            "CF", "mucoviscidosis", "pulmonary cystic fibrosis",
        ],

        # ── General device terms ───────────────────────────────────────
        "device": [
            "apparatus", "instrument", "equipment", "machine", "system",
        ],
        "sensor": [
            "detector", "transducer", "probe", "sensing element", "pickup",
        ],
        "controller": [
            "control unit", "control device", "processor",
            "microcontroller", "embedded controller",
        ],

        # ── Pressure / flow (legacy entries retained) ──────────────────
        "negative pressure": [
            "vacuum", "suction", "subatmospheric pressure", "reduced pressure",
        ],
        "pressure sensor": [
            "pressure transducer", "pressure gauge", "pressure detector", "force sensor",
        ],
    }

    # ------------------------------------------------------------------
    # Hyponyms (broad → specific)
    # ------------------------------------------------------------------

    HYPONYMS: Dict[str, List[str]] = {
        "nebulizer": [
            "jet nebulizer", "ultrasonic nebulizer", "vibrating mesh nebulizer",
            "breath-actuated nebulizer", "smart nebulizer", "portable nebulizer",
            "nasal nebulizer", "mesh nebulizer",
        ],
        "aerosol generator": [
            "vibrating mesh", "aperture plate", "ultrasonic transducer",
            "venturi jet", "piezoelectric membrane",
        ],
        "drug delivery system": [
            "nebulizer system", "inhalation device", "pulmonary delivery device",
            "inhaler", "dry powder inhaler",
        ],
        "sensor": [
            "pressure sensor", "force sensor", "strain gauge",
            "flow sensor", "piezoelectric sensor", "capacitive sensor",
        ],
        "device": [
            "medical device", "therapeutic device", "measurement device",
            "portable device", "wearable device",
        ],
        "mesh": [
            "vibrating mesh", "microporous mesh", "electroformed mesh",
            "laser-drilled mesh", "etched aperture plate",
        ],
    }

    # ------------------------------------------------------------------
    # Hypernyms (specific → broad)
    # ------------------------------------------------------------------

    HYPERNYMS: Dict[str, List[str]] = {
        "vibrating mesh nebulizer": ["nebulizer", "aerosol generator", "inhalation device"],
        "jet nebulizer": ["nebulizer", "aerosol generator", "inhalation device"],
        "ultrasonic nebulizer": ["nebulizer", "aerosol generator"],
        "aperture plate": ["mesh", "component", "atomization element"],
        "MMAD": ["particle size", "aerosol characteristic"],
    }

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(self, use_llm: bool = True):
        self._llm = _AnthropicLLMClient() if use_llm else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def expand(self, keywords: List[str]) -> Dict[str, List[str]]:
        """Expand each keyword. Returns {keyword: [synonym, ...]}."""
        result = {}
        for kw in keywords:
            kw = kw.strip()
            if not kw or kw.startswith("entity:"):
                continue
            syns = self._expand_single(kw)
            if syns:
                result[kw] = syns
        return result

    def _expand_single(self, keyword: str) -> List[str]:
        kw_lower = keyword.lower()
        expanded: set = set()

        for key, syns in self.SYNONYM_DB.items():
            if key in kw_lower or kw_lower in key:
                expanded.update(syns)

        for key, hypos in self.HYPONYMS.items():
            if key in kw_lower or kw_lower in key:
                expanded.update(hypos)

        for key, hypers in self.HYPERNYMS.items():
            if key in kw_lower or kw_lower in key:
                expanded.update(hypers)

        # LLM fallback when static DB has no match
        if not expanded and self._llm and self._llm.available:
            print(f"[SYNONYM] '{keyword}' not in static DB — querying LLM...")
            llm_syns = self._llm.expand(keyword)
            expanded.update(llm_syns)

        return [s for s in expanded if s.lower() != kw_lower]

    def generate_expanded_queries(
        self,
        keywords: List[str],
        include_original: bool = True,
        max_per_keyword: int = 8,
    ) -> List[str]:
        """Return a flat deduplicated list of all queries."""
        expanded = self.expand(keywords)
        all_queries: List[str] = []
        seen: set = set()

        def _add(q: str):
            if q.lower() not in seen:
                seen.add(q.lower())
                all_queries.append(q)

        for kw in keywords:
            kw = kw.strip()
            if not kw:
                continue
            if include_original:
                _add(kw)
            for syn in list(expanded.get(kw, []))[:max_per_keyword]:
                _add(syn)

        return all_queries

    def generate_boolean_groups(self, keywords: List[str]) -> Dict[str, List[str]]:
        """Return OR groups: {keyword: [keyword, syn1, syn2, ...]}."""
        expanded = self.expand(keywords)
        return {
            kw: [kw] + expanded.get(kw, [])
            for kw in keywords
            if kw.strip() and not kw.startswith("entity:")
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_keywords(args: List[str]) -> List[str]:
    """
    Accept keywords in two forms:
      python synonym_expander.py nebulizer mesh aerosol   → ["nebulizer", "mesh", "aerosol"]
      python synonym_expander.py "nebulizer mesh aerosol" → ["nebulizer", "mesh", "aerosol"]
    """
    if not args:
        return []
    # If only one arg and contains spaces, split it
    if len(args) == 1 and " " in args[0]:
        return [w.strip() for w in args[0].split() if w.strip()]
    return [a.strip() for a in args if a.strip()]


if __name__ == "__main__":
    raw_args = sys.argv[1:]

    if raw_args:
        keywords = _parse_keywords(raw_args)
    else:
        # Default demo
        keywords = ["nebulizer", "mesh", "aerosol", "ultrasonic"]

    print(f"=== SynonymExpander ===")
    print(f"Input keywords: {keywords}\n")

    expander = SynonymExpander(use_llm=True)
    expanded = expander.expand(keywords)

    print("Expanded synonyms:")
    for kw, syns in expanded.items():
        print(f"  [{kw}]")
        for s in syns:
            print(f"    - {s}")

    queries = expander.generate_expanded_queries(keywords)
    print(f"\nAll search queries ({len(queries)}):")
    for q in queries:
        print(f"  - {q}")

    groups = expander.generate_boolean_groups(keywords)
    print(f"\nBoolean OR groups:")
    for base, group in groups.items():
        print(f"  {base}: {group}")

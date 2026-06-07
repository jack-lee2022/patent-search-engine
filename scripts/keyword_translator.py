#!/usr/bin/env python3
"""
KeywordTranslator — Reference implementation for patent-search-engine skill.

Translates Chinese (or any non-English) patent topics into English search queries
optimized for Google Patents. Includes entity extraction, manual fallback map,
LLM translation, and SQLite caching.

Usage:
    python keyword_translator.py "舌肌力訓練"
    python keyword_translator.py "JMS舌壓測定儀"
"""

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import List, Optional

# Manual fallback mapping for common domains
MANUAL_KEYWORD_MAP = {
    "舌肌力訓練": [
        "tongue strength training",
        "tongue muscle exercise",
        "oral rehabilitation tongue",
        "dysphagia tongue training",
        "tongue strength evaluation",
        "oral muscle trainer",
        "tongue pressure measurement",
        "tongue exercise device",
        "tongue force measurement",
        "tongue muscle strength",
        "oral function test",
        "lingual muscle training",
    ],
    "口腔復健": [
        "oral rehabilitation device",
        "oral exercise therapy",
        "jaw muscle training",
        "oral motor therapy",
        "facial muscle rehabilitation",
        "swallowing evaluation device",
        "oral function rehabilitation",
        "palatal pressure",
    ],
    "睡眠呼吸機": [
        "sleep apnea mask",
        "CPAP device",
        "positive airway pressure",
        "OSA treatment device",
        "nasal CPAP mask",
    ],
    "負壓治療": [
        "negative pressure therapy",
        "negative pressure device",
        "suction therapy",
        "vacuum therapy medical",
    ],
    "阻塞型睡眠呼吸中止症": [
        "obstructive sleep apnea",
        "OSA treatment",
        "sleep apnea therapy",
        "snoring treatment device",
    ],
    "舌壓測定": [
        "tongue pressure measurement",
        "tongue pressure meter",
        "oral pressure sensor",
        "tongue force sensor",
        "lingual pressure measurement",
        "palatal pressure measurement",
        "tongue pressure gauge",
    ],
    "吞嚥障礙評估": [
        "swallowing evaluation device",
        "deglutition assessment",
        "dysphagia evaluation tool",
        "swallowing function test",
        "deglutition disorder device",
    ],
}


class LLMClient:
    """Minimal LLM client for keyword translation. Replace with real implementation."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY", "")

    def call(self, prompt: str, temperature: float = 0.1, max_tokens: int = 400) -> Optional[str]:
        # Placeholder: return None to trigger fallback
        return None

    def extract_json(self, text: str) -> Optional[List[str]]:
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try regex extraction of quoted strings
        found = re.findall(r'"([^"]+)"', text)
        if found:
            return [f.strip() for f in found if len(f.strip()) > 2]
        return None


class KeywordTranslator:
    """Translate Chinese patent topics into English search queries."""

    def __init__(self, cache_db_path: Optional[str] = None):
        self.llm = LLMClient()
        self.cache_db_path = cache_db_path or "keyword_cache.db"
        self._init_cache()

    def _init_cache(self):
        Path(self.cache_db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache_db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS keyword_cache (
                    topic TEXT PRIMARY KEY,
                    keywords TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            conn.commit()

    def _get_cache(self, topic: str) -> Optional[List[str]]:
        with sqlite3.connect(self.cache_db_path) as conn:
            row = conn.execute(
                "SELECT keywords FROM keyword_cache WHERE topic = ?", (topic,)
            ).fetchone()
            if row:
                return json.loads(row[0])
        return None

    def _set_cache(self, topic: str, keywords: List[str]):
        with sqlite3.connect(self.cache_db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO keyword_cache (topic, keywords) VALUES (?, ?)",
                (topic, json.dumps(keywords, ensure_ascii=False)),
            )
            conn.commit()

    @staticmethod
    def _is_chinese(text: str) -> bool:
        if not text:
            return False
        cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        return cjk_chars / len(text) > 0.3

    def extract_entities(self, topic: str) -> List[str]:
        """Extract company names, brand names, and product identifiers."""
        entities = []
        topic = topic.strip()
        if not topic:
            return entities

        # 1. All-caps acronyms (2-6 letters) — Unicode-aware boundary
        for match in re.finditer(r'(?<![A-Za-z])[A-Z]{2,6}(?![A-Za-z])', topic):
            candidate = match.group()
            if candidate not in {"PDF", "URL", "HTTP", "HTML", "API", "JSON",
                                 "USA", "UK", "EU", "JP", "CN", "TW", "US", "EN",
                                 "MD", "PHD", "ETC", "VS", "IP", "AI", "IoT"}:
                entities.append(candidate)

        # 2. English phrases inside parentheses
        paren_pattern = re.findall(
            r'[\(（]([A-Za-z][A-Za-z0-9\s\-/]+(?:Device|System|Apparatus|Instrument|'
            r'Meter|Gauge|Tool|Method|Technology|Ltd|Limited|Inc|Co\.?|Corp\.?|'
            r'LLC|GmbH|AG|KK|株式会社)?)[\)）]',
            topic
        )
        for m in paren_pattern:
            m = m.strip()
            words = m.split()
            if len(words) >= 2:
                if any(suffix in m for suffix in ["Ltd", "Limited", "Inc", "Co.", "Corp.", "LLC", "GmbH", "AG", "KK", "株式会社"]):
                    clean = m.replace(".", "").strip()
                    entities.append(clean)
                else:
                    entities.append(" ".join(words[:4]))

        # 3. Capitalized word groups (product/brand names)
        for match in re.finditer(r'\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*){1,3})\b', topic):
            candidate = match.group()
            if candidate.lower() not in {"the", "and", "for", "with", "from", "this", "that"}:
                if len(candidate) > 3:
                    entities.append(candidate)

        # Deduplicate
        seen = set()
        unique = []
        for e in entities:
            e_lower = e.lower()
            if e_lower not in seen:
                seen.add(e_lower)
                unique.append(e)
        return unique

    def translate(self, topic: str, force_llm: bool = False) -> List[str]:
        """Translate topic to list of English patent search queries."""
        topic = topic.strip()
        if not topic:
            return []

        # Always extract entities
        entities = self.extract_entities(topic)
        if entities:
            print(f"[TRANSLATOR] Extracted entities: {entities}")

        # 1. English passthrough
        if not self._is_chinese(topic):
            words = [w.strip() for w in topic.replace(",", " ").split() if w.strip()]
            queries = [" ".join(words)]
            if len(words) > 3:
                queries.append(" ".join(words[:3]))
                queries.append(" ".join(words[-3:]))
            for e in entities:
                queries.append(f"entity:{e}")
            return queries

        # 2. Cache hit — MUST re-attach entities
        cached = self._get_cache(topic)
        if cached and not force_llm:
            print(f"[TRANSLATOR] Cache hit for '{topic}'")
            result = list(cached)
            attached = 0
            for e in entities:
                marker = f"entity:{e}"
                if marker not in result:
                    result.append(marker)
                    attached += 1
            if attached:
                print(f"[TRANSLATOR] Re-attached {attached} entity marker(s)")
            return result

        # 3. Manual fallback map
        for key, keywords in MANUAL_KEYWORD_MAP.items():
            if key in topic or topic in key:
                print(f"[TRANSLATOR] Manual fallback for '{topic}'")
                combined = list(keywords)
                for e in entities:
                    if e.lower() not in [k.lower() for k in combined]:
                        combined.append(f"entity:{e}")
                self._set_cache(topic, combined)
                return combined

        # 4. LLM translation
        if not self.llm.api_key:
            print("[TRANSLATOR WARN] No LLM API key")
            return [topic] + [f"entity:{e}" for e in entities]

        print(f"[TRANSLATOR] LLM translating '{topic}'...")
        prompt = f"""You are a patent search expert.
Translate the following topic into 6-8 English patent search queries.
Each query should be 2-4 words, focused on technical terms commonly used in patents.
ALSO extract any company names, brand names, or product names mentioned.
Output ONLY a valid JSON array of strings. No markdown, no explanation.

Topic: {topic}

Example: ["tongue strength training", "tongue muscle exercise device", "JMS", "tongue pressure meter"]
"""
        raw = self.llm.call(prompt, temperature=0.1, max_tokens=400)
        if raw:
            parsed = self.llm.extract_json(raw)
            if isinstance(parsed, list) and parsed:
                keywords = [str(k).strip() for k in parsed if str(k).strip()]
                for e in entities:
                    if e.lower() not in [k.lower() for k in keywords]:
                        keywords.append(f"entity:{e}")
                self._set_cache(topic, keywords)
                print(f"[TRANSLATOR] Got {len(keywords)} queries: {keywords}")
                return keywords
            else:
                found = re.findall(r'"([^"]+)"', raw)
                if found:
                    keywords = [f.strip() for f in found if len(f.strip()) > 2]
                    for e in entities:
                        if e.lower() not in [k.lower() for k in keywords]:
                            keywords.append(f"entity:{e}")
                    self._set_cache(topic, keywords)
                    return keywords

        print("[TRANSLATOR WARN] LLM failed; returning topic as-is")
        return [topic] + [f"entity:{e}" for e in entities]

    def translate_multi(self, topics: List[str]) -> List[str]:
        all_queries = []
        for t in topics:
            all_queries.extend(self.translate(t))
        seen = set()
        return [q for q in all_queries if not (q in seen or seen.add(q))]


if __name__ == "__main__":
    import sys
    translator = KeywordTranslator()
    if len(sys.argv) > 1:
        topic = sys.argv[1]
        queries = translator.translate(topic)
        print(f"\nTopic: {topic}")
        print(f"Queries: {json.dumps(queries, ensure_ascii=False, indent=2)}")
    else:
        test_topics = ["舌肌力訓練", "JMS舌壓測定儀", "oral rehabilitation"]
        for t in test_topics:
            queries = translator.translate(t)
            print(f"\n{t} -> {queries}")

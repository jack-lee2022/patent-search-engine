#!/usr/bin/env python3
"""
BooleanQueryBuilder — Reference implementation for patent-search-engine skill.

Builds patent search queries with Boolean logic (AND, OR, NOT, parentheses)
for both Google Patents and EPO OPS syntax.

This is the core of Step 4: "Combine search terms and execute search".

Usage:
    from boolean_query_builder import BooleanQueryBuilder

    b = BooleanQueryBuilder()
    b.add_or(["negative pressure", "vacuum", "suction"])
    b.add_and(["sensor", "controller"])
    b.add_not("biomedical")
    q = b.build_google_patents()
    # → "(negative pressure OR vacuum OR suction) AND (sensor OR controller) NOT biomedical"
"""

from typing import List, Dict, Optional, Any
import urllib.parse


class BooleanQueryBuilder:
    """Construct Boolean search queries for patent databases."""

    def __init__(self):
        self._or_groups: List[List[str]] = []  # Each group is OR'd internally
        self._and_terms: List[str] = []        # Individual AND terms
        self._not_terms: List[str] = []       # Exclusion terms
        self._raw_fields: Dict[str, str] = {}  # field-specific filters

    # ── Fluent API ─────────────────────────────────────────

    def add_or(self, terms: List[str]) -> "BooleanQueryBuilder":
        """Add an OR group. All terms in the group are OR'd together."""
        if terms:
            self._or_groups.append(terms)
        return self

    def add_and(self, term: str) -> "BooleanQueryBuilder":
        """Add a single term that must be present (AND)."""
        if term:
            self._and_terms.append(term)
        return self

    def add_not(self, term: str) -> "BooleanQueryBuilder":
        """Add an exclusion term (NOT)."""
        if term:
            self._not_terms.append(term)
        return self

    def add_field(self, field: str, value: str) -> "BooleanQueryBuilder":
        """Add a field-specific filter (e.g., classification, country, date)."""
        self._raw_fields[field] = value
        return self

    def add_ipc(self, ipc_code: str) -> "BooleanQueryBuilder":
        """Add IPC classification filter."""
        return self.add_field("classification/ipc", ipc_code)

    def add_cpc(self, cpc_code: str) -> "BooleanQueryBuilder":
        """Add CPC classification filter."""
        return self.add_field("cpc", cpc_code)

    def add_country(self, country: str) -> "BooleanQueryBuilder":
        """Add country filter."""
        return self.add_field("country", country)

    def add_date_after(self, date: str) -> "BooleanQueryBuilder":
        """Add publication date after filter (YYYY-MM-DD)."""
        return self.add_field("after", date)

    def add_date_before(self, date: str) -> "BooleanQueryBuilder":
        """Add publication date before filter (YYYY-MM-DD)."""
        return self.add_field("before", date)

    def add_assignee(self, assignee: str) -> "BooleanQueryBuilder":
        """Add assignee filter."""
        return self.add_field("assignee", assignee)

    def add_inventor(self, inventor: str) -> "BooleanQueryBuilder":
        """Add inventor filter."""
        return self.add_field("inventor", inventor)

    # ── Builders ─────────────────────────────────────────────

    def build_google_patents(self) -> str:
        """Build a Google Patents compatible query string.

        Google Patents supports:
        - AND: implicit space, or explicit AND
        - OR: explicit OR
        - NOT: NOT or -prefix
        - Fields: classification/ipc:, country:, assignee:, after:, before:
        - Parentheses for grouping
        """
        parts: List[str] = []

        # OR groups
        for group in self._or_groups:
            if group:
                parts.append(f"({' OR '.join(group)})")

        # AND terms
        for term in self._and_terms:
            parts.append(term)

        # Field filters
        for field, value in self._raw_fields.items():
            if field == "classification/ipc":
                parts.append(f"classification/ipc:{value}")
            elif field == "cpc":
                parts.append(f"cpc/{value}")
            elif field == "country":
                parts.append(f"country:{value}")
            elif field == "after":
                parts.append(f"after:{value}")
            elif field == "before":
                parts.append(f"before:{value}")
            elif field == "assignee":
                parts.append(f"assignee:{value}")
            elif field == "inventor":
                parts.append(f"inventor:{value}")
            else:
                parts.append(f"{field}:{value}")

        # NOT terms
        for term in self._not_terms:
            parts.append(f"NOT {term}")

        return " AND ".join(parts)

    def build_epo_ops(self) -> str:
        """Build an EPO OPS compatible query string.

        EPO OPS syntax:
        - ti=title, ab=abstract, cl=claims, de=description
        - pa=applicant, pn=publication number, pd=publication date
        - ic=ipc, ci=cpc
        - AND/OR/NOT (uppercase)
        """
        parts: List[str] = []

        # OR groups: title OR abstract
        for group in self._or_groups:
            if group:
                clauses = []
                for term in group:
                    clauses.append(f"ti={term}")
                    clauses.append(f"ab={term}")
                parts.append(f"({' OR '.join(clauses)})")

        # AND terms
        for term in self._and_terms:
            parts.append(f"ti={term}")
            parts.append(f"ab={term}")

        # Field filters
        for field, value in self._raw_fields.items():
            if field == "classification/ipc":
                parts.append(f"ic={value}")
            elif field == "cpc":
                parts.append(f"ci={value}")
            elif field == "country":
                parts.append(f"pn={value}")
            elif field == "after":
                parts.append(f"pd>={value}")
            elif field == "before":
                parts.append(f"pd<={value}")
            elif field == "assignee":
                parts.append(f"pa={value}")
            elif field == "inventor":
                parts.append(f"in={value}")
            else:
                parts.append(f"{field}={value}")

        # NOT terms
        for term in self._not_terms:
            parts.append(f"NOT (ti={term} OR ab={term})")

        return " AND ".join(parts)

    def build_uspto(self) -> str:
        """Build a USPTO Patent Public Search compatible query string.

        USPTO syntax:
        - [ABST/claims/title]/(term) for field search
        - AND/OR/ANDNOT
        - [PD/] for publication date
        """
        parts: List[str] = []

        for group in self._or_groups:
            if group:
                sub = " OR ".join(f"(ABST/{urllib.parse.quote(t)} OR TTL/{urllib.parse.quote(t)})") for t in group)
                parts.append(f"({sub})")

        for term in self._and_terms:
            parts.append(f"(ABST/{urllib.parse.quote(term)} OR TTL/{urllib.parse.quote(term)})")

        for field, value in self._raw_fields.items():
            if field == "classification/ipc":
                parts.append(f"(IC/{value})")
            elif field == "cpc":
                parts.append(f"(CPC/{value})")
            elif field == "country":
                parts.append(f"(COUNTRY/{value})")
            elif field == "after":
                parts.append(f"(PD/{value}->)")
            elif field == "before":
                parts.append(f"(PD/<-{value})")
            elif field == "assignee":
                parts.append(f"(AN/{urllib.parse.quote(value)})")
            elif field == "inventor":
                parts.append(f"(IN/{urllib.parse.quote(value)})")

        for term in self._not_terms:
            parts.append(f"ANDNOT (ABST/{urllib.parse.quote(term)} OR TTL/{urllib.parse.quote(term)})")

        return " AND ".join(parts)

    # ── Convenience methods ─────────────────────────────────

    def build_all(self) -> Dict[str, str]:
        """Return all three query formats at once."""
        return {
            "google_patents": self.build_google_patents(),
            "epo_ops": self.build_epo_ops(),
            "uspto": self.build_uspto(),
        }

    def __repr__(self) -> str:
        return (
            f"BooleanQueryBuilder("
            f"or_groups={self._or_groups}, "
            f"and_terms={self._and_terms}, "
            f"not_terms={self._not_terms}, "
            f"fields={self._raw_fields})"
        )

    def reset(self) -> "BooleanQueryBuilder":
        """Reset all state for reuse."""
        self._or_groups.clear()
        self._and_terms.clear()
        self._not_terms.clear()
        self._raw_fields.clear()
        return self


# ── Higher-level: SearchQueryComposer ──────────────────────

class SearchQueryComposer:
    """Compose a complete search query from a structured patent topic.

    Bridges Step 2 (keyword extraction) and Step 4 (Boolean combination).
    """

    def __init__(self):
        self.builder = BooleanQueryBuilder()

    def compose(
        self,
        keywords: List[str],
        synonyms: Optional[Dict[str, List[str]]] = None,
        assignee: Optional[str] = None,
        ipc: Optional[str] = None,
        cpc: Optional[str] = None,
        country: Optional[str] = None,
        date_after: Optional[str] = None,
        date_before: Optional[str] = None,
        exclusions: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Compose a full query from structured components.

        Args:
            keywords: Primary technical keywords (treated as OR group)
            synonyms: {"keyword": ["syn1", "syn2"]} — each keyword gets its own OR group
            assignee: Company name filter
            ipc: IPC classification code
            cpc: CPC classification code
            country: Country code (e.g., "US")
            date_after: Publication date after (YYYY-MM-DD)
            date_before: Publication date before (YYYY-MM-DD)
            exclusions: Terms to exclude

        Returns:
            Dict with query strings for google_patents, epo_ops, uspto
        """
        self.builder.reset()

        # 1. Synonyms: each keyword + its synonyms form an OR group
        if synonyms:
            for base, syns in synonyms.items():
                group = [base] + syns
                self.builder.add_or(group)
        elif keywords:
            self.builder.add_or(keywords)

        # 2. Field filters
        if assignee:
            self.builder.add_assignee(assignee)
        if ipc:
            self.builder.add_ipc(ipc)
        if cpc:
            self.builder.add_cpc(cpc)
        if country:
            self.builder.add_country(country)
        if date_after:
            self.builder.add_date_after(date_after)
        if date_before:
            self.builder.add_date_before(date_before)

        # 3. Exclusions
        if exclusions:
            for ex in exclusions:
                self.builder.add_not(ex)

        return self.builder.build_all()

    def from_purpose(
        self,
        purpose: str,  # "novelty" | "fto" | "invalidity" | "landscape"
        keywords: List[str],
        target_countries: Optional[List[str]] = None,
        synonyms: Optional[Dict[str, List[str]]] = None,
        ipc: Optional[str] = None,
        cpc: Optional[str] = None,
        exclusions: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Auto-configure search parameters based on search purpose.

        | Purpose | Default filters |
        |---------|---------------|
        | novelty | All countries, all statuses, no date limit |
        | fto | Target countries only, active/granted only, last 20 years |
        | invalidity | All countries, all statuses, no date limit |
        | landscape | All countries, all statuses, last 10 years |
        """
        self.builder.reset()

        if synonyms:
            for base, syns in synonyms.items():
                self.builder.add_or([base] + syns)
        elif keywords:
            self.builder.add_or(keywords)

        if ipc:
            self.builder.add_ipc(ipc)
        if cpc:
            self.builder.add_cpc(cpc)

        if exclusions:
            for ex in exclusions:
                self.builder.add_not(ex)

        if purpose == "fto":
            # FTO: only active patents, target countries, last 20 years
            if target_countries:
                # For EPO OPS we can't OR countries easily; pick first or use multiple queries
                self.builder.add_country(target_countries[0])
            else:
                self.builder.add_country("US")
            self.builder.add_date_after("2005-01-01")
        elif purpose == "landscape":
            self.builder.add_date_after("2015-01-01")

        return self.builder.build_all()


if __name__ == "__main__":
    import json

    # Example 1: Negative pressure therapy with synonyms
    print("=== Example 1: Negative Pressure Therapy ===")
    composer = SearchQueryComposer()
    queries = composer.compose(
        keywords=["negative pressure therapy"],
        synonyms={
            "negative pressure": ["vacuum", "suction"],
            "therapy": ["treatment"],
        },
        ipc="A61M1/00",
        country="US",
        date_after="2020-01-01",
        exclusions=["animal", "veterinary"],
    )
    for source, query in queries.items():
        print(f"\n{source}:")
        print(f"  {query}")

    # Example 2: FTO search
    print("\n=== Example 2: FTO Search for Tongue Pressure Device ===")
    queries = composer.from_purpose(
        purpose="fto",
        keywords=["tongue pressure", "oral pressure"],
        synonyms={
            "tongue pressure": ["oral pressure", "lingual pressure"],
        },
        cpc="A61B5/00",
        target_countries=["US", "EP"],
    )
    for source, query in queries.items():
        print(f"\n{source}:")
        print(f"  {query}")

    # Example 3: Manual builder
    print("\n=== Example 3: Manual Boolean Builder ===")
    b = BooleanQueryBuilder()
    b.add_or(["bicycle", "bike", "cycle"])
    b.add_or(["pedal", "foot pedal"])
    b.add_and("sensor")
    b.add_not("biomedical")
    b.add_ipc("B62M1/00")
    print("Google Patents:", b.build_google_patents())
    print("EPO OPS:", b.build_epo_ops())
    print("USPTO:", b.build_uspto())

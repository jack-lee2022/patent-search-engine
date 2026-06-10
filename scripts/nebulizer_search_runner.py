#!/usr/bin/env python3
"""
One-shot aggregator: run multiple nebulizer queries via Tor,
deduplicate, rank, and export a markdown report.
"""

import json
import sys
import os
from datetime import date
from collections import defaultdict
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(__file__))

from google_patents_collector import GooglePatentsCollector

# ── Query plan ────────────────────────────────────────────────────────────────
QUERIES = [
    ("nebulizer aerosol inhalation",                          "全類型 / 基礎"),
    ("vibrating mesh nebulizer aperture plate",               "振動網孔 / VMN"),
    ("ultrasonic nebulizer piezoelectric atomization",        "超音波 / 壓電"),
    ("jet nebulizer breath-actuated compressor pneumatic",    "噴射式"),
    ("smart nebulizer IoT compliance monitoring sensor",      "智慧型 / 監控"),
    ("nebulizer pulmonary drug delivery COPD asthma",         "藥物遞送應用"),
]

MAX_PER_QUERY  = 50
FINAL_LIMIT    = 50
USE_TOR        = True


def run_all_queries() -> List[Dict[str, Any]]:
    collector = GooglePatentsCollector(tor_enabled=USE_TOR)
    seen: set = set()
    all_items: List[Dict[str, Any]] = []

    for query, label in QUERIES:
        print(f"\n[SEARCH] {label} → \"{query}\"")
        items = collector.fetch_by_keywords(query, max_results=MAX_PER_QUERY)
        new = 0
        for item in items:
            p = item.get("patent", {})
            pn = p.get("publication_number", "")
            if pn and pn not in seen:
                seen.add(pn)
                item["_source_query"]  = query
                item["_source_label"]  = label
                all_items.append(item)
                new += 1
        print(f"  → {new} new (total unique so far: {len(all_items)})")

    return all_items


def classify(item: Dict) -> str:
    """Assign a technology group based on patent metadata."""
    p   = item.get("patent", {})
    t   = (p.get("title", "") + " " + item.get("_source_label", "")).lower()
    ql  = item.get("_source_label", "").lower()

    if "振動網孔" in ql or "vmn" in t or "vibrat" in t or "mesh" in t or "aperture" in t:
        return "振動網孔式 (VMN)"
    if "超音波" in ql or "ultrasonic" in t or "piezoelectric" in t or "piezo" in t:
        return "超音波式"
    if "噴射" in ql or "jet" in t or "pneumatic" in t or "compressor" in t or "venturi" in t:
        return "噴射式"
    if "智慧" in ql or "smart" in t or "iot" in t or "monitor" in t or "sensor" in t or "compliance" in t:
        return "智慧型 / 監控"
    if "drug" in t or "delivery" in t or "pulmonary" in t or "copd" in t or "asthma" in t:
        return "藥物遞送應用"
    return "基礎 / 通用"


def score(item: Dict) -> float:
    """Score for ranking: prefer US, prefer later dates, prefer known assignees."""
    p = item.get("patent", {})
    s = 0.0
    pn = p.get("publication_number", "")
    if pn.startswith("US"):
        s += 30
    elif pn.startswith("EP"):
        s += 20
    elif pn.startswith("WO"):
        s += 15

    # Publication year
    pub = p.get("publication_date", "") or p.get("filing_date", "")
    if len(pub) >= 4:
        try:
            year = int(pub[:4])
            s += max(0, (year - 1990) * 1.5)
        except ValueError:
            pass

    # Family size proxy (bigger family → more important)
    fam = p.get("patent_family_size", 0) or 0
    s += min(fam, 20)

    # Assignee known player bonus
    known = ["aerogen", "pari", "philips", "omron", "trudell", "misco", "aerz"]
    asgn = p.get("assignee", "").lower()
    if any(k in asgn for k in known):
        s += 10

    return s


def select_top(all_items: List[Dict], limit: int = FINAL_LIMIT) -> List[Dict]:
    """
    Stratified selection: score within each group, pick proportionally,
    ensure no group has fewer than 2 entries unless pool is too small.
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for item in all_items:
        item["_group"] = classify(item)
        groups[item["_group"]].append(item)

    # Sort each group by score
    for g in groups:
        groups[g].sort(key=score, reverse=True)

    GROUP_ORDER = [
        "振動網孔式 (VMN)",
        "超音波式",
        "噴射式",
        "智慧型 / 監控",
        "藥物遞送應用",
        "基礎 / 通用",
    ]
    total_pool = sum(len(v) for v in groups.values())
    selected: List[Dict] = []
    per_group = max(2, limit // len(groups))

    for g in GROUP_ORDER:
        pool = groups.get(g, [])
        take = min(per_group, len(pool))
        selected.extend(pool[:take])

    # Fill remaining slots with highest-scored un-selected
    selected_pns = {item["patent"]["publication_number"] for item in selected}
    remaining = [i for i in all_items if i["patent"]["publication_number"] not in selected_pns]
    remaining.sort(key=score, reverse=True)
    for item in remaining:
        if len(selected) >= limit:
            break
        selected.append(item)

    # Final sort by group then score
    selected.sort(key=lambda x: (GROUP_ORDER.index(x.get("_group", "基礎 / 通用")
                                  if x.get("_group") in GROUP_ORDER else 5), -score(x)))
    return selected[:limit]


def to_markdown(selected: List[Dict]) -> str:
    today = date.today().strftime("%Y-%m-%d")
    total_q = len(QUERIES)

    lines = [
        f"# 霧化器 (Nebulizer) 專利檢索報告（第二次）",
        f"",
        f"**檢索日期：** {today}  ",
        f"**檢索工具：** patent-search-engine + Google Patents XHR API  ",
        f"**代理方式：** Tor（exit IP 已驗證）  ",
        f"**查詢數量：** {total_q} 輪  ",
        f"**最終篩選：** {len(selected)} 件（去重後）  ",
        f"",
        f"---",
        f"",
        f"## 檢索策略",
        f"",
        f"| 輪次 | 查詢關鍵字 | 技術分類 |",
        f"|------|------------|----------|",
    ]
    for i, (q, label) in enumerate(QUERIES, 1):
        lines.append(f"| {i} | `{q}` | {label} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## 專利清單",
        f"",
    ]

    current_group = ""
    counter = 0
    for item in selected:
        p     = item.get("patent", {})
        group = item.get("_group", "其他")
        pn    = p.get("publication_number", "")
        title = p.get("title", "（無標題）")
        asgn  = p.get("assignee", "Unknown")
        pub   = p.get("publication_date", "") or p.get("filing_date", "")
        year  = pub[:4] if len(pub) >= 4 else "—"
        legal = p.get("legal_status", "") or ""
        status = "有效" if "Active" in legal else ("已過期" if "Not" in legal else "—")
        country = pn[:2] if len(pn) >= 2 else "—"

        if group != current_group:
            current_group = group
            lines.append(f"### {group}")
            lines.append(f"")
            lines.append(f"| # | 專利號 | 標題 | 申請人 | 公告年 | 法律狀態 |")
            lines.append(f"|---|--------|------|--------|--------|----------|")

        counter += 1
        title_s = title[:55] + "..." if len(title) > 55 else title
        lines.append(f"| {counter} | {pn} | {title_s} | {asgn[:30]} | {year} | {status} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## 統計摘要",
        f"",
    ]

    # Group counts
    group_counts: Dict[str, int] = defaultdict(int)
    country_counts: Dict[str, int] = defaultdict(int)
    for item in selected:
        group_counts[item.get("_group", "其他")] += 1
        pn = item.get("patent", {}).get("publication_number", "")
        country_counts[pn[:2]] += 1

    lines.append(f"### 技術分類分布")
    lines.append(f"")
    lines.append(f"| 技術分類 | 件數 |")
    lines.append(f"|----------|------|")
    for g in ["振動網孔式 (VMN)", "超音波式", "噴射式", "智慧型 / 監控", "藥物遞送應用", "基礎 / 通用"]:
        c = group_counts.get(g, 0)
        if c:
            lines.append(f"| {g} | {c} |")

    lines.append(f"")
    lines.append(f"### 國家/地區分布")
    lines.append(f"")
    lines.append(f"| 國家/地區 | 件數 |")
    lines.append(f"|-----------|------|")
    for country, cnt in sorted(country_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {country} | {cnt} |")

    lines += [
        f"",
        f"---",
        f"",
        f"*本報告由 Claude Code + patent-search-engine (Tor proxy) 自動生成*",
        f"",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Nebulizer Patent Search (Round 2, Tor enabled) ===\n")

    all_items = run_all_queries()
    print(f"\n[RESULT] Total unique patents collected: {len(all_items)}")

    selected = select_top(all_items, limit=FINAL_LIMIT)
    print(f"[RESULT] Selected for report: {len(selected)}")

    md = to_markdown(selected)
    out_path = r"D:\patent\Nebulizer_Patent_Search_Report_Round2.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n[OUTPUT] Report saved to: {out_path}")

    # Print group breakdown
    from collections import Counter
    groups = Counter(item.get("_group", "?") for item in selected)
    print("\nGroup breakdown:")
    for g, c in groups.most_common():
        print(f"  {g}: {c}")

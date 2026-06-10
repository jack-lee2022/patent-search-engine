#!/usr/bin/env python3
"""
patent_search_runner.py — Universal patent search runner for pro-patent-search skill.

Runs multi-round Google Patents searches for any technology topic, then:
  1. Deduplicates across rounds
  2. Scores and applies stratified selection
  3. Writes two output files:
       <outdir>/<slug>_Search_Process_Report.md   ← full audit trail
       <outdir>/<slug>_Patent_List.md             ← clean final list (50 patents)

Usage:
    python scripts/patent_search_runner.py --topic "nebulizer" --outdir "D:\\patent\\run1"
    python scripts/patent_search_runner.py --topic "blood pressure monitor" --max 60 --outdir "D:\\patent\\bp"
    python scripts/patent_search_runner.py --topic "nebulizer" --queries queries.json --outdir "D:\\patent\\run2"

Query override format (queries.json):
    [
      {"query": "nebulizer aerosol inhalation", "label": "全類型"},
      {"query": "vibrating mesh nebulizer",    "label": "VMN"}
    ]
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

sys.path.insert(0, os.path.dirname(__file__))

# ── Imports (graceful fallback if synonym_expander unavailable) ────────────────
try:
    from synonym_expander import SynonymExpander
    _HAS_EXPANDER = True
except ImportError:
    _HAS_EXPANDER = False

from google_patents_collector import GooglePatentsCollector

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_PER_QUERY   = 50
DEFAULT_FINAL   = 50
MAX_ROUNDS      = 8

GROUP_ORDER = [
    "振動網孔式 (VMN)",
    "超音波式",
    "噴射式",
    "智慧型 / 監控",
    "藥物遞送應用",
    "基礎 / 通用",
    "其他",
]

# IPC/CPC hint map: topic keyword → code prefix
IPC_HINTS = {
    "nebulizer":         "A61M11",
    "inhaler":           "A61M15",
    "blood pressure":    "A61B5/02",
    "glucose":           "A61B5/145",
    "ventilator":        "A61M16",
    "endoscope":         "A61B1",
    "catheter":          "A61M25",
}


# ── Query builder ─────────────────────────────────────────────────────────────

def _slug(topic: str) -> str:
    return re.sub(r"[^a-zA-Z0-9一-鿿]+", "_", topic).strip("_")


def build_queries(topic: str) -> List[Tuple[str, str]]:
    """
    Auto-generate up to 6 search queries from the topic using SynonymExpander.
    Returns list of (query_string, label).
    """
    queries: List[Tuple[str, str]] = []

    if not _HAS_EXPANDER:
        queries.append((topic, "基礎"))
        return queries

    expander = SynonymExpander(use_llm=False)

    # Round 1: base topic + top synonyms
    syns = expander.expand([topic]).get(topic, [])
    base_terms = [topic] + syns[:3]
    queries.append((" ".join(base_terms[:3]), "全類型 / 基礎"))

    # Rounds 2-5: one query per major hyponym
    hyponyms = expander.HYPONYMS.get(topic.lower(), [])
    for hypo in hyponyms[:4]:
        label = hypo
        queries.append((f"{topic} {hypo}", label))

    # Round 6: application / clinical context
    app_terms = []
    for kw in ["drug delivery", "pulmonary", "inhalation", "monitoring", "smart", "IoT"]:
        exp = expander.expand([kw]).get(kw, [])
        if exp:
            app_terms.append(exp[0])
    if app_terms:
        app_query = f"{topic} " + " ".join(app_terms[:3])
        queries.append((app_query, "應用 / 智慧型"))

    # Trim to MAX_ROUNDS and ensure uniqueness
    seen_q: set = set()
    unique: List[Tuple[str, str]] = []
    for q, lbl in queries:
        if q not in seen_q:
            seen_q.add(q)
            unique.append((q, lbl))

    return unique[:MAX_ROUNDS]


def load_queries(path: str) -> List[Tuple[str, str]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [(item["query"], item.get("label", item["query"])) for item in data]


# ── Classification ─────────────────────────────────────────────────────────────

def classify(item: Dict, topic: str) -> str:
    p   = item.get("patent", {})
    t   = (p.get("title", "") + " " + item.get("_source_label", "")).lower()
    ql  = item.get("_source_label", "").lower()

    if any(k in t for k in ["vibrat", "mesh", "aperture", "vmn"]):
        return "振動網孔式 (VMN)"
    if any(k in t for k in ["ultrasonic", "piezoelectric", "piezo", "acoustic"]):
        return "超音波式"
    if any(k in t for k in ["jet", "pneumatic", "compressor", "venturi", "breath-actuat"]):
        return "噴射式"
    if any(k in t for k in ["smart", "iot", "monitor", "sensor", "compliance", "connect", "wireless"]):
        return "智慧型 / 監控"
    if any(k in t for k in ["drug", "delivery", "pulmonary", "copd", "asthma", "pharma"]):
        return "藥物遞送應用"

    topic_l = topic.lower()
    if topic_l in t:
        return "基礎 / 通用"
    return "其他"


# ── Scoring ────────────────────────────────────────────────────────────────────

KNOWN_ASSIGNEES = [
    "aerogen", "pari", "philips", "omron", "trudell", "stamford devices",
    "pneuma respiratory", "inspirx", "novartis", "janssen", "boehringer",
    "misco", "aerz", "nektar", "vectura",
]


def score(item: Dict) -> float:
    p   = item.get("patent", {})
    s   = 0.0
    pn  = p.get("publication_number", "")

    # Country weight
    if pn.startswith("US"):   s += 30
    elif pn.startswith("EP"): s += 20
    elif pn.startswith("WO"): s += 15
    elif pn.startswith("JP"): s += 8
    elif pn.startswith("KR"): s += 6

    # Recency
    pub = p.get("publication_date", "") or p.get("filing_date", "")
    if len(pub) >= 4:
        try:
            s += max(0, (int(pub[:4]) - 1990) * 1.5)
        except ValueError:
            pass

    # Family size
    s += min(p.get("patent_family_size", 0) or 0, 20)

    # Known assignee
    asgn = p.get("assignee", "").lower()
    if any(k in asgn for k in KNOWN_ASSIGNEES):
        s += 10

    return s


# ── Selection ──────────────────────────────────────────────────────────────────

def select_top(all_items: List[Dict], topic: str, limit: int = DEFAULT_FINAL) -> List[Dict]:
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for item in all_items:
        item["_group"] = classify(item, topic)
        groups[item["_group"]].append(item)
    for g in groups:
        groups[g].sort(key=score, reverse=True)

    active_groups = [g for g in GROUP_ORDER if g in groups]
    per_group = max(2, limit // max(len(active_groups), 1))

    selected: List[Dict] = []
    for g in active_groups:
        selected.extend(groups[g][:per_group])

    selected_pns = {i["patent"]["publication_number"] for i in selected}
    remaining = sorted(
        [i for i in all_items if i["patent"]["publication_number"] not in selected_pns],
        key=score, reverse=True,
    )
    for item in remaining:
        if len(selected) >= limit:
            break
        selected.append(item)

    selected.sort(key=lambda x: (
        GROUP_ORDER.index(x["_group"]) if x["_group"] in GROUP_ORDER else len(GROUP_ORDER),
        -score(x),
    ))
    return selected[:limit]


# ── Main search runner ─────────────────────────────────────────────────────────

def run(
    topic: str,
    queries: List[Tuple[str, str]],
    max_per_query: int = MAX_PER_QUERY,
    final_limit: int   = DEFAULT_FINAL,
    use_tor: bool      = True,
) -> Dict:
    """Execute all queries and return full audit data."""
    collector = GooglePatentsCollector(tor_enabled=use_tor)
    seen: set = set()
    all_items: List[Dict] = []
    per_query_stats: List[Dict] = []

    for query, label in queries:
        print(f"\n[SEARCH] {label}  →  \"{query}\"")
        items = collector.fetch_by_keywords(query, max_results=max_per_query)
        raw_count = len(items)

        new_items, duplicates = [], 0
        for item in items:
            pn = item.get("patent", {}).get("publication_number", "")
            if pn and pn not in seen:
                seen.add(pn)
                item["_source_query"] = query
                item["_source_label"] = label
                all_items.append(item)
                new_items.append(item)
            else:
                duplicates += 1

        cumulative = len(all_items)
        print(f"  原始: {raw_count}  新增: {len(new_items)}  重複: {duplicates}  累計: {cumulative}")

        country_cnt: Dict[str, int] = defaultdict(int)
        for item in items:
            pn = item.get("patent", {}).get("publication_number", "")
            country_cnt[pn[:2]] += 1

        per_query_stats.append({
            "query":      query,
            "label":      label,
            "raw":        raw_count,
            "new":        len(new_items),
            "duplicates": duplicates,
            "cumulative": cumulative,
            "countries":  dict(sorted(country_cnt.items(), key=lambda x: -x[1])),
            "sample":     [
                {
                    "pn":       i.get("patent", {}).get("publication_number", ""),
                    "title":    i.get("patent", {}).get("title", ""),
                    "assignee": i.get("patent", {}).get("assignee", ""),
                    "year":     (i.get("patent", {}).get("publication_date", "") or "")[:4],
                }
                for i in new_items[:5]
            ],
        })

    selected = select_top(all_items, topic, limit=final_limit)

    # Elimination breakdown
    selected_pns = {i["patent"]["publication_number"] for i in selected}
    elim_by_group: Dict[str, int] = defaultdict(int)
    for item in all_items:
        if item["patent"]["publication_number"] not in selected_pns:
            elim_by_group[item.get("_group", "其他")] += 1

    return {
        "date":            date.today().isoformat(),
        "topic":           topic,
        "use_tor":         use_tor,
        "total_raw":       len(all_items),
        "total_selected":  len(selected),
        "total_eliminated": len(all_items) - len(selected),
        "queries":         queries,
        "per_query":       per_query_stats,
        "selected":        selected,
        "elim_by_group":   dict(elim_by_group),
    }


# ── Markdown generators ────────────────────────────────────────────────────────

def render_process_report(data: Dict) -> str:
    """Detailed process report with per-query audit trail."""
    today      = data["date"]
    topic      = data["topic"]
    pq         = data["per_query"]
    selected   = data["selected"]
    total_raw  = data["total_raw"]
    total_sel  = data["total_selected"]
    total_elim = data["total_eliminated"]
    total_300  = sum(q["raw"] for q in pq)
    dup_removed = total_300 - total_raw
    proxy_str  = "Tor SOCKS5" if data["use_tor"] else "直連（無代理）"

    lines = [
        f"# {topic} 專利檢索過程報告",
        "",
        f"**檢索日期：** {today}  ",
        f"**主題：** {topic}  ",
        f"**代理方式：** {proxy_str}  ",
        f"**工具：** patent-search-engine / google_patents_collector.py  ",
        "",
        "---",
        "",
        "## 一、流程概覽",
        "",
        "```",
        f"  查詢輪數：{len(pq)} 輪",
        f"  各輪回傳：{' + '.join(str(q['raw']) for q in pq)} = {total_300} 筆（含跨輪重複）",
        f"  去重排除：{dup_removed} 筆",
        f"  去重後：  {total_raw} 件唯一專利",
        f"  篩選後：  {total_sel} 件（最終入選）",
        f"  淘汰：    {total_elim} 件",
        "```",
        "",
        "---",
        "",
        "## 二、關鍵詞設計",
        "",
        f"以「技術維度」為軸設計 {len(pq)} 輪查詢，確保涵蓋所有主要技術分支：",
        "",
        "| 輪次 | 查詢關鍵字 | 技術面向 |",
        "|------|-----------|---------|",
    ]
    for i, q in enumerate(pq, 1):
        kws = q["query"].replace(" ", " + ")
        lines.append(f"| {i} | `{kws}` | {q['label']} |")

    if _HAS_EXPANDER:
        expander = SynonymExpander(use_llm=False)
        expanded = expander.expand([topic])
        lines += [
            "",
            f"**關鍵詞擴展來源：** `synonym_expander.py`（靜態資料庫 + Anthropic Claude 後備）  ",
        ]
        syns = expanded.get(topic, [])[:8]
        if syns:
            lines.append(f"- `{topic}` → " + ", ".join(syns))

    lines += [
        "",
        "---",
        "",
        "## 三、逐輪搜尋結果",
        "",
    ]

    for i, q in enumerate(pq, 1):
        lines += [
            f"### 第 {i} 輪：{q['label']}",
            "",
            f"**查詢字串：** `{q['query']}`  ",
            f"**原始回傳：** {q['raw']} 件  ",
            f"**新增（去重後）：** {q['new']} 件  ",
            f"**跨輪重複：** {q['duplicates']} 件  ",
            f"**累計唯一：** {q['cumulative']} 件  ",
            "",
            "**國家 / 地區分布（本輪）：**  ",
        ]
        for country, cnt in list(q["countries"].items())[:8]:
            bar = "█" * min(cnt, 20)
            lines.append(f"- {country}: {bar} {cnt}")

        lines += [
            "",
            "**本輪新增代表性專利（前 5 件）：**  ",
            "",
            "| 專利號 | 標題 | 申請人 | 年份 |",
            "|--------|------|--------|------|",
        ]
        for s in q["sample"]:
            title = (s["title"][:50] + "...") if len(s["title"]) > 50 else s["title"]
            asgn  = (s["assignee"][:28] + "..") if len(s["assignee"]) > 28 else s["assignee"]
            lines.append(f"| {s['pn']} | {title} | {asgn} | {s['year']} |")
        lines.append("")

    lines += [
        "---",
        "",
        "## 四、篩選規則",
        "",
        "### 4.1 去重",
        "",
        f"以 `publication_number` 為唯一鍵，跨 {len(pq)} 輪查詢去重。",
        f"- 合計原始回傳：{total_300} 筆",
        f"- 跨輪重複排除：{dup_removed} 筆",
        f"- 去重後唯一專利：**{total_raw} 件**",
        "",
        "### 4.2 評分排序",
        "",
        "| 評分維度 | 規則 | 最高加分 |",
        "|----------|------|---------|",
        "| 國家權重 | US +30 / EP +20 / WO +15 / JP +8 / KR +6 | 30 |",
        "| 公告年份 | (年份 − 1990) × 1.5 | ~54（2026 年）|",
        "| 專利家族大小 | min(family_size, 20) | 20 |",
        "| 核心申請人加分 | 已知關鍵廠商 +10 | 10 |",
        "",
        "### 4.3 分層抽樣",
        "",
        "| 步驟 | 說明 |",
        "|------|------|",
        f"| ① 技術分組 | 依標題關鍵字將 {total_raw} 件分入最多 7 個技術組 |",
        "| ② 組內排序 | 每組依評分由高到低排列 |",
        f"| ③ 每組取 Top-N | 每組最多取 {max(2, total_sel // 6)} 件 |",
        "| ④ 餘額補足 | 剩餘名額從全局高分未選中者補入，湊滿目標件數 |",
        "",
        "### 4.4 淘汰分析",
        "",
        f"共淘汰 **{total_elim} 件**：",
        "",
        "| 技術分類 | 淘汰件數 |",
        "|----------|---------|",
    ]
    for g in GROUP_ORDER:
        cnt = data["elim_by_group"].get(g, 0)
        if cnt:
            lines.append(f"| {g} | {cnt} |")

    lines += [
        "",
        "---",
        "",
        f"## 五、最終入選專利（{total_sel} 件）",
        "",
    ]
    current_group = ""
    counter = 0
    for item in selected:
        p      = item.get("patent", {})
        group  = item.get("_group", "其他")
        pn     = p.get("publication_number", "")
        title  = p.get("title", "（無標題）")
        asgn   = p.get("assignee", "Unknown")
        pub    = p.get("publication_date", "") or p.get("filing_date", "")
        year   = pub[:4] if len(pub) >= 4 else "—"
        sc     = round(score(item), 1)
        src_q  = item.get("_source_query", "")

        if group != current_group:
            current_group = group
            lines += [
                f"### {group}",
                "",
                "| # | 專利號 | 標題 | 申請人 | 年 | 評分 | 來源查詢 |",
                "|---|--------|------|--------|----|------|----------|",
            ]
        counter += 1
        title_s = (title[:48] + "...") if len(title) > 48 else title
        asgn_s  = (asgn[:25] + "..") if len(asgn) > 25 else asgn
        src_s   = (src_q[:38] + "...") if len(src_q) > 38 else src_q
        lines.append(f"| {counter} | {pn} | {title_s} | {asgn_s} | {year} | {sc} | `{src_s}` |")

    lines += [
        "",
        "---",
        "",
        "## 六、統計摘要",
        "",
        "### 技術分類分布",
        "",
        "| 技術分類 | 入選 | 原始池 | 入選率 |",
        "|----------|------|--------|--------|",
    ]
    pool_by_group: Dict[str, int] = defaultdict(int)
    sel_by_group:  Dict[str, int] = defaultdict(int)
    for item in selected:
        sel_by_group[item.get("_group", "其他")] += 1
    for g, cnt in data["elim_by_group"].items():
        pool_by_group[g] += cnt
    for item in selected:
        pool_by_group[item.get("_group", "其他")] += 1

    for g in GROUP_ORDER:
        sc = sel_by_group.get(g, 0)
        pc = pool_by_group.get(g, 0)
        if pc:
            lines.append(f"| {g} | {sc} | {pc} | {sc/pc*100:.0f}% |")

    lines += [
        "",
        "### 國家分布",
        "",
        "| 國家 | 件數 | 比例 |",
        "|------|------|------|",
    ]
    country_final: Dict[str, int] = defaultdict(int)
    for item in selected:
        pn = item.get("patent", {}).get("publication_number", "")
        country_final[pn[:2]] += 1
    for c, cnt in sorted(country_final.items(), key=lambda x: -x[1]):
        lines.append(f"| {c} | {cnt} | {cnt/total_sel*100:.0f}% |")

    lines += [
        "",
        "### 年份分布",
        "",
        "| 年份區間 | 件數 |",
        "|----------|------|",
    ]
    year_bins: Dict[str, int] = defaultdict(int)
    for item in selected:
        p   = item.get("patent", {})
        pub = p.get("publication_date", "") or p.get("filing_date", "")
        y   = int(pub[:4]) if len(pub) >= 4 else 0
        if   y >= 2023: year_bins["2023–2026"] += 1
        elif y >= 2020: year_bins["2020–2022"] += 1
        elif y >= 2015: year_bins["2015–2019"] += 1
        elif y >= 2010: year_bins["2010–2014"] += 1
        elif y >  0:    year_bins["< 2010"]    += 1
        else:           year_bins["年份不明"]   += 1
    for band in ["2023–2026", "2020–2022", "2015–2019", "2010–2014", "< 2010", "年份不明"]:
        cnt = year_bins.get(band, 0)
        if cnt:
            lines.append(f"| {band} | {cnt} |")

    lines += [
        "",
        "---",
        "",
        f"*本文件由 Claude Code + patent_search_runner.py 自動生成*  ",
        f"*生成時間：{today}*  ",
    ]
    return "\n".join(lines)


def render_patent_list(data: Dict) -> str:
    """Clean final patent list (no audit detail)."""
    today    = data["date"]
    topic    = data["topic"]
    selected = data["selected"]

    lines = [
        f"# {topic} 專利檢索報告",
        "",
        f"**檢索日期：** {today}  ",
        f"**最終件數：** {len(selected)} 件  ",
        "",
        "---",
        "",
        "## 專利清單",
        "",
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

        if group != current_group:
            current_group = group
            lines += [
                f"### {group}",
                "",
                "| # | 專利號 | 標題 | 申請人 | 年份 | 狀態 |",
                "|---|--------|------|--------|------|------|",
            ]
        counter += 1
        title_s = (title[:55] + "...") if len(title) > 55 else title
        asgn_s  = (asgn[:30] + "..") if len(asgn) > 30 else asgn
        lines.append(f"| {counter} | {pn} | {title_s} | {asgn_s} | {year} | {status} |")

    lines += [
        "",
        "---",
        "",
        f"*由 patent_search_runner.py 生成，詳細過程請見 Process Report*",
    ]
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Universal patent search runner (pro-patent-search skill)"
    )
    parser.add_argument("--topic",   required=True,  help="Technology topic, e.g. 'nebulizer'")
    parser.add_argument("--outdir",  required=True,  help="Output directory for reports")
    parser.add_argument("--max",     type=int, default=MAX_PER_QUERY,
                        help=f"Max results per query (default {MAX_PER_QUERY})")
    parser.add_argument("--final",   type=int, default=DEFAULT_FINAL,
                        help=f"Final selection limit (default {DEFAULT_FINAL})")
    parser.add_argument("--queries", help="Path to JSON query override file")
    parser.add_argument("--no-tor",  action="store_true", help="Disable Tor proxy")
    args = parser.parse_args()

    # Build or load queries
    if args.queries:
        queries = load_queries(args.queries)
        print(f"[RUNNER] Loaded {len(queries)} queries from {args.queries}")
    else:
        queries = build_queries(args.topic)
        print(f"[RUNNER] Auto-generated {len(queries)} queries for topic: {args.topic}")

    for i, (q, lbl) in enumerate(queries, 1):
        print(f"  {i}. [{lbl}] {q}")

    # Run
    use_tor = not args.no_tor
    data = run(
        topic=args.topic,
        queries=queries,
        max_per_query=args.max,
        final_limit=args.final,
        use_tor=use_tor,
    )

    # Write outputs
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    slug = _slug(args.topic)

    process_path = outdir / f"{slug}_Search_Process_Report.md"
    list_path    = outdir / f"{slug}_Patent_List.md"

    process_path.write_text(render_process_report(data), encoding="utf-8")
    list_path.write_text(render_patent_list(data), encoding="utf-8")

    print(f"\n[DONE]")
    print(f"  Process report : {process_path}")
    print(f"  Patent list    : {list_path}")
    print(f"  Total unique   : {data['total_raw']}")
    print(f"  Selected       : {data['total_selected']}")
    print(f"  Eliminated     : {data['total_eliminated']}")


if __name__ == "__main__":
    main()

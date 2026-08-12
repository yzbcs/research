#!/usr/bin/env python3
"""Validate atlas data, counts, dates, bridge references, and visible metadata."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "arxiv_idea_atlas.html"


def main() -> int:
    html = HTML_PATH.read_text(encoding="utf-8")
    errors: list[str] = []
    match = re.search(
        r'<script type="application/json" id="arxivIdeaAtlasData">(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        print("FAIL: missing arxivIdeaAtlasData")
        return 1
    data = json.loads(match.group(1))
    meta = data["meta"]
    papers = data["papers"]
    categories = data["categories"]
    bridges = data["bridges"]
    paper_ids = [paper["id"] for paper in papers]
    category_ids = {category["id"] for category in categories}

    if len(paper_ids) != len(set(paper_ids)):
        errors.append("paper ids are not unique")
    if meta["papers"] != len(papers):
        errors.append(f"meta papers {meta['papers']} != records {len(papers)}")
    if meta["categories"] != len(categories) or len(categories) != 17:
        errors.append("category total is not 17")
    if sum(category["count"] for category in categories) != len(papers):
        errors.append("category counts do not sum to paper total")

    actual_counts = Counter(paper["category"] for paper in papers)
    actual_recent = Counter(
        paper["category"] for paper in papers if paper["date"] >= meta["recent_cutoff"]
    )
    for category in categories:
        cid = category["id"]
        if category["count"] != actual_counts[cid]:
            errors.append(f"category {cid} count mismatch")
        if category["recent"] != actual_recent[cid]:
            errors.append(f"category {cid} recent mismatch")
        if not category.get("summary") or not category.get("frame"):
            errors.append(f"category {cid} missing summary or research frame")

    for paper in papers:
        if paper["category"] not in category_ids:
            errors.append(f"paper {paper['id']} has unknown category")
        if paper["url"] != f"https://arxiv.org/abs/{paper['id']}":
            errors.append(f"paper {paper['id']} has noncanonical abstract URL")
        try:
            date.fromisoformat(paper["date"])
        except ValueError:
            errors.append(f"paper {paper['id']} has invalid date")

    expected_cutoff = (
        date.fromisoformat(meta["paper_to"]) - timedelta(days=6)
    ).isoformat()
    if meta["recent_cutoff"] != expected_cutoff:
        errors.append("recent cutoff is not the final seven paper dates")
    if max(paper["date"] for paper in papers) != meta["paper_to"]:
        errors.append("paper_to does not match latest paper date")
    if "LLM 解析失败，请检查 API 响应" in html:
        errors.append("archive parser-error sentinel leaked into atlas")

    by_id = {paper["id"]: paper for paper in papers}
    for index, bridge in enumerate(bridges):
        refs = bridge.get("papers", [])
        missing = [paper_id for paper_id in refs if paper_id not in by_id]
        if missing:
            errors.append(f"bridge {index} missing paper refs: {missing}")
            continue
        represented = {by_id[paper_id]["category"] for paper_id in refs}
        if not set(bridge["cats"]).issubset(represented):
            errors.append(f"bridge {index} lacks evidence from both categories")

    index_match = re.match(r"<!-- index:.*?-->", html, re.S)
    if not index_match or str(meta["papers"]) not in index_match.group(0):
        errors.append("index metadata does not contain current paper total")
    if meta["as_of"] not in html:
        errors.append("snapshot date missing from visible page payload")

    print(f"page: {HTML_PATH.name} ({HTML_PATH.stat().st_size} bytes)")
    print(f"papers: {len(papers)}")
    print(f"categories: {len(categories)}")
    print(f"recent: {sum(actual_recent.values())}")
    print(f"bridges: {len(bridges)}")
    print(f"range: {meta['from']} ~ {meta['to']} (papers through {meta['paper_to']})")
    if errors:
        print("FAIL:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("PASS: arxiv_idea_atlas.html data checks ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

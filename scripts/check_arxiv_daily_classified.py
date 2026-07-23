#!/usr/bin/env python3
"""Validate the shipped arxiv_daily_classified.html against acceptance criteria.

Drives the real root HTML page (not a mock): index comment, multiple category
sections, non-empty per-category summaries, paper titles with arXiv abs
links/ids, full-archive date span, and known digest-grounded papers.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "arxiv_daily_classified.html"

# Ground-truth samples from live digests (early + late window)
KNOWN_PAPERS = [
    ("2604.06132", "Claw-Eval"),  # 2026-04-08 first day
    ("2607.18485", "Trusted Credentials, Untrusted Behavior"),
    ("2607.18566", "The Story Shapes the Agent"),
    ("2607.18806", "AI Tour Meeting"),
    ("2607.18754", "AgentDebugX"),
]


def main() -> int:
    if not HTML_PATH.exists():
        print(f"FAIL: missing shipped page {HTML_PATH}")
        return 1

    content = HTML_PATH.read_text(encoding="utf-8")
    errors: list[str] = []

    if not re.search(r"<!--\s*index:\s*[^|]+\|[^|]+\|[^>]*-->", content, re.I):
        errors.append("missing <!-- index: title | date | description --> comment")

    cat_headers = re.findall(
        r'<section class="category"[^>]*>\s*<header class="cat-header">\s*<h2>([^<]+)</h2>',
        content,
    )
    if len(cat_headers) < 2:
        errors.append(f"expected >=2 category sections, found {len(cat_headers)}")

    summaries = re.findall(r'class="cat-summary".*?<p>(.*?)</p>', content, re.S)
    if len(summaries) != len(cat_headers):
        errors.append(
            f"summary count {len(summaries)} != category count {len(cat_headers)}"
        )
    for i, s in enumerate(summaries):
        text = re.sub(r"\s+", " ", s).strip()
        if len(text) < 20:
            errors.append(f"category[{i}] summary too short or empty: {text!r}")
        if "TODO" in text:
            errors.append(f"category[{i}] summary contains TODO")

    arxiv_links = re.findall(r"https://arxiv\.org/abs/(\d+\.\d+)", content)
    unique_ids = sorted(set(arxiv_links))
    if len(unique_ids) < 100:
        errors.append(
            f"expected full-archive scale (>=100 unique arXiv ids), found {len(unique_ids)}"
        )

    paper_titles = re.findall(
        r'class="paper-title"[^>]*>\s*<a[^>]*>([^<]+)</a>', content
    )
    if len(paper_titles) < 100:
        errors.append(f"expected >=100 paper titles, found {len(paper_titles)}")

    # Full archive window markers
    if "2026-04-08" not in content:
        errors.append("missing early archive date 2026-04-08")
    if "2026-07-22" not in content:
        errors.append("missing latest archive date 2026-07-22")
    if "全量" not in content and "全部" not in content:
        errors.append("page should indicate full-archive scope (全量/全部)")

    if re.search(r"TODO:\s*fill|placeholder", content, re.I):
        errors.append("placeholder body detected")

    for arxiv_id, title_frag in KNOWN_PAPERS:
        if arxiv_id not in content:
            errors.append(f"missing known arXiv id {arxiv_id}")
        if title_frag not in content:
            errors.append(f"missing known title fragment {title_frag!r}")
        if f"https://arxiv.org/abs/{arxiv_id}" not in content:
            errors.append(f"missing abs URL for {arxiv_id}")

    empty_cats = re.findall(r'<span class="badge">0 篇</span>', content)
    if empty_cats:
        errors.append(f"found {len(empty_cats)} empty categories (0 篇)")

    print(f"page: {HTML_PATH.name} ({HTML_PATH.stat().st_size} bytes)")
    print(f"categories: {len(cat_headers)}")
    for h in cat_headers:
        print(f"  - {h}")
    print(f"summaries: {len(summaries)}")
    print(f"paper_titles: {len(paper_titles)}")
    print(f"unique_arxiv_ids: {len(unique_ids)}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("PASS: full-archive arxiv_daily_classified.html checks ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

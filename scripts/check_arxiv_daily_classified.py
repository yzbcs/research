#!/usr/bin/env python3
"""Validate the shipped arxiv_daily_classified.html against acceptance criteria.

This is a structural + content check on the real root HTML page (not a mock):
index comment, multiple category sections, non-empty per-category summaries,
paper titles with arXiv abs links/ids, and a few known digest-grounded papers.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "arxiv_daily_classified.html"

# Ground-truth samples taken from live yzbcs.github.io/study digests
# (2026-07-22 and nearby window). Used only as presence checks.
KNOWN_PAPERS = [
    ("2607.18485", "Trusted Credentials, Untrusted Behavior"),
    ("2607.18566", "The Story Shapes the Agent"),
    ("2607.18806", "AI Tour Meeting"),
    ("2607.18754", "AgentDebugX"),
    ("2607.13602", "Analogical Deep Research"),
]


def main() -> int:
    if not HTML_PATH.exists():
        print(f"FAIL: missing shipped page {HTML_PATH}")
        return 1

    content = HTML_PATH.read_text(encoding="utf-8")
    errors: list[str] = []

    # (a) index comment
    if not re.search(r"<!--\s*index:\s*[^|]+\|[^|]+\|[^>]*-->", content, re.I):
        errors.append("missing <!-- index: title | date | description --> comment")

    # (b) multiple category sections
    cat_headers = re.findall(r'<section class="category"[^>]*>\s*<header class="cat-header">\s*<h2>([^<]+)</h2>', content)
    if len(cat_headers) < 2:
        errors.append(f"expected >=2 category sections, found {len(cat_headers)}")

    # (c) each category has non-empty summary prose
    summaries = re.findall(
        r'class="cat-summary".*?<p>(.*?)</p>',
        content,
        re.S,
    )
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

    # (d) paper entries with titles and arXiv links/ids
    arxiv_links = re.findall(r"https://arxiv\.org/abs/(\d+\.\d+)", content)
    if len(arxiv_links) < 5:
        errors.append(f"expected many arXiv abs links, found {len(arxiv_links)}")
    unique_ids = sorted(set(arxiv_links))
    if len(unique_ids) < 5:
        errors.append(f"expected >=5 unique arXiv ids, found {len(unique_ids)}")

    paper_titles = re.findall(r'class="paper-title"[^>]*>\s*<a[^>]*>([^<]+)</a>', content)
    if len(paper_titles) < 5:
        errors.append(f"expected >=5 paper titles, found {len(paper_titles)}")

    # (e) no placeholder-only body
    if re.search(r"\bTODO\b", content) and "TODO" in content.split("<body", 1)[-1]:
        # allow TODO only if not dominating; flag explicit empty placeholder
        body = content.split("<body", 1)[-1]
        if "TODO: fill" in body or "placeholder" in body.lower():
            errors.append("placeholder body detected")

    # Known digest-grounded papers must appear (title fragment + abs id)
    for arxiv_id, title_frag in KNOWN_PAPERS:
        if arxiv_id not in content:
            errors.append(f"missing known arXiv id {arxiv_id}")
        if title_frag not in content:
            errors.append(f"missing known title fragment {title_frag!r}")
        if f"https://arxiv.org/abs/{arxiv_id}" not in content:
            errors.append(f"missing abs URL for {arxiv_id}")

    # Empty categories with zero papers should not appear if papers were fetched
    empty_cats = re.findall(
        r'<span class="badge">0 篇</span>',
        content,
    )
    if empty_cats:
        errors.append(f"found {len(empty_cats)} empty categories (0 篇)")

    print(f"page: {HTML_PATH.name}")
    print(f"categories: {len(cat_headers)} -> {cat_headers}")
    print(f"summaries: {len(summaries)}")
    print(f"paper_titles: {len(paper_titles)}")
    print(f"unique_arxiv_ids: {len(unique_ids)}")
    print(f"sample_ids: {unique_ids[:5]}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("PASS: arxiv_daily_classified.html satisfies structural acceptance checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

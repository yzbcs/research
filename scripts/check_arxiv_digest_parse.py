#!/usr/bin/env python3
"""Drive the shipped digest parser on cached daily HTML (not a reimplementation).

Exercises ``build_arxiv_daily_classified.parse_daily_html`` / ``classify_paper``
on the real study digest files. New-window witnesses and rest days are
acceptance gates; one older digest is a control that still yields arXiv cards.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_arxiv_daily_classified as classified  # noqa: E402

DAILY_DIR = ROOT / "assets" / "input" / "study_digests" / "daily_html_all"

# Digest date -> local cache filename
DIGESTS = {
    "2026-08-13": DAILY_DIR / "daily_2026_08_2026-08-13.html",
    "2026-08-14": DAILY_DIR / "daily_2026_08_2026-08-14.html",
    "2026-08-15": DAILY_DIR / "daily_2026_08_2026-08-15.html",
    "2026-08-16": DAILY_DIR / "daily_2026_08_2026-08-16.html",
    "2026-04-08": DAILY_DIR / "daily_2026_04_2026-04-08.html",
}

WITNESSES = {
    "2026-08-13": ("2608.11552", "Beyond Single-Turn Confidence"),
    "2026-08-14": ("2608.12476", "Governed Persistent Memory"),
    "2026-04-08": ("2604.06132", "Claw-Eval"),
}

REST_DAYS = ("2026-08-15", "2026-08-16")


def _ids(papers: list[dict]) -> set[str]:
    return {p["arxiv_id"] for p in papers}


def main() -> int:
    errors: list[str] = []

    parsed: dict[str, list[dict]] = {}
    for digest_date, path in DIGESTS.items():
        if not path.exists():
            errors.append(f"missing digest file {path}")
            continue
        papers = classified.parse_daily_html(path, digest_date)
        parsed[digest_date] = papers
        print(f"{digest_date}: {len(papers)} arXiv cards from {path.name}")
        for p in papers:
            if not p.get("arxiv_id") or not p.get("title"):
                errors.append(f"{digest_date}: parsed record missing title/id: {p}")
            if "arxiv.org/abs/" not in (p.get("arxiv_url") or ""):
                errors.append(f"{digest_date}: non-abs url for {p.get('arxiv_id')}")
            if "小红书" in (p.get("title") or "") and "arxiv.org" not in (p.get("arxiv_url") or ""):
                errors.append(f"{digest_date}: 小红书-only card leaked: {p.get('title')}")
            # Parser must skip cards that are not arXiv papers.
            if not p.get("arxiv_id"):
                errors.append(f"{digest_date}: empty arxiv_id")
            cat = classified.classify_paper(p)
            if cat not in classified.CATEGORY_ORDER:
                errors.append(f"{digest_date}: {p['arxiv_id']} classified to unknown {cat!r}")

    for day in REST_DAYS:
        papers = parsed.get(day, None)
        if papers is None:
            continue
        if papers:
            errors.append(
                f"{day} is a rest day but parser returned {len(papers)} cards: "
                f"{[p['arxiv_id'] for p in papers]}"
            )

    for day, (arxiv_id, title_frag) in WITNESSES.items():
        papers = parsed.get(day, [])
        ids = _ids(papers)
        if arxiv_id not in ids:
            errors.append(f"{day}: missing witness {arxiv_id}")
            continue
        hit = next(p for p in papers if p["arxiv_id"] == arxiv_id)
        if title_frag not in hit["title"]:
            errors.append(
                f"{day}: {arxiv_id} title {hit['title']!r} lacks {title_frag!r}"
            )
        if hit["arxiv_url"] != f"https://arxiv.org/abs/{arxiv_id}":
            errors.append(f"{day}: {arxiv_id} abs URL is {hit['arxiv_url']!r}")

    if parsed.get("2026-04-08") is not None and len(parsed["2026-04-08"]) < 1:
        errors.append("control digest 2026-04-08 yielded no arXiv cards")

    file_dates = classified.digest_dates_in_dir(DAILY_DIR)
    if not file_dates:
        errors.append("no digest filenames in cache")
    else:
        archive_to = file_dates[-1]
        classified_html = (ROOT / "arxiv_daily_classified.html").read_text(encoding="utf-8")
        title_rng = re.search(
            r"·\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})\s*</title>",
            classified_html,
        )
        if not title_rng or title_rng.group(2) != archive_to:
            errors.append(
                f"classified title window end {title_rng.group(2) if title_rng else None} "
                f"!= latest digest {archive_to}"
            )
        atlas_html = (ROOT / "arxiv_idea_atlas.html").read_text(encoding="utf-8")
        match = re.search(
            r'<script type="application/json" id="arxivIdeaAtlasData">(.*?)</script>',
            atlas_html,
            re.S,
        )
        if not match:
            errors.append("atlas payload missing")
        else:
            meta = json.loads(match.group(1))["meta"]
            if meta.get("to") != archive_to:
                errors.append(f"atlas meta.to {meta.get('to')!r} != latest digest {archive_to}")
            if meta.get("as_of") != archive_to:
                errors.append(f"atlas as_of {meta.get('as_of')!r} != latest digest {archive_to}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("PASS: shipped parse/classify on cached new + control digests")
    return 0


if __name__ == "__main__":
    sys.exit(main())

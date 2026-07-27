#!/usr/bin/env python3
"""Copy a local HTML page into this repository and regenerate index.html."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_COMMENT_RE = re.compile(r"<!--\s*index:", re.IGNORECASE)


def slugify_filename(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = re.sub(r"[^a-z0-9._-]+", "_", stem).strip("_")
    return f"{stem or 'page'}.html"


def ensure_index_comment(path: Path, title: str, description: str, page_date: str) -> None:
    content = path.read_text(encoding="utf-8", errors="replace")
    if INDEX_COMMENT_RE.search(content):
        return
    comment = f"<!-- index: {title} | {page_date} | {description} -->\n"
    path.write_text(comment + content, encoding="utf-8")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    parser.add_argument("--title", help="Title shown in index.html")
    parser.add_argument("--description", default="", help="Description shown in index.html")
    parser.add_argument("--date", default=date.today().isoformat(), help="Date shown in index.html")
    parser.add_argument("--name", help="Destination filename, for example exp142_demo.html")
    parser.add_argument("--commit", action="store_true", help="Run git add/commit after copying")
    parser.add_argument("--push", action="store_true", help="Run git push after committing")
    args = parser.parse_args()

    src = args.html_file.expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"File not found: {src}")
    if src.suffix.lower() != ".html":
        raise SystemExit("Only .html files are supported.")

    dest_name = args.name or slugify_filename(src.name)
    if not dest_name.endswith(".html"):
        dest_name += ".html"
    dest = ROOT / "pages" / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(src, dest)
    title = args.title or dest.stem.replace("_", " ").replace("-", " ").title()
    ensure_index_comment(dest, title, args.description, args.date)
    run(["python3", "scripts/gen_index.py"])

    rel = dest.relative_to(ROOT).as_posix()
    print(f"Copied: {rel}")
    print("Review the page, then publish with:")
    print(f"  git add {rel} index.html")
    print(f"  git commit -m \"Add {dest.stem}\"")
    print("  git push")

    if args.commit:
        rel = dest.relative_to(ROOT).as_posix()
        run(["git", "add", rel, "index.html"])
        run(["git", "commit", "-m", f"Add {dest.stem}"])
    if args.push:
        run(["git", "push"])


if __name__ == "__main__":
    main()

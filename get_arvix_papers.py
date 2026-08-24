#!/usr/bin/env python3
"""
Download arXiv PDFs listed in a CSV file and bundle them into a zip archive.

Usage:  python get_arvix_papers.py refs.csv [--out-dir DIR] [--zip-name NAME]
Requires: requests  (pip install requests)

The CSV file must have a header row with columns `arxiv_id,title`. Each row's
`title` is slugified into the output PDF's filename (falling back to the
sanitized arXiv ID if the title is blank). By default, PDFs are saved to an
`arxiv_papers/` directory created next to the CSV file.
"""

import argparse
import csv
import re
import time
import zipfile
from pathlib import Path

import requests

OUT_DIR_NAME = "arxiv_papers"
ZIP_NAME = "arxiv_papers.zip"
HEADERS = {"User-Agent": "lit-review-downloader/1.0 (personal research use)"}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return re.sub(r"_+", "_", slug)


def read_refs(csv_path: Path) -> list[tuple[str, str]]:
    refs = []
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            arxiv_id = (row.get("arxiv_id") or "").strip()
            title = (row.get("title") or "").strip()
            if not arxiv_id:
                continue
            name = slugify(title) if title else arxiv_id.replace("/", "_")
            refs.append((name, arxiv_id))
    return refs


def download_pdf(arxiv_id: str, dest: Path) -> bool:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=120)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            dest.write_bytes(r.content)
            return True
    except requests.RequestException:
        pass
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Download arXiv PDFs listed in a CSV file.")
    parser.add_argument("csv_path", type=Path, help="CSV file with arxiv_id,title columns")
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help=f"directory to save PDFs (default: {OUT_DIR_NAME}/ next to the CSV file)",
    )
    parser.add_argument("--zip-name", type=Path, default=ZIP_NAME, help="output zip filename")
    args = parser.parse_args()

    out_dir = args.out_dir or args.csv_path.resolve().parent / OUT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = read_refs(args.csv_path)
    ok, skipped = [], []

    for name, arxiv_id in refs:
        dest = out_dir / f"{name}.pdf"
        if dest.exists():
            print(f"[skip] {name} (already downloaded)")
            ok.append(name)
            continue

        if download_pdf(arxiv_id, dest):
            print(f"[ ok ] {name}  (arXiv:{arxiv_id})")
            ok.append(name)
        else:
            print(f"[miss] {name} — not found on arXiv, skipping")
            skipped.append(name)
        time.sleep(3)

    with zipfile.ZipFile(args.zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for pdf in sorted(out_dir.glob("*.pdf")):
            zf.write(pdf, pdf.name)

    print(f"\nDone: {len(ok)} PDFs zipped into {args.zip_name}; {len(skipped)} skipped.")
    if skipped:
        print("Skipped (likely not on arXiv):")
        for name in skipped:
            print(f"  - {name}")


if __name__ == "__main__":
    main()

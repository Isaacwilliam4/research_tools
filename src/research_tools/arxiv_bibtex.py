"""
Generate BibTeX citations (with abstracts) for a list of arXiv IDs.

Usage:  get-arxiv-bibtex ID1 ID2 ... [-o refs.bib]
        get-arxiv-bibtex ID1,ID2,... [-o refs.bib]

Metadata is fetched from the arXiv API in a single request. Entries are
written to stdout unless --out is given. Papers with a journal reference are
emitted as @article, everything else as @misc. Citation keys follow the
Google Scholar style: <firstauthorlastname><year><firsttitleword>.
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

API_URL = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "lit-review-downloader/1.0 (personal research use)"}
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "to", "and", "with", "towards", "toward"}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def fetch_entries(ids: list[str]) -> list[ET.Element]:
    params = {"id_list": ",".join(ids), "max_results": len(ids)}
    r = requests.get(API_URL, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return ET.fromstring(r.content).findall("atom:entry", NS)


def make_key(authors: list[str], year: str, title: str, used: set[str]) -> str:
    last = authors[0].split()[-1] if authors else "anon"
    last = re.sub(r"[^a-z]", "", last.lower()) or "anon"
    words = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOPWORDS]
    key = f"{last}{year}{words[0] if words else ''}"
    base, suffix = key, ord("a")
    while key in used:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    used.add(key)
    return key


def entry_to_bibtex(entry: ET.Element, used_keys: set[str]) -> tuple[str, str]:
    arxiv_id = strip_version(entry.findtext("atom:id", "", NS).rsplit("/abs/", 1)[-1])
    title = clean(entry.findtext("atom:title", "", NS))
    abstract = clean(entry.findtext("atom:summary", "", NS))
    authors = [clean(a.findtext("atom:name", "", NS)) for a in entry.findall("atom:author", NS)]
    year = entry.findtext("atom:published", "", NS)[:4]
    doi = clean(entry.findtext("arxiv:doi", "", NS))
    journal_ref = clean(entry.findtext("arxiv:journal_ref", "", NS))
    primary = entry.find("arxiv:primary_category", NS)
    category = primary.get("term") if primary is not None else ""

    fields = [
        ("title", f"{{{title}}}"),
        ("author", " and ".join(authors)),
        ("year", year),
    ]
    if journal_ref:
        fields.append(("journal", journal_ref))
    fields += [
        ("eprint", arxiv_id),
        ("archivePrefix", "arXiv"),
        ("primaryClass", category),
        ("url", f"https://arxiv.org/abs/{arxiv_id}"),
    ]
    if doi:
        fields.append(("doi", doi))
    fields.append(("abstract", abstract))

    entry_type = "article" if journal_ref else "misc"
    key = make_key(authors, year, title, used_keys)
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields if value)
    return arxiv_id, f"@{entry_type}{{{key},\n{body}\n}}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate BibTeX (with abstracts) for arXiv IDs.")
    parser.add_argument("ids", nargs="+", help="arXiv IDs, space- or comma-separated")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="write BibTeX to this file instead of stdout")
    args = parser.parse_args()

    ids = [i.strip() for arg in args.ids for i in arg.split(",") if i.strip()]
    try:
        entries = fetch_entries(ids)
    except (requests.RequestException, ET.ParseError) as e:
        sys.exit(f"error: failed to query arXiv API: {e}")

    used_keys: set[str] = set()
    found: dict[str, str] = {}
    for entry in entries:
        # Malformed IDs come back as a single "Error" entry pointing at api/errors
        if "/api/errors" in entry.findtext("atom:id", "", NS):
            sys.exit(f"error: arXiv API rejected the request: "
                     f"{clean(entry.findtext('atom:summary', '', NS))}")
        arxiv_id, bib = entry_to_bibtex(entry, used_keys)
        found[arxiv_id] = bib

    bibs, missing = [], []
    for arxiv_id in ids:
        bib = found.get(strip_version(arxiv_id))
        if bib:
            bibs.append(bib)
        else:
            missing.append(arxiv_id)

    output = "\n\n".join(bibs) + "\n" if bibs else ""
    if args.out:
        args.out.write_text(output)
        print(f"Wrote {len(bibs)} entries to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    if missing:
        print("Not found on arXiv:", file=sys.stderr)
        for arxiv_id in missing:
            print(f"  - {arxiv_id}", file=sys.stderr)


if __name__ == "__main__":
    main()

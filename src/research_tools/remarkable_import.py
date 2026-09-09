"""
Reconstruct a browsable folder tree from a reMarkable "xochitl" data export.

Usage:  import-remarkable /path/to/xochitl DEST_DIR

Each item in a xochitl export is a UUID with a companion `<uuid>.metadata`
JSON file holding its display name (visibleName), type (DocumentType or
CollectionType, i.e. document or folder), and parent (another item's UUID,
"" for root, or the literal "trash"). This walks that graph and copies or
renders each document into DEST_DIR under a snake_case mirror of its
original folder structure. Trashed items are placed under a top-level
Trash/ directory instead of being dropped.

Documents whose reMarkable fileType is pdf or epub are copied as-is.
Handwritten notebooks (fileType == notebook, no native PDF) are rendered
page-by-page from their .rm stroke data and merged into a single PDF; pages
with no strokes are omitted, and a notebook is skipped (with a warning) if
none of its pages render.
"""

import argparse
import io
import json
import multiprocessing as mp
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfWriter
from reportlab.graphics import renderPDF
from rmc.exporters.svg import tree_to_svg
from rmscene import read_tree
from svglib.svglib import svg2rlg

TRASH_DIR_NAME = "Trash"
KNOWN_EXTENSIONS = (".pdf", ".epub", ".notebook")


@dataclass
class Item:
    id: str
    type: str
    visible_name: str
    parent: str


def snake_case(name: str) -> str:
    for ext in KNOWN_EXTENSIONS:
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return re.sub(r"_+", "_", slug) or "untitled"


def unique_name(used_names: dict[Path, set[str]], parent_dir: Path, base: str) -> str:
    used = used_names.setdefault(parent_dir, set())
    name = base
    n = 1
    while name in used:
        n += 1
        name = f"{base}_{n:02d}"
    used.add(name)
    return name


def load_items(src: Path) -> dict[str, Item]:
    items: dict[str, Item] = {}
    for meta_path in sorted(src.glob("*.metadata")):
        item_id = meta_path.stem
        try:
            data = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"[warn] skipping corrupt metadata: {item_id}")
            continue
        items[item_id] = Item(
            id=item_id,
            type=data.get("type", ""),
            visible_name=data.get("visibleName") or item_id,
            parent=data.get("parent", ""),
        )
    return items


def classify_root(item_id: str, items: dict[str, Item]) -> str:
    """Walk parent pointers up to classify an item as "root" or "trash"."""
    seen: set[str] = set()
    current = item_id
    while True:
        if current in ("", "trash"):
            return "root" if current == "" else "trash"
        if current in seen:
            print(f"[warn] parent cycle detected at {current!r}, placing at export root")
            return "root"
        seen.add(current)
        item = items.get(current)
        if item is None:
            print(f"[warn] orphan parent for {item_id}, placing at export root")
            return "root"
        current = item.parent


def resolve_dir(
    item_id: str,
    items: dict[str, Item],
    dest: Path,
    resolved: dict[str, Path],
    used_names: dict[Path, set[str]],
) -> Path:
    """Return (memoized) the destination directory a CollectionType maps to."""
    if item_id in resolved:
        return resolved[item_id]

    item = items[item_id]
    if item.parent in ("", "trash"):
        parent_dir = dest / TRASH_DIR_NAME if item.parent == "trash" else dest
    else:
        parent_item = items.get(item.parent)
        if parent_item is None:
            root_kind = classify_root(item_id, items)
            parent_dir = dest / TRASH_DIR_NAME if root_kind == "trash" else dest
        else:
            parent_dir = resolve_dir(item.parent, items, dest, resolved, used_names)

    name = unique_name(used_names, parent_dir, snake_case(item.visible_name))
    path = parent_dir / name
    resolved[item_id] = path
    return path


def get_content(src: Path, doc_id: str) -> dict:
    content_path = src / f"{doc_id}.content"
    try:
        return json.loads(content_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def page_ids(content: dict) -> list[str]:
    c_pages = content.get("cPages", {}).get("pages")
    if c_pages:
        return [p["id"] for p in c_pages if "id" in p]
    return list(content.get("pages", []))


def _render_page_worker(rm_path: str, out_path: str) -> None:
    """Render one .rm page to a single-page PDF. Runs in a child process (see
    render_rm_page) because the SVG/PDF rendering stack has been observed to
    hard-crash the whole interpreter (native `free(): invalid size` abort,
    not a catchable Python exception) on some stroke data."""
    with open(rm_path, "rb") as f:
        tree = read_tree(f)
    svg_text = io.StringIO()
    tree_to_svg(tree, svg_text)
    # svg2rlg's XML parser rejects a `str` input that also carries an
    # `encoding=` declaration in its `<?xml ?>` prolog (which the SVG rmc
    # emits always does), so it must be fed as bytes instead.
    svg_buf = io.BytesIO(svg_text.getvalue().encode("utf-8"))
    drawing = svg2rlg(svg_buf)
    if drawing is None:
        raise ValueError("svg2rlg returned no drawing")
    renderPDF.drawToFile(drawing, out_path)


def render_rm_page(rm_path: Path, out_path: Path) -> bool:
    ctx = mp.get_context("fork")
    proc = ctx.Process(target=_render_page_worker, args=(str(rm_path), str(out_path)))
    proc.start()
    proc.join()
    return proc.exitcode == 0 and out_path.exists()


def render_notebook(src: Path, doc_id: str, content: dict, dest_pdf: Path) -> bool:
    writer = PdfWriter()
    rendered = 0
    with tempfile.TemporaryDirectory(prefix="remarkable_page_") as tmp_dir:
        for page_id in page_ids(content):
            rm_path = src / doc_id / f"{page_id}.rm"
            if not rm_path.exists():
                continue
            page_pdf = Path(tmp_dir) / f"{page_id}.pdf"
            if render_rm_page(rm_path, page_pdf):
                writer.append(str(page_pdf))
                rendered += 1
            else:
                print(f"[warn] failed to render page {page_id} of {doc_id}")

        if rendered == 0:
            return False

        dest_pdf.parent.mkdir(parents=True, exist_ok=True)
        with dest_pdf.open("wb") as f:
            writer.write(f)
    return True


def export_document(
    src: Path,
    item: Item,
    dest_dir: Path,
    dest_root: Path,
    used_names: dict[Path, set[str]],
    counts: dict[str, int],
) -> None:
    content = get_content(src, item.id)
    file_type = content.get("fileType") or None
    base = snake_case(item.visible_name)

    if file_type == "pdf":
        src_pdf = src / f"{item.id}.pdf"
        name = unique_name(used_names, dest_dir, base)
        dest_pdf = dest_dir / f"{name}.pdf"
        dest_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_pdf, dest_pdf)
        print(f"[ ok ] {dest_pdf.relative_to(dest_root)}")
        counts["pdf"] += 1
    elif file_type == "epub":
        src_epub = src / f"{item.id}.epub"
        name = unique_name(used_names, dest_dir, base)
        dest_epub = dest_dir / f"{name}.epub"
        dest_epub.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_epub, dest_epub)
        print(f"[ ok ] {dest_epub.relative_to(dest_root)}")
        counts["epub"] += 1
    elif file_type == "notebook":
        name = unique_name(used_names, dest_dir, base)
        dest_pdf = dest_dir / f"{name}.pdf"
        if render_notebook(src, item.id, content, dest_pdf):
            print(f"[ ok ] {dest_pdf.relative_to(dest_root)}  (rendered from notebook)")
            counts["notebook_rendered"] += 1
        else:
            print(f"[warn] no renderable pages for {item.visible_name!r} ({item.id}), skipping")
            counts["notebook_skipped"] += 1
    else:
        print(f"[warn] skipping {item.id} ({item.visible_name!r}): unknown/missing fileType")
        counts["unknown_skipped"] += 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconstruct a browsable folder tree from a reMarkable xochitl export."
    )
    parser.add_argument("src", type=Path, help="path to the xochitl data directory")
    parser.add_argument("dest", type=Path, help="output directory (created if missing)")
    args = parser.parse_args()

    items = load_items(args.src)
    args.dest.mkdir(parents=True, exist_ok=True)

    resolved: dict[str, Path] = {}
    used_names: dict[Path, set[str]] = {}

    for item_id, item in items.items():
        if item.type == "CollectionType":
            resolve_dir(item_id, items, args.dest, resolved, used_names)

    counts = {"pdf": 0, "epub": 0, "notebook_rendered": 0, "notebook_skipped": 0, "unknown_skipped": 0}

    for item_id, item in items.items():
        if item.type != "DocumentType":
            continue
        if item.parent in ("", "trash") or item.parent not in items:
            root_kind = classify_root(item_id, items)
            dest_dir = args.dest / TRASH_DIR_NAME if root_kind == "trash" else args.dest
        else:
            dest_dir = resolve_dir(item.parent, items, args.dest, resolved, used_names)
        export_document(args.src, item, dest_dir, args.dest, used_names, counts)

    print(
        f"\nDone: {counts['pdf']} pdf, {counts['epub']} epub, "
        f"{counts['notebook_rendered']} notebooks rendered, "
        f"{counts['notebook_skipped']} notebooks skipped, "
        f"{counts['unknown_skipped']} unknown skipped."
    )


if __name__ == "__main__":
    main()

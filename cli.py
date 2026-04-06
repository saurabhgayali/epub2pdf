#!/usr/bin/env python3
"""epub2pdf – Convert EPUB files to PDF preserving fonts and bookmarks.

Single-file CLI.  Build to exe with:
  pyinstaller --onefile --name epub2pdf cli.py

Usage:
  python cli.py                            convert all EPUBs in current folder
  python cli.py book.epub                  → book.pdf (same folder)
  python cli.py book.epub output.pdf       → output.pdf
  python cli.py ./src/                     convert all EPUBs in ./src/
  python cli.py ./src/ ./dst/              output goes to ./dst/
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
#  EPUB parsing helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_epub(epub: Path) -> str:
    """Unzip epub into a temp directory; return the directory path."""
    tmp = tempfile.mkdtemp(prefix="epub2pdf_")
    with zipfile.ZipFile(epub, "r") as z:
        z.extractall(tmp)
    return tmp


def _opf_info(root_dir: str) -> Tuple[str, str]:
    """Return (opf_absolute_path, opf_directory) by reading container.xml."""
    container = os.path.join(root_dir, "META-INF", "container.xml")
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    elem = ET.parse(container).find(".//c:rootfile", ns)
    if elem is None:
        raise ValueError("container.xml has no rootfile element")
    rel = elem.get("full-path", "")
    full = os.path.join(root_dir, rel.replace("/", os.sep))
    return full, os.path.dirname(full)


def _local_name(elem: ET.Element) -> str:
    t = elem.tag
    return t.split("}")[-1] if "}" in t else t


def _ns_prefix(root_elem: ET.Element) -> str:
    m = re.match(r"\{([^}]+)\}", root_elem.tag)
    return f"{{{m.group(1)}}}" if m else ""


def _parse_opf(opf: str, opf_dir: str) -> Tuple[List[Dict], Optional[str]]:
    """Return (spine_items, toc_file_path_or_None)."""
    root = ET.parse(opf).getroot()
    p = _ns_prefix(root)

    manifest: Dict[str, Dict] = {}
    for item in root.iter(f"{p}item"):
        manifest[item.get("id", "")] = {
            "href": item.get("href", ""),
            "media_type": item.get("media-type", ""),
            "properties": item.get("properties", ""),
        }

    spine: List[Dict] = []
    for ref in root.iter(f"{p}itemref"):
        iid = ref.get("idref", "")
        if iid in manifest:
            href = manifest[iid]["href"]
            spine.append({
                **manifest[iid],
                "id": iid,
                "path": os.path.normpath(
                    os.path.join(opf_dir, href.replace("/", os.sep))
                ),
            })

    # EPUB 3 nav document takes priority over EPUB 2 NCX
    toc_path: Optional[str] = None
    for item in manifest.values():
        if "nav" in item.get("properties", "").split():
            toc_path = os.path.normpath(
                os.path.join(opf_dir, item["href"].replace("/", os.sep))
            )
            break
    if toc_path is None:
        spine_el = root.find(f"{p}spine")
        ncx_id = spine_el.get("toc") if spine_el is not None else None
        if ncx_id and ncx_id in manifest:
            toc_path = os.path.normpath(
                os.path.join(opf_dir, manifest[ncx_id]["href"].replace("/", os.sep))
            )

    return spine, toc_path


def _parse_ncx(ncx_path: str) -> List[Dict]:
    """Parse EPUB 2 NCX → [{'title', 'src', 'level'}, …]."""
    root = ET.parse(ncx_path).getroot()
    p = _ns_prefix(root)
    items: List[Dict] = []

    def walk(node: ET.Element, lvl: int = 0) -> None:
        lbl = node.find(f"{p}navLabel/{p}text")
        ct = node.find(f"{p}content")
        if lbl is not None and ct is not None:
            items.append({
                "title": (lbl.text or "").strip(),
                "src": ct.get("src", ""),
                "level": lvl,
            })
        for child in node.findall(f"{p}navPoint"):
            walk(child, lvl + 1)

    navmap = root.find(f"{p}navMap")
    if navmap is not None:
        for np in navmap.findall(f"{p}navPoint"):
            walk(np)
    return items


def _parse_nav(nav_path: str) -> List[Dict]:
    """Parse EPUB 3 NAV HTML → [{'title', 'src', 'level'}, …]."""
    EPUB_NS = "http://www.idpf.org/2007/ops"
    root = ET.parse(nav_path).getroot()
    items: List[Dict] = []

    def find_toc_nav(el: ET.Element) -> Optional[ET.Element]:
        if _local_name(el) == "nav":
            etype = el.get(f"{{{EPUB_NS}}}type", "") or el.get("epub:type", "")
            if "toc" in etype.split():
                return el
        for ch in el:
            found = find_toc_nav(ch)
            if found is not None:
                return found
        return None

    def parse_ol(ol: ET.Element, lvl: int = 0) -> None:
        for li in ol:
            if _local_name(li) != "li":
                continue
            anchor = sub_ol = None
            for ch in li:
                n = _local_name(ch)
                if n in ("a", "span") and anchor is None:
                    anchor = ch
                elif n == "ol":
                    sub_ol = ch
            if anchor is not None:
                title = "".join(anchor.itertext()).strip()
                href = anchor.get("href", "")
                items.append({"title": title, "src": href, "level": lvl})
            if sub_ol is not None:
                parse_ol(sub_ol, lvl + 1)

    nav_el = find_toc_nav(root)
    if nav_el is not None:
        for ch in nav_el:
            if _local_name(ch) == "ol":
                parse_ol(ch)
                break
    return items


def _get_toc(toc_path: Optional[str]) -> List[Dict]:
    if not toc_path or not os.path.isfile(toc_path):
        return []
    try:
        items = _parse_nav(toc_path)        # Try NAV first
        return items if items else _parse_ncx(toc_path)   # fallback NCX
    except Exception:
        return []


def _html_spine(spine: List[Dict]) -> List[str]:
    """Return absolute paths of HTML/XHTML files from the spine, in order."""
    out: List[str] = []
    for item in spine:
        mt = item.get("media_type", "")
        p = item["path"]
        if (
            "html" in mt
            or p.lower().endswith((".html", ".xhtml", ".htm"))
        ) and os.path.isfile(p):
            out.append(p)
    return out


def _page_for(src: str, html_files: List[str], starts: Dict[str, int]) -> int:
    """Find the first PDF page number for a TOC entry src."""
    bare = src.split("#")[0].replace("/", os.sep)
    for hf in html_files:
        if os.path.normpath(hf).endswith(os.path.normpath(bare)):
            return starts.get(hf, 0)
    return 0


def _detect_page_size(html_path: str) -> Optional[Tuple[float, float]]:
    """Detect the intended page dimensions (CSS pixels) from an HTML/XHTML file.

    Checks in priority order:
      1. ``@page { size: W H }`` inside inline ``<style>`` blocks.
      2. ``@page { size: W H }`` inside linked ``.css`` files.
      3. ``<meta name="viewport" content="width=W, height=H">``.
      4. ``<svg viewBox="0 0 W H">`` or ``<svg width="W" height="H">``.
      5. First ``<img width="W" height="H">``.

    Returns ``(width_px, height_px)`` or ``None``.
    """
    html_dir = os.path.dirname(html_path)
    try:
        with open(html_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return None

    # ── helper: extract (w, h) from a block of CSS text ──────────────────────
    def _from_css(css: str) -> Optional[Tuple[float, float]]:
        # @page { ... size: W H ... }  — numeric px values
        for blk in re.finditer(r"@page\s*\{([^}]*)\}", css, re.DOTALL | re.IGNORECASE):
            m = re.search(
                r"\bsize\s*:\s*([\d.]+)(?:px)?\s+([\d.]+)(?:px)?",
                blk.group(1), re.IGNORECASE,
            )
            if m:
                return float(m.group(1)), float(m.group(2))
        return None

    # 1. Inline <style> blocks
    for style_m in re.finditer(r"<style[^>]*>(.*?)</style>", content,
                                re.DOTALL | re.IGNORECASE):
        r = _from_css(style_m.group(1))
        if r:
            return r

    # 2. Linked CSS files
    for link_m in re.finditer(
        r'<link[^>]+href=["\']([^"\']+\.css)["\']', content, re.IGNORECASE
    ):
        css_rel = link_m.group(1).replace("/", os.sep).lstrip(os.sep)
        css_abs = os.path.normpath(os.path.join(html_dir, css_rel))
        if os.path.isfile(css_abs):
            try:
                with open(css_abs, "r", encoding="utf-8", errors="replace") as fh:
                    r = _from_css(fh.read())
                if r:
                    return r
            except OSError:
                pass

    # 3. <meta name="viewport" content="width=W, height=H">
    for vp_m in re.finditer(
        r'<meta\b[^>]*\bname=["\']viewport["\'][^>]*content=["\']([^"\']+)["\']'
        r'|<meta\b[^>]*\bcontent=["\']([^"\']+)["\'][^>]*\bname=["\']viewport["\']',
        content, re.IGNORECASE,
    ):
        vp_str = vp_m.group(1) or vp_m.group(2)
        w_m = re.search(r"\bwidth\s*=\s*([\d.]+)", vp_str)
        h_m = re.search(r"\bheight\s*=\s*([\d.]+)", vp_str)
        if w_m and h_m:
            return float(w_m.group(1)), float(h_m.group(1))

    # 4. <svg> root element  — viewBox or width/height attributes
    svg_m = re.search(r"<svg\b[^>]+>", content, re.IGNORECASE | re.DOTALL)
    if svg_m:
        tag = svg_m.group(0)
        vb = re.search(
            r'\bviewBox=["\'][\d. ]*?([\d.]+)\s+([\d.]+)["\']', tag, re.IGNORECASE
        )
        if vb:
            return float(vb.group(1)), float(vb.group(2))
        w_m = re.search(r'\bwidth=["\']?([\d.]+)(?:px)?["\']?', tag)
        h_m = re.search(r'\bheight=["\']?([\d.]+)(?:px)?["\']?', tag)
        if w_m and h_m:
            return float(w_m.group(1)), float(h_m.group(1))

    # 5. First <img> with explicit width + height attributes
    img_m = re.search(r"<img\b[^>]+>", content, re.IGNORECASE | re.DOTALL)
    if img_m:
        tag = img_m.group(0)
        w_m = re.search(r'\bwidth=["\']?([\d.]+)["\']?', tag)
        h_m = re.search(r'\bheight=["\']?([\d.]+)["\']?', tag)
        if w_m and h_m:
            return float(w_m.group(1)), float(h_m.group(1))

    return None


def _is_image_only_html(html_path: str) -> bool:
    """Return True when the HTML file consists almost entirely of <img> tags.

    Scanned-book EPUBs (the Calibre "image dump" format) pack dozens of JPEG
    pages into one HTML file with zero real text.  Feeding such a file to
    WeasyPrint produces an arbitrary A4-paginated mess.  We detect this pattern
    and bypass WeasyPrint entirely for those files.

    Heuristic: ≥2 images AND fewer than 30 non-whitespace characters of text
    per image on average.
    """
    try:
        with open(html_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return False
    img_count = len(re.findall(r"<img\b", content, re.I))
    if img_count < 2:
        return False
    stripped = re.sub(r"<[^>]+>", " ", content)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return len(stripped) < img_count * 30


def _extract_img_list(
    html_path: str,
) -> List[Tuple[str, Optional[int], Optional[int]]]:
    """Return [(abs_img_path, width_px_or_None, height_px_or_None), ...].

    Walks every <img> element in the HTML in document order, resolves its
    ``src`` relative to the HTML file's directory, and reads optional
    ``width``/``height`` attributes.  Missing-file entries are skipped.
    """
    html_dir = os.path.dirname(html_path)
    try:
        with open(html_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return []
    results: List[Tuple[str, Optional[int], Optional[int]]] = []
    for m in re.finditer(r"<img\b([^>]+)>", content, re.I | re.DOTALL):
        attrs = m.group(1)
        src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', attrs, re.I)
        if not src_m:
            continue
        src = src_m.group(1).split("?")[0]   # strip any query string
        abs_p = os.path.normpath(
            os.path.join(html_dir, src.replace("/", os.sep))
        )
        if not os.path.isfile(abs_p):
            continue
        wm = re.search(r'\bwidth=["\']?(\d+)', attrs, re.I)
        hm = re.search(r'\bheight=["\']?(\d+)', attrs, re.I)
        results.append((
            abs_p,
            int(wm.group(1)) if wm else None,
            int(hm.group(1)) if hm else None,
        ))
    return results


def _imgs_to_pdf_bytes(
    img_list: List[Tuple[str, Optional[int], Optional[int]]],
    cb: Callable[[str, int], None],
    pct_start: int,
    pct_end: int,
) -> bytes:
    """Render each image in *img_list* as its own PDF page and return the bytes.

    Uses Pillow directly — no WeasyPrint — so every page is exactly the size
    of its source image (1 px = 1 pt at 72 dpi).  This correctly preserves
    landscape vs. portrait per image, which is what ``--split`` needs.
    """
    try:
        from PIL import Image as PILImg   # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            f"Pillow is required for image-only EPUBs: {exc}\n"
            "  Install with:  pip install Pillow"
        ) from exc
    import pypdf  # noqa: PLC0415

    writer = pypdf.PdfWriter()
    n = len(img_list)
    for i, (img_path, _w, _h) in enumerate(img_list, 1):
        pct = pct_start + int((pct_end - pct_start) * i / max(n, 1))
        cb(f"    image {i}/{n}", pct)
        try:
            with PILImg.open(img_path) as img:
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                # resolution=72 ↔ 1 pixel = 1 point → page size = img.size in pts
                img.save(buf, format="PDF", resolution=72)
            buf.seek(0)
            for page in pypdf.PdfReader(buf).pages:
                writer.add_page(page)
        except Exception as exc:
            cb(f"    WARNING: skipped {os.path.basename(img_path)}: {exc}", pct)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _is_landscape(page) -> bool:
    """Return True when a PDF page is wider than it is tall."""
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)
    return w > h + 0.5          # 0.5 pt tolerance to ignore square-ish pages


def _split_page(page) -> Tuple[object, object]:
    """Split a landscape PDF page into (left_half, right_half) page objects.

    Each half gets its own mediabox and cropbox so PDF viewers render only
    the relevant portion.
    """
    import pypdf  # local import — already guaranteed by caller

    w = float(page.mediabox.width)
    h = float(page.mediabox.height)
    mid = w / 2.0

    def _half(x0: float, x1: float):
        tmp = pypdf.PdfWriter()
        tmp.add_page(page)          # clones the page into tmp's object store
        p = tmp.pages[0]
        p.mediabox.lower_left  = (x0, 0)
        p.mediabox.upper_right = (x1, h)
        p.cropbox.lower_left   = (x0, 0)
        p.cropbox.upper_right  = (x1, h)
        return p

    return _half(0, mid), _half(mid, w)


# ═══════════════════════════════════════════════════════════════════════════════
#  Public conversion API
# ═══════════════════════════════════════════════════════════════════════════════

def convert_file(
    input_path: str,
    output_path: str,
    on_progress: Optional[Callable[[str, int], None]] = None,
    split_landscape: bool = False,
) -> None:
    """Convert a single EPUB file to PDF.

    Args:
        input_path:      Path to the source .epub file.
        output_path:     Path to write the resulting .pdf.
        on_progress:     Optional callback(message: str, percent: int).
        split_landscape: When True, each landscape page (width > height) is
                         automatically split at the mid-point into two
                         portrait-oriented pages (left then right).
                         Portrait pages are left untouched regardless.

    Raises:
        RuntimeError: if weasyprint / pypdf are not installed.
        FileNotFoundError: if the input file does not exist.
        ValueError: if no readable HTML content is found in the EPUB.
    """
    try:
        from weasyprint import HTML as WP, CSS as WPCSS   # noqa: PLC0415
        import pypdf                                        # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            f"Missing dependency: {exc}\n"
            "  Install with:  pip install weasyprint pypdf"
        ) from exc

    cb = on_progress or (lambda m, p: None)
    inp = Path(input_path).resolve()
    out = Path(output_path).resolve()

    if not inp.exists():
        raise FileNotFoundError(f"Input file not found: {inp}")

    out.parent.mkdir(parents=True, exist_ok=True)

    cb("Extracting EPUB…", 5)
    tmp = _extract_epub(inp)
    try:
        opf, opf_dir = _opf_info(tmp)
        spine, toc_path = _parse_opf(opf, opf_dir)
        toc = _get_toc(toc_path)
        html_files = _html_spine(spine)

        if not html_files:
            raise ValueError("No readable HTML content found in EPUB.")

        n = len(html_files)
        cb(f"Rendering {n} section(s)…", 15)

        # Render each HTML section to PDF bytes.
        #
        # Three strategies, chosen automatically per section:
        #
        #  A) Image-only HTML (scanned-book EPUBs with dozens of <img> tags,
        #     no real text, no @page CSS):
        #     → bypass WeasyPrint; convert each <img> directly via Pillow so
        #       every scanned page gets its own correctly-sized PDF page.
        #       This is the only reliable way to handle the "234 images in
        #       one HTML" pattern that Calibre / some converters produce.
        #
        #  B) Fixed-layout HTML with detectable page dimensions:
        #     → inject @page { size: Wpx Hpx } override before calling WeasyPrint
        #       so landscape pages render as landscape (not forced to A4).
        #
        #  C) Normal reflowable HTML:
        #     → pass straight to WeasyPrint with its defaults.
        parts: List[bytes] = []
        for i, hf in enumerate(html_files, 1):
            pct_a = 15 + int(68 * (i - 1) / n)
            pct_b = 15 + int(68 * i / n)
            cb(f"  section {i}/{n}", pct_a)

            if _is_image_only_html(hf):
                img_list = _extract_img_list(hf)
                if img_list:
                    cb(f"  (image-only: {len(img_list)} images, rendering via Pillow)", pct_a)
                    parts.append(_imgs_to_pdf_bytes(img_list, cb, pct_a, pct_b))
                    continue
            # Fixed-layout: inject detected page size
            size = _detect_page_size(hf)
            if size:
                w, h = size
                page_css = WPCSS(string=f"@page {{ size: {w}px {h}px; }}")
                parts.append(WP(filename=hf).write_pdf(stylesheets=[page_css]))
            else:
                parts.append(WP(filename=hf).write_pdf())

        cb("Merging pages…", 85)
        writer = pypdf.PdfWriter()
        starts: Dict[str, int] = {}
        landscape_count = 0
        for hf, pdf_bytes in zip(html_files, parts):
            starts[hf] = len(writer.pages)
            for page in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages:
                if split_landscape and _is_landscape(page):
                    left, right = _split_page(page)
                    writer.add_page(left)
                    writer.add_page(right)
                    landscape_count += 1
                else:
                    writer.add_page(page)
        if split_landscape and landscape_count:
            cb(f"Split {landscape_count} landscape page(s) into pairs…", 88)

        # Add hierarchical PDF bookmarks from TOC
        if toc:
            cb("Adding bookmarks…", 93)
            stack: List[Tuple[int, object]] = []
            for entry in toc:
                lvl = entry["level"]
                pg = _page_for(entry["src"], html_files, starts)
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                parent_ref = stack[-1][1] if stack else None
                ref = writer.add_outline_item(
                    entry["title"], pg, parent=parent_ref
                )
                stack.append((lvl, ref))

        with open(out, "wb") as f:
            writer.write(f)

        cb(f"Saved → {out}", 100)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def convert_folder(
    src_dir: str,
    dst_dir: Optional[str] = None,
    on_progress: Optional[Callable[[str, int], None]] = None,
    split_landscape: bool = False,
) -> List[Tuple[str, bool, str]]:
    """Convert every .epub in src_dir to PDF in dst_dir (default: same folder).

    Returns list of (epub_path, success, info_string).
    """
    src = Path(src_dir).resolve()
    dst = Path(dst_dir).resolve() if dst_dir else src
    dst.mkdir(parents=True, exist_ok=True)

    epubs = sorted(src.glob("*.epub"))
    results: List[Tuple[str, bool, str]] = []

    for i, epub in enumerate(epubs):
        out = dst / (epub.stem + ".pdf")
        prefix = f"[{i + 1}/{len(epubs)}] {epub.name}: "

        def _cb(msg: str, pct: int, _pfx: str = prefix) -> None:
            if on_progress:
                on_progress(f"{_pfx}{msg}", pct)

        try:
            convert_file(str(epub), str(out), _cb, split_landscape=split_landscape)
            results.append((str(epub), True, str(out)))
        except Exception as exc:
            if on_progress:
                on_progress(f"{prefix}ERROR: {exc}", 0)
            results.append((str(epub), False, str(exc)))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="epub2pdf",
        description="Convert EPUB to PDF — fonts and bookmarks preserved.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  epub2pdf                              scan current folder, convert all EPUBs
  epub2pdf book.epub                    → book.pdf
  epub2pdf book.epub novel.pdf          → novel.pdf
  epub2pdf ./books/                     convert all EPUBs in ./books/
  epub2pdf ./books/ ./pdfs/             output to ./pdfs/
  epub2pdf manga.epub --split           split landscape spreads into 2 pages
""",
    )
    ap.add_argument(
        "input", nargs="?", metavar="INPUT",
        help="EPUB file or folder  (omit to scan the current folder)",
    )
    ap.add_argument(
        "output", nargs="?", metavar="OUTPUT",
        help="Output PDF file or folder",
    )
    ap.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress progress messages",
    )
    ap.add_argument(
        "--split", action="store_true",
        help=(
            "Split every landscape page at its midpoint into two portrait "
            "pages (left then right). Portrait pages are never split. "
            "Landscape is auto-detected (page width > height)."
        ),
    )
    args = ap.parse_args()

    def cb(msg: str, pct: int) -> None:
        if not args.quiet:
            print(f"  [{pct:3d}%] {msg}")

    inp: str = args.input or "."
    out: Optional[str] = args.output

    if os.path.isdir(inp):
        results = convert_folder(inp, out, cb, split_landscape=args.split)
        if not results:
            print(f"No .epub files found in '{inp}'.")
            sys.exit(0)
        print()
        for epub, ok, info in results:
            tick = "OK  " if ok else "FAIL"
            print(f"  [{tick}] {Path(epub).name}  →  {info}")
    else:
        out_path = out or str(Path(inp).with_suffix(".pdf"))
        try:
            convert_file(inp, out_path, cb, split_landscape=args.split)
            print(f"\nDone: {out_path}")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

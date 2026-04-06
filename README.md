# epub2pdf

Convert EPUB files to PDF — fonts, bookmarks, and page layout fully preserved.
Single-file CLI and GUI. Builds to a standalone executable on Windows, macOS, and Linux.

---

## Table of Contents

1. [Features](#features)
2. [User Guide](#user-guide)
   - [Download Binaries](#download-binaries)
   - [Using the GUI](#using-the-gui)
   - [Using the CLI](#using-the-cli)
3. [Automatic Detection](#automatic-detection)
4. [AI Integration Ideas](#ai-integration-ideas)
5. [Developer Guide](#developer-guide)
   - [Prerequisites](#prerequisites)
   - [Running from Source](#running-from-source)
   - [Building Executables](#building-executables)
   - [Project Structure](#project-structure)

---

## Features

| Feature | Detail |
|---|---|
| Font preservation | Embedded fonts from EPUB CSS are rendered faithfully via WeasyPrint |
| Bookmark preservation | EPUB 3 NAV and EPUB 2 NCX tables of contents become nested PDF outline entries |
| **Auto layout detection** | Detects image-only EPUBs, fixed-layout dimensions, and landscape spreads automatically (see [Automatic Detection](#automatic-detection)) |
| **Landscape split** | Optional `--split` flag cuts each landscape two-page spread into its two individual portrait pages |
| Batch convert | Point at a folder to convert every `.epub` in it in one run |
| Cross-platform | Works on Windows, macOS, Linux — both CLI and GUI |
| Single-file exes | Both tools build to single `.exe` / binary with PyInstaller — no Python needed on end-user machine |

---

## User Guide

### Download Binaries

Download the latest release from the Releases page. Two files are provided:

| File | Purpose |
|---|---|
| `epub2pdf.exe` (Windows) / `epub2pdf` (macOS/Linux) | Command-line tool |
| `epub2pdf-gui.exe` (Windows) / `epub2pdf-gui` (macOS/Linux) | Graphical interface |

Both files are fully self-contained — no Python, no installer, no dependencies needed.

> **macOS / Linux:** After downloading, mark the binary as executable:
> ```sh
> chmod +x epub2pdf epub2pdf-gui
> ```

---

### Using the GUI

Double-click `epub2pdf-gui.exe` (or run `./epub2pdf-gui` on macOS/Linux).

# GUI 
<br><img width="722" height="615" alt="image" src="https://github.com/user-attachments/assets/5dfcc6b2-3f29-4933-b109-6d220ace8c63" />



**Typical workflows:**

| Goal | What to do |
|---|---|
| Convert one book | Select *Single file*, browse for the `.epub`, click Convert |
| Convert a whole folder | Select *Folder*, browse for the source folder, click Convert |
| Leave output blank | PDF is placed next to the source file with the same name |
| Comic / manga spread | Tick *Split landscape pages*, then Convert |

Progress and any warnings appear in the log panel at the bottom.

---

### Using the CLI

```
epub2pdf [INPUT] [OUTPUT] [--split] [-q]
```

| Argument | Description |
|---|---|
| `INPUT` | EPUB file or folder. Omit to scan the current directory. |
| `OUTPUT` | PDF file or output folder. Omit to use the same name/location. |
| `--split` | Split landscape pages at the midpoint into two portrait pages. |
| `-q` / `--quiet` | Suppress progress output. |

**Examples:**

```sh
# Convert one file (output: book.pdf)
epub2pdf book.epub

# Convert with explicit output name
epub2pdf book.epub output/novel.pdf

# Convert all EPUBs in a folder → same folder
epub2pdf ./my-books/

# Convert all EPUBs in a folder → different output folder
epub2pdf ./my-books/ ./pdfs/

# Scan current directory and convert everything found
epub2pdf

# Comic with two-page landscape spreads → split each spread into 2 pages
epub2pdf manga.epub --split

# Batch convert comics with split, quietly
epub2pdf ./comics/ ./comics-pdf/ --split -q
```

---

## Automatic Detection

No manual flags are needed for layout detection. Every conversion goes through a **three-stage auto-detection pipeline** per HTML section inside the EPUB:

### Stage 1 — Image-Only EPUB (scanned books, comics, textbooks)

**Trigger:** The HTML section contains ≥ 2 `<img>` tags and almost no text (< 30 characters per image on average). This matches Calibre-converted scans, manga and comic EPUBs, and scanned academic textbooks.

**Action:** WeasyPrint is bypassed entirely. Each `<img>` is rendered directly via **Pillow** at its native pixel dimensions (1 px = 1 PDF pt at 72 dpi). Every scanned page becomes its own correctly-sized PDF page — portrait or landscape, exactly as the original image.

> Without this path, WeasyPrint would flow all images into an A4 document, chopping images across arbitrary page breaks.

### Stage 2 — Fixed-Layout EPUB (ebooks with explicit page dimensions)

**Trigger:** A page size is found in any of these locations (checked in order):
1. `@page { size: W H }` in inline `<style>` blocks
2. `@page { size: W H }` in linked `.css` files
3. `<meta name="viewport" content="width=W, height=H">`
4. `<svg viewBox="0 0 W H">` or `<svg width="W" height="H">`
5. First `<img width="W" height="H">`

**Action:** An `@page { size: Wpx Hpx }` stylesheet override is injected into WeasyPrint so the PDF pages match the EPUB's intended dimensions — landscape where the EPUB is landscape.

### Stage 3 — Reflowable EPUB (standard text books)

**Trigger:** Neither of the above applies.

**Action:** WeasyPrint renders with its defaults. Fonts and bookmarks are preserved as normal.

### Landscape Split (`--split` / GUI checkbox)

After rendering, every PDF page is checked: if `width > height` (with a 0.5 pt tolerance), the page is a landscape spread. With `--split` active, each such page is sliced at its horizontal midpoint into a left page and a right page. Portrait pages are never touched.

This detection is based on the **actual rendered PDF page dimensions**, not any metadata — so it works regardless of which rendering path was used.

---

## AI Integration Ideas

> **These are proposed future enhancements — none are implemented yet.**
> The automatic detection pipeline (stages 1–3 above) is already built-in and requires no AI.
> The ideas below describe where AI/ML could extend the tool further.

### 1. Smarter Page Classification *(not yet implemented)*
Replace or augment `_is_image_only_html()` with a small vision model (e.g. a CLIP-based classifier) that distinguishes:
- Text pages
- Mixed text+image pages
- Full-page scans
- Two-page spreads needing a split

This would remove the need for the `--split` flag entirely.

### 2. OCR Layer for Scanned Books *(not yet implemented)*
After the Pillow image path renders scanned pages, run **Tesseract / EasyOCR / Surya** on each image and embed the OCR text as an invisible layer in the PDF. The result is a searchable, copy-paste-able PDF from a scanned EPUB.

Proposed CLI flags (not active):
```
# --ocr and --ocr-lang are NOT current options — shown as design sketch only
epub2pdf scan.epub --ocr
epub2pdf scan.epub --ocr-lang jpn
```

### 3. Auto Split Detection via Aspect Ratio Clustering *(not yet implemented)*
Instead of a fixed `width > height` rule, cluster image aspect ratios across the whole EPUB and auto-detect the "spread" dimension class. Useful for EPUBs where spreads are only slightly wider than portrait pages.

### 4. Table of Contents Generation for Scanless EPUBs *(not yet implemented)*
For image-only EPUBs with no NCX/NAV, use a vision model to detect chapter-header pages and auto-generate a PDF table of contents.

### 5. Reading Order Correction *(not yet implemented)*
Some scanned manga EPUBs store pages right-to-left. A classifier could detect this and reorder pages (and set the PDF reading direction) automatically.

---

## Developer Guide

### Prerequisites

- Python 3.9 or higher
- `pip` (comes with Python)
- `tkinter` — included with standard Python on Windows and macOS. On Linux: `sudo apt install python3-tk`
- WeasyPrint 60+ uses a pure-Python PDF renderer — **no GTK/Pango/Cairo install needed** on any platform.

### Running from Source

```sh
# Clone / download the project, then from the EpubtoPdf/ folder:

# Run CLI (creates venv and installs dependencies automatically on first run)
python run.py book.epub
python run.py book.epub out.pdf
python run.py ./folder/
python run.py manga.epub --split

# Run GUI
python run-gui.py
```

Both `run.py` and `run-gui.py`:
- Create `./venv` if it doesn't exist
- Install `requirements.txt` into the venv
- Launch the tool inside the venv
- Pass through all arguments unchanged

To force a clean reinstall of the venv:
```sh
python run.py --reinstall
python run-gui.py --reinstall
```

### Building Executables

```sh
# Build both epub2pdf and epub2pdf-gui
python build.py

# Build CLI only
python build.py --cli-only

# Build GUI only
python build.py --gui-only

# Rebuild everything from a clean venv
python build.py --reinstall
```

Output is placed in `dist/`:
```
dist/
  epub2pdf.exe       ← standalone CLI
  epub2pdf-gui.exe   ← standalone GUI (no console window)
```

`build.py` automatically:
1. Creates `./venv` if needed
2. Installs `requirements.txt` + `pyinstaller` and `pyinstaller-hooks-contrib`
3. Runs PyInstaller with `--onefile` and `--collect-all weasyprint` to bundle WeasyPrint's CSS/font data
4. Uses `--windowed` for the GUI build (no console window on Windows/macOS)

### Project Structure

```
EpubtoPdf/
├── cli.py            # Conversion engine + argparse CLI (single file, buildable to exe)
├── GUI.py            # tkinter GUI — imports engine from cli.py
├── run.py            # Dev runner: creates venv, installs deps, runs cli.py
├── run-gui.py        # Dev runner: creates venv, installs deps, runs GUI.py
├── build.py          # PyInstaller build script (cross-platform)
└── requirements.txt  # weasyprint>=60, pypdf>=3, Pillow>=9
```

**Key functions in `cli.py`:**

| Function | Purpose |
|---|---|
| `_is_image_only_html()` | Detect scanned-image HTML sections |
| `_extract_img_list()` | Walk `<img>` tags in document order |
| `_imgs_to_pdf_bytes()` | Render images to PDF via Pillow (one page per image) |
| `_detect_page_size()` | Detect fixed-layout page dimensions from CSS/viewport/SVG |
| `_is_landscape()` | Check actual rendered PDF page dimensions |
| `_split_page()` | Slice a landscape PDF page into left/right halves |
| `convert_file()` | Public API: convert one EPUB to PDF |
| `convert_folder()` | Public API: convert all EPUBs in a folder |

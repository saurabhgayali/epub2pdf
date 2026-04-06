#!/usr/bin/env python3
"""build.py – Build standalone executables for cli.py and GUI.py.

Creates (or reuses) ./venv, installs requirements + PyInstaller,
then produces:
  dist/epub2pdf          (or epub2pdf.exe on Windows)  – CLI tool
  dist/epub2pdf-gui      (or epub2pdf-gui.exe)          – GUI tool

Usage:
  python build.py                  build both targets
  python build.py --cli-only       build CLI only
  python build.py --gui-only       build GUI only
  python build.py --reinstall      recreate the venv before building
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
VENV = HERE / "venv"
REQ = HERE / "requirements.txt"
DIST = HERE / "dist"
BUILD_TMP = HERE / "build"


# ── Venv helpers ──────────────────────────────────────────────────────────────

def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _venv_pyinstaller() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "pyinstaller.exe"
    return VENV / "bin" / "pyinstaller"


def _ensure_venv(reinstall: bool = False) -> tuple[Path, Path]:
    py = _venv_python()
    pi = _venv_pyinstaller()

    if reinstall and VENV.exists():
        print("Removing existing venv…")
        shutil.rmtree(VENV)

    if not py.exists():
        print("Creating virtual environment…")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])

    if not pi.exists():
        print("Installing requirements and PyInstaller…")
        subprocess.check_call(
            [str(py), "-m", "pip", "install", "--quiet", "-r", str(REQ)]
        )
        subprocess.check_call(
            [str(py), "-m", "pip", "install", "--quiet",
             "pyinstaller", "pyinstaller-hooks-contrib"]
        )
        print("Setup complete.\n")

    return py, pi


# ── Build helpers ─────────────────────────────────────────────────────────────

def _build(pi: Path, script: Path, name: str, windowed: bool = False) -> None:
    """Run PyInstaller to produce a single-file executable."""
    print(f"\n{'─' * 60}")
    print(f"Building:  {name}")
    print(f"Source:    {script.name}")
    print(f"{'─' * 60}")

    cmd = [
        str(pi), str(script),
        "--onefile",
        "--name", name,
        "--distpath", str(DIST),
        "--workpath", str(BUILD_TMP),
        "--specpath", str(BUILD_TMP),
        # WeasyPrint: collect all submodule data (CSS, fonts, etc.)
        "--collect-all", "weasyprint",
        # Suppress the bootloader console on GUI builds
    ]
    if windowed:
        cmd.append("--windowed")

    subprocess.check_call(cmd)

    exe_suffix = ".exe" if sys.platform == "win32" else ""
    print(f"\nBuilt →  dist/{name}{exe_suffix}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build epub2pdf executables with PyInstaller."
    )
    ap.add_argument("--cli-only", action="store_true", help="Build CLI only")
    ap.add_argument("--gui-only", action="store_true", help="Build GUI only")
    ap.add_argument(
        "--reinstall", action="store_true",
        help="Recreate the venv before building",
    )
    args = ap.parse_args()

    _py, pi = _ensure_venv(reinstall=args.reinstall)

    build_cli = not args.gui_only
    build_gui = not args.cli_only

    if build_cli:
        _build(pi, HERE / "cli.py", "epub2pdf", windowed=False)

    if build_gui:
        _build(pi, HERE / "GUI.py", "epub2pdf-gui", windowed=True)

    print("\n" + "═" * 60)
    print("Build complete!  Executables are in the  dist/  folder.")
    if sys.platform == "win32":
        if build_cli:
            print("  dist\\epub2pdf.exe")
        if build_gui:
            print("  dist\\epub2pdf-gui.exe")
    else:
        if build_cli:
            print("  dist/epub2pdf")
        if build_gui:
            print("  dist/epub2pdf-gui")
    print("═" * 60)


if __name__ == "__main__":
    main()

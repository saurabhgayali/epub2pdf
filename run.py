#!/usr/bin/env python3
"""run.py – Run cli.py inside a managed virtual environment.

Creates ./venv, installs requirements.txt (once), then forwards all
command-line arguments to cli.py.

Usage:
  python run.py                          # convert EPUBs in current folder
  python run.py book.epub                # → book.pdf
  python run.py book.epub out.pdf
  python run.py ./src/ ./dst/
  python run.py --reinstall              # force-recreate the venv
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
VENV = HERE / "venv"
REQ = HERE / "requirements.txt"


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _ensure_venv() -> Path:
    py = _venv_python()

    if "--reinstall" in sys.argv:
        sys.argv.remove("--reinstall")
        print("Removing existing venv…")
        shutil.rmtree(VENV, ignore_errors=True)

    if not py.exists():
        print("Creating virtual environment…")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        print("Installing requirements…")
        subprocess.check_call(
            [str(py), "-m", "pip", "install", "--quiet", "-r", str(REQ)]
        )
        print("Setup complete.\n")

    return py


if __name__ == "__main__":
    py = _ensure_venv()
    script = HERE / "cli.py"
    result = subprocess.run([str(py), str(script)] + sys.argv[1:])
    sys.exit(result.returncode)

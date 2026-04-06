#!/usr/bin/env python3
"""run-gui.py – Run GUI.py inside a managed virtual environment.

Creates ./venv, installs requirements.txt (once), then launches the GUI.

Usage:
  python run-gui.py
  python run-gui.py --reinstall    # force-recreate the venv
"""
from __future__ import annotations

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
    script = HERE / "GUI.py"
    result = subprocess.run([str(py), str(script)])
    sys.exit(result.returncode)

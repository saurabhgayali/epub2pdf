#!/usr/bin/env python3
"""epub2pdf GUI – Convert EPUB files to PDF with a tkinter interface.

Single-file GUI script.  Build to exe with:
  pyinstaller --onefile --windowed --name epub2pdf-gui GUI.py

Imports the conversion engine from cli.py (must be in the same folder).
"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk

# ---------------------------------------------------------------------------
# Ensure cli.py (conversion engine) is importable when the script runs from
# its own directory (also works after PyInstaller bundles both files).
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from cli import convert_file, convert_folder  # noqa: E402
except ImportError as _err:
    # Show a friendly error window if the engine is missing
    _root = tk.Tk()
    _root.withdraw()
    import tkinter.messagebox as _mb
    _mb.showerror(
        "Import error",
        f"Cannot import cli.py:\n{_err}\n\nMake sure cli.py is in the same folder.",
    )
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Main application window
# ═══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    """Top-level window for the EPUB → PDF converter."""

    PAD = 10
    BTN_WIDTH = 9

    def __init__(self) -> None:
        super().__init__()
        self.title("EPUB → PDF Converter")
        self.resizable(True, True)
        self.minsize(620, 530)

        self._mode = tk.StringVar(value="file")   # "file" | "folder"
        self._input_var = tk.StringVar()
        self._output_var = tk.StringVar()
        self._split_var = tk.BooleanVar(value=False)
        self._progress_var = tk.DoubleVar(value=0.0)
        self._converting = False

        self._build_ui()
        self._center_window()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        p = self.PAD

        # ── Mode row ──────────────────────────────────────────────────────────
        mf = ttk.LabelFrame(self, text="Conversion mode", padding=6)
        mf.pack(fill="x", padx=p, pady=(p, 4))

        ttk.Radiobutton(
            mf, text="Single file", variable=self._mode, value="file",
            command=self._on_mode_change,
        ).pack(side="left", padx=12)
        ttk.Radiobutton(
            mf, text="Folder (all EPUBs)", variable=self._mode, value="folder",
            command=self._on_mode_change,
        ).pack(side="left", padx=12)

        # ── I/O paths ─────────────────────────────────────────────────────────
        iof = ttk.LabelFrame(self, text="Paths", padding=6)
        iof.pack(fill="x", padx=p, pady=4)
        iof.columnconfigure(1, weight=1)

        self._input_lbl = ttk.Label(iof, text="Input file:")
        self._input_lbl.grid(row=0, column=0, sticky="w", padx=(4, 8), pady=3)
        ttk.Entry(iof, textvariable=self._input_var).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        ttk.Button(
            iof, text="Browse…", width=self.BTN_WIDTH,
            command=self._browse_input,
        ).grid(row=0, column=2, padx=(6, 0), pady=3)

        self._output_lbl = ttk.Label(iof, text="Output file:")
        self._output_lbl.grid(row=1, column=0, sticky="w", padx=(4, 8), pady=3)
        ttk.Entry(iof, textvariable=self._output_var).grid(
            row=1, column=1, sticky="ew", pady=3
        )
        ttk.Button(
            iof, text="Browse…", width=self.BTN_WIDTH,
            command=self._browse_output,
        ).grid(row=1, column=2, padx=(6, 0), pady=3)

        hint = (
            "Leave input blank to convert all EPUBs in the current folder.\n"
            "Leave output blank to place the PDF next to the source file."
        )
        ttk.Label(iof, text=hint, foreground="grey", font=("TkDefaultFont", 8)).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 2)
        )

        # ── Options ───────────────────────────────────────────────────────────
        of = ttk.LabelFrame(self, text="Options", padding=6)
        of.pack(fill="x", padx=p, pady=4)

        self._split_cb = ttk.Checkbutton(
            of,
            text="Split landscape pages into two portrait pages (auto-detected)",
            variable=self._split_var,
        )
        self._split_cb.pack(anchor="w", padx=4)
        ttk.Label(
            of,
            text=(
                "Splits any page whose width > height at the midpoint (left → page N, "
                "right → page N+1). Useful for two-page manga/comic spreads."
            ),
            foreground="grey",
            font=("TkDefaultFont", 8),
        ).pack(anchor="w", padx=24, pady=(0, 2))

        # ── Convert button ────────────────────────────────────────────────────
        self._convert_btn = ttk.Button(
            self, text="Convert to PDF",
            command=self._start_conversion,
        )
        self._convert_btn.pack(fill="x", padx=p, pady=6, ipady=6)

        # ── Progress bar ──────────────────────────────────────────────────────
        pf = ttk.Frame(self)
        pf.pack(fill="x", padx=p, pady=(0, 4))
        pf.columnconfigure(0, weight=1)

        self._pbar = ttk.Progressbar(
            pf, variable=self._progress_var, maximum=100, length=400
        )
        self._pbar.grid(row=0, column=0, sticky="ew")
        self._pct_lbl = ttk.Label(pf, text="0 %", width=6, anchor="e")
        self._pct_lbl.grid(row=0, column=1, padx=(6, 0))

        # ── Log ───────────────────────────────────────────────────────────────
        lf = ttk.LabelFrame(self, text="Log", padding=6)
        lf.pack(fill="both", expand=True, padx=p, pady=(0, p))

        self._log = scrolledtext.ScrolledText(
            lf, state="disabled", height=12,
            font=("Consolas", 9), wrap="word",
        )
        self._log.pack(fill="both", expand=True)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(
            self, textvariable=self._status_var,
            relief="sunken", anchor="w", padding=(4, 1),
        ).pack(fill="x", side="bottom")

    def _center_window(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    # ── Mode helpers ──────────────────────────────────────────────────────────

    def _on_mode_change(self) -> None:
        if self._mode.get() == "file":
            self._input_lbl.config(text="Input file:")
            self._output_lbl.config(text="Output file:")
        else:
            self._input_lbl.config(text="Input folder:")
            self._output_lbl.config(text="Output folder:")
        self._input_var.set("")
        self._output_var.set("")

    # ── Browse callbacks ──────────────────────────────────────────────────────

    def _browse_input(self) -> None:
        if self._mode.get() == "file":
            path = filedialog.askopenfilename(
                title="Select EPUB file",
                filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askdirectory(title="Select input folder")
        if path:
            self._input_var.set(path)
            # Auto-fill output only if currently empty
            if not self._output_var.get().strip():
                p = Path(path)
                if self._mode.get() == "file":
                    self._output_var.set(str(p.with_suffix(".pdf")))
                # folder mode: leave output blank → same folder

    def _browse_output(self) -> None:
        if self._mode.get() == "file":
            path = filedialog.asksaveasfilename(
                title="Save PDF as",
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._output_var.set(path)

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log_append(self, text: str) -> None:
        self._log.config(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _log_clear(self) -> None:
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    def _set_progress(self, pct: float) -> None:
        self._progress_var.set(pct)
        self._pct_lbl.config(text=f"{int(pct)} %")

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)

    # ── Conversion ────────────────────────────────────────────────────────────

    def _start_conversion(self) -> None:
        if self._converting:
            return

        self._log_clear()
        self._set_progress(0)
        self._convert_btn.config(state="disabled")
        self._converting = True

        mode = self._mode.get()
        inp = self._input_var.get().strip()
        out = self._output_var.get().strip() or None

        # No input → scan current directory
        if not inp:
            inp = "."
            mode = "folder"

        def _progress(msg: str, pct: int) -> None:
            self.after(0, self._log_append, f"[{pct:3d}%] {msg}")
            self.after(0, self._set_progress, pct)
            self.after(0, self._set_status, msg)

        do_split = self._split_var.get()

        def _run() -> None:
            try:
                if mode == "folder" or os.path.isdir(inp):
                    results = convert_folder(inp, out, _progress, split_landscape=do_split)
                    if not results:
                        self.after(0, self._log_append, "No .epub files found.")
                        self.after(0, self._set_status, "No EPUBs found.")
                    else:
                        for epub_f, ok, info in results:
                            tick = "✓" if ok else "✗"
                            self.after(
                                0,
                                self._log_append,
                                f"{tick}  {Path(epub_f).name}  →  {info}",
                            )
                        ok_count = sum(1 for _, ok, _ in results if ok)
                        self.after(
                            0, self._set_status,
                            f"Done — {ok_count}/{len(results)} converted.",
                        )
                else:
                    out_path = out or str(Path(inp).with_suffix(".pdf"))
                    convert_file(inp, out_path, _progress, split_landscape=do_split)
                    self.after(0, self._set_status, f"Done → {out_path}")
            except Exception as exc:
                self.after(0, self._log_append, f"ERROR: {exc}")
                self.after(0, self._set_status, f"Error: {exc}")
            finally:
                self.after(0, self._finish_conversion)

        threading.Thread(target=_run, daemon=True).start()

    def _finish_conversion(self) -> None:
        self._converting = False
        self._convert_btn.config(state="normal")
        self._set_progress(100)


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

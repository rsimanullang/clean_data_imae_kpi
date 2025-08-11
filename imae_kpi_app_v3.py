# imae_kpi_app_v3.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime
import traceback
import pandas as pd

APP_TITLE = "IMAE - KPI"
HEADER_ROW_EXCEL = 8  # header at Excel row 8 (1-based)

TARGET_CELL_KEYS = [
    "eNodeB Function Name",
    "Local Cell ID",
    "Cell Name",
    "eNodeB ID",
    "Cell FDD TDD indication",
]

# ---------------- Data cleaning helpers ----------------

def log_df_shape(meta, df, stage):
    meta[f"{stage}_rows"] = len(df)
    meta[f"{stage}_cols"] = len(df.columns)

def read_csv_robust(path, skiprows, header):
    """Try several encodings & delimiters; return (df, meta)."""
    encodings = ["utf-8-sig", "utf-8", "latin1"]
    seps = [None, ",", ";", "\t", "|"]  # None = auto-detect
    last_err = None
    for enc in encodings:
        for sep in seps:
            try:
                df = pd.read_csv(
                    path,
                    skiprows=skiprows,
                    header=header,
                    dtype=str,
                    sep=sep,
                    engine="python",   # needed for sep=None (auto)
                    encoding=enc,
                    quotechar='"',
                )
                meta = {"encoding": enc, "sep": "auto" if sep is None else sep}
                return df, meta
            except Exception as e:
                last_err = e
                continue
    raise last_err

def clean_headers(df):
    df.columns = (
        pd.Index(df.columns.astype(str))
        .str.replace(r"[\t\n\r]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    return df

def trim_strings(df):
    obj_cols = df.select_dtypes(include="object").columns
    if len(obj_cols) > 0:
        df[obj_cols] = df[obj_cols].apply(
            lambda s: s.str.replace(r"\s{2,}", " ", regex=True).str.strip()
        )
    return df

def replace_nil(df):
    return df.replace(r"(?i)^\s*nil\s*$", pd.NA, regex=True)

def split_start_time(df):
    """Split Start Time -> Date, Hour. Returns (df, found: bool)."""
    start_col = next((c for c in df.columns if c.lower().strip() == "start time"), None)
    if start_col is None:
        return df, False
    s = df[start_col].astype("string").str.replace(r"\s{2,}", " ", regex=True).str.strip()
    dt = pd.to_datetime(s, errors="coerce")  # robust enough for '7/13/2025  12:00:00 AM'
    df["Date"] = dt.dt.date.astype("string")
    df["Hour"] = dt.dt.hour
    # Put Date/Hour/Start Time first
    front = [c for c in ["Date", "Hour", start_col] if c in df.columns]
    df = df[front + [c for c in df.columns if c not in set(front)]]
    return df, True

def extract_selected_from_cell(df):
    """Pull specific keys from 'Cell' column; drop original 'Cell'."""
    cell_col = next((c for c in df.columns if c.lower().strip() == "cell"), None)
    if cell_col is None:
        return df, False

    rows = []
    for raw in df[cell_col].fillna(""):
        kv = {k: pd.NA for k in TARGET_CELL_KEYS}
        # Split on commas between pairs
        parts = [p.strip() for p in str(raw).split(",")]
        for part in parts:
            if "=" in part:
                key, val = part.split("=", 1)
                key = key.strip()
                if key in kv:
                    kv[key] = val.strip()
        rows.append(kv)

    parsed = pd.DataFrame(rows, columns=TARGET_CELL_KEYS)
    df = pd.concat([df.drop(columns=[cell_col]), parsed], axis=1)
    return df, True

def process_file(path: Path):
    """Return (cleaned_df, meta dict) with detailed info for logging."""
    meta = {"file": path.name}
    skip = HEADER_ROW_EXCEL - 1

    df, read_meta = read_csv_robust(path, skiprows=skip, header=0)
    meta.update(read_meta)
    log_df_shape(meta, df, "read")

    df = clean_headers(df);              log_df_shape(meta, df, "after_headers")
    df = trim_strings(df);               log_df_shape(meta, df, "after_trim")
    df = replace_nil(df);                log_df_shape(meta, df, "after_nil")

    df, start_found = split_start_time(df)
    meta["start_time_found"] = start_found
    log_df_shape(meta, df, "after_starttime")

    df, cell_found = extract_selected_from_cell(df)
    meta["cell_extracted"] = cell_found
    log_df_shape(meta, df, "after_cell")

    return df, meta

# ---------------- GUI App ----------------

class KPIApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x460")
        self.minsize(720, 420)

        self.selected_files = ()
        self.combine_name_var = tk.StringVar(value="combined_clean.csv")
        self.outdir_var = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)

        title = ttk.Label(root, text=APP_TITLE, font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w", pady=(0, 12))

        # Row 1: choose files
        row1 = ttk.Frame(root); row1.pack(fill="x", pady=6)
        self.files_entry = ttk.Entry(row1)
        self.files_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row1, text="find and choose files", command=self.choose_files).pack(side="left")
        ttk.Button(row1, text="OK", width=6, command=self.validate_files).pack(side="left", padx=(8, 0))

        # Row 2: combined file name
        row2 = ttk.Frame(root); row2.pack(fill="x", pady=6)
        self.name_entry = ttk.Entry(row2, textvariable=self.combine_name_var)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row2, text="files name after combine", command=lambda: self.name_entry.focus_set()).pack(side="left")
        ttk.Button(row2, text="OK", width=6, command=self.validate_name).pack(side="left", padx=(8, 0))

        # Row 3: output folder (optional)
        row3 = ttk.Frame(root); row3.pack(fill="x", pady=6)
        self.outdir_entry = ttk.Entry(row3, textvariable=self.outdir_var)
        self.outdir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row3, text="choose output folder (optional)", command=self.choose_output_dir).pack(side="left")

        # Status (with scrollbar)
        ttk.Label(root, text="status:").pack(anchor="w", pady=(10, 4))
        status_frame = ttk.Frame(root); status_frame.pack(fill="both", expand=True)
        self.status = tk.Text(status_frame, height=12, wrap="word")
        self.status_scroll = ttk.Scrollbar(status_frame, orient="vertical", command=self.status.yview)
        self.status.configure(yscrollcommand=self.status_scroll.set)
        self.status.pack(side="left", fill="both", expand=True)
        self.status_scroll.pack(side="right", fill="y")
        self.status.configure(state="disabled")

        # Footer buttons
        footer = ttk.Frame(root); footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="okay", command=self.run).pack(side="left")  # <- renamed
        ttk.Button(footer, text="cancel", command=self.destroy).pack(side="right")

    # ---- UI Helpers ----
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.status.configure(state="normal")
        self.status.insert("end", f"[{ts}] {msg}\n")
        self.status.see("end")
        self.status.configure(state="disabled")
        self.update_idletasks()

    def choose_files(self):
        files = filedialog.askopenfilenames(
            title="Select CSV files to clean and combine",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if files:
            self.selected_files = files
            self.files_entry.delete(0, "end")
            self.files_entry.insert(0, f"{len(files)} file(s) selected")
            self.log(f"Selected {len(files)} file(s).")

    def validate_files(self):
        if not self.selected_files:
            messagebox.showwarning(APP_TITLE, "Please choose at least one CSV file.")
        else:
            messagebox.showinfo(APP_TITLE, f"{len(self.selected_files)} file(s) ready.")

    def validate_name(self):
        name = self.combine_name_var.get().strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "Please enter a file name for the combined CSV.")
            return
        if not name.lower().endswith(".csv"):
            self.combine_name_var.set(name + ".csv")
        messagebox.showinfo(APP_TITLE, f"Combined file name set to: {self.combine_name_var.get()}")

    def choose_output_dir(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.outdir_var.set(d)
            self.log(f"Output folder set: {d}")

    # ---- Main run ----
    def run(self):
        try:
            if not self.selected_files:
                messagebox.showwarning(APP_TITLE, "Please choose CSV files first.")
                return

            name = (self.combine_name_var.get().strip() or "combined_clean.csv")
            if not name.lower().endswith(".csv"):
                name += ".csv"

            out_dir = Path(self.outdir_var.get()) if self.outdir_var.get().strip() else Path(self.selected_files[0]).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            combined_path = out_dir / name

            self.log("=== Job started ===")
            self.log(f"Output folder: {out_dir}")
            self.log(f"Combined filename: {combined_path.name}")

            cleaned_frames = []
            total_in = total_out = 0

            for f in self.selected_files:
                p = Path(f)
                self.log(f"Processing: {p}")
                try:
                    df, meta = process_file(p)
                    self.log(f"  Read using encoding={meta['encoding']}, sep={meta['sep']}")
                    self.log(f"  Shape after read: {meta['read_rows']} rows x {meta['read_cols']} cols")
                    self.log(f"  Start Time found: {meta['start_time_found']}  |  Cell extracted: {meta['cell_extracted']}")
                    self.log(f"  Shape after clean: {meta['after_cell_rows']} rows x {meta['after_cell_cols']} cols")

                    # Save per-file cleaned output next to the source
                    per_file_out = p.with_name(p.stem + "_clean.csv")
                    df.to_csv(per_file_out, index=False)
                    self.log(f"  Saved: {per_file_out.name}")

                    total_in += meta["read_rows"]
                    total_out += meta["after_cell_rows"]

                    # keep for combined
                    df2 = df.copy()
                    df2.insert(0, "_source_file", p.name)
                    cleaned_frames.append(df2)
                except Exception as e:
                    self.log(f"  ERROR in {p.name}: {e}")
                    self.log(traceback.format_exc())

            if cleaned_frames:
                self.log("Combining cleaned data ...")
                combined = pd.concat(cleaned_frames, ignore_index=True, sort=True)
                cols = ["_source_file"] + [c for c in combined.columns if c != "_source_file"]
                combined = combined[cols]
                combined.to_csv(combined_path, index=False)
                self.log(f"Combined rows: {len(combined)} | Columns: {len(combined.columns)}")
                self.log(f"Totals — rows in: {total_in}, rows out: {total_out}")
                self.log(f"Combined file saved: {combined_path}")
                self.log("=== Job finished successfully ===")
                messagebox.showinfo(APP_TITLE, f"Done!\nCombined file:\n{combined_path}")
            else:
                self.log("No cleaned data to combine.")
                messagebox.showwarning(APP_TITLE, "No cleaned data to combine.")
        except Exception as e:
            self.log(f"FATAL: {e}")
            self.log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, f"Unexpected error:\n{e}")

if __name__ == "__main__":
    try:
        app = KPIApp()
        app.mainloop()
    except ImportError as e:
        print("Missing package:", e)
        print("Install with: pip install pandas")

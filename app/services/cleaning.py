"""
Logic data cleaning — porting dari repo data-clean-be (main.py) ke bentuk
service yang bisa dipanggil router, konsisten dengan pola donasi_classifier.py.

Perubahan dari versi asli:
- `pd.to_datetime(..., infer_datetime_format=True)` dihapus — parameter ini
  sudah tidak ada lagi di pandas 3.x (akan error kalau tetap dipakai).
  pandas modern sudah infer format otomatis tanpa flag ini, jadi cukup
  hapus argumennya, perilakunya tetap sama.
- Fungsi dipecah jadi murni: terima/kembalikan DataFrame + log, tidak baca
  file atau bikin HTTP response langsung (itu tanggung jawab router).
"""

from __future__ import annotations

import json
import re
from typing import Optional

import pandas as pd

# Nama-nama kolom yang kemungkinan besar berisi timestamp
DATETIME_HINTS = [
    "time", "timestamp", "date", "datetime", "waktu", "tanggal",
    "created", "updated", "modified", "at", "recorded", "logged",
]

# Tujuan tool ini adalah mengambil data dengan status ini saja — selalu
# diterapkan, tidak bergantung pada filter_column/filter_values yang user
# kirim. Cek kedua kemungkinan nama kolom karena normalize_col_names bisa
# mengubah "State" jadi "state" sebelum langkah ini jalan.
TARGET_STATE_VALUES = ["Checkout", "Expired"]
STATE_COLUMN_CANDIDATES = ["State", "state"]


def normalize_column_name(col: str) -> str:
    """Ubah nama kolom menjadi snake_case standar."""
    s = col.strip()
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    s = re.sub(r"[\s\-.]+", "_", s)
    s = re.sub(r"[^\w]", "_", s)
    s = s.lower()
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "col"


def apply_normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """
    Terapkan normalize_column_name ke semua kolom.
    Kembalikan (df_baru, rename_log) — rename_log: [{before, after}].
    Tangani tabrakan nama dengan suffix _2, _3, dst.
    """
    seen: dict[str, int] = {}
    rename_map: dict[str, str] = {}
    log: list[dict] = []

    for col in df.columns:
        new = normalize_column_name(col)
        if new in seen:
            seen[new] += 1
            new = f"{new}_{seen[new]}"
        else:
            seen[new] = 1
        rename_map[col] = new
        if col != new:
            log.append({"before": col, "after": new})

    return df.rename(columns=rename_map), log


def detect_datetime_columns(df: pd.DataFrame) -> list[dict]:
    """
    Deteksi kolom yang berisi data waktu/timestamp.
    Kembalikan list of {name, sample, resolution} — resolution: 'second' | 'minute' | 'date'
    """
    datetime_cols = []
    for col in df.columns:
        series = df[col]

        if pd.api.types.is_datetime64_any_dtype(series):
            parsed = series
        else:
            if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
                continue
            try:
                parsed = pd.to_datetime(series, errors="raise")
            except Exception:
                continue

        has_time = parsed.dropna().apply(
            lambda x: x.hour != 0 or x.minute != 0 or x.second != 0
        ).any()
        has_second = parsed.dropna().apply(lambda x: x.second != 0).any()
        resolution = "second" if has_second else ("minute" if has_time else "date")
        sample = str(parsed.dropna().iloc[0]) if not parsed.dropna().empty else ""

        datetime_cols.append({"name": col, "sample": sample, "resolution": resolution})

    def hint_score(col_info):
        name_lower = col_info["name"].lower()
        return any(hint in name_lower for hint in DATETIME_HINTS)

    datetime_cols.sort(key=hint_score, reverse=True)
    return datetime_cols


def analyze_dataframe(df: pd.DataFrame) -> dict:
    """Info kolom, tipe data, nilai unik, kolom datetime, preview normalisasi nama kolom."""
    columns_info = []
    for col in df.columns:
        col_info = {
            "name": col,
            "dtype": str(df[col].dtype),
            "null_count": int(df[col].isnull().sum()),
            "unique_count": int(df[col].nunique()),
        }
        if df[col].nunique() <= 50:
            col_info["unique_values"] = [str(v) for v in df[col].dropna().unique().tolist()]
        columns_info.append(col_info)

    datetime_columns = detect_datetime_columns(df)
    _, normalize_log = apply_normalize_columns(df)

    return {
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "duplicate_rows": int(df.duplicated().sum()),
        "columns": columns_info,
        "datetime_columns": datetime_columns,
        "normalize_preview": normalize_log,
        "preview": df.head(5).fillna("").to_dict(orient="records"),
    }


def clean_dataframe(
    df: pd.DataFrame,
    normalize_col_names: bool = False,
    remove_duplicates: bool = False,
    dedup_time_column: Optional[str] = None,
    dedup_subset: Optional[str] = None,
    remove_nulls: bool = False,
    filter_column: Optional[str] = None,
    filter_values: Optional[str] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Terapkan langkah-langkah cleaning sesuai flag yang di-passing.
    Kembalikan (df_bersih, steps_log).
    """
    steps_log: list[str] = []

    # ── 1. Normalisasi nama kolom (PERTAMA, agar referensi kolom lain pakai nama baru) ──
    if normalize_col_names:
        df, rename_log = apply_normalize_columns(df)
        changed = len(rename_log)
        if changed:
            examples = ", ".join(f'"{r["before"]}" -> "{r["after"]}"' for r in rename_log[:3])
            suffix = f" (contoh: {examples}{'...' if changed > 3 else ''})"
            steps_log.append(f"Normalisasi nama kolom: {changed} kolom diubah{suffix}")
        else:
            steps_log.append("Normalisasi nama kolom: semua nama sudah snake_case")

        rename_map = {r["before"]: r["after"] for r in rename_log}
        if dedup_time_column and dedup_time_column in rename_map:
            dedup_time_column = rename_map[dedup_time_column]
        if dedup_subset:
            old_subset = json.loads(dedup_subset)
            dedup_subset = json.dumps([rename_map.get(c, c) for c in old_subset])
        if filter_column and filter_column in rename_map:
            filter_column = rename_map[filter_column]

    # ── 2. Hapus duplikat ──
    if remove_duplicates:
        before = len(df)
        if dedup_time_column and dedup_time_column in df.columns:
            df[dedup_time_column] = pd.to_datetime(df[dedup_time_column], errors="coerce")

            if dedup_subset:
                subset_cols = json.loads(dedup_subset)
                subset_cols = [c for c in subset_cols if c in df.columns and c != dedup_time_column]
            else:
                subset_cols = [c for c in df.columns if c != dedup_time_column]

            if "State" in df.columns:
                df["_is_paid"] = df["State"].astype(str).str.lower().eq("paid")
            else:
                df["_is_paid"] = False

            df = df.sort_values(by=["_is_paid", dedup_time_column], ascending=[False, False])
            df = df.drop_duplicates(subset=subset_cols if subset_cols else None, keep="first")
            df = df.drop(columns=["_is_paid"], errors="ignore")
            df = df.sort_values(dedup_time_column, ascending=True).reset_index(drop=True)

            removed = before - len(df)
            steps_log.append(f"Hapus duplikat (keep terbaru via '{dedup_time_column}'): {removed} baris dihapus")
        else:
            df = df.drop_duplicates()
            removed = before - len(df)
            steps_log.append(f"Hapus duplikat: {removed} baris dihapus")

    # ── 3. Hapus baris kosong ──
    if remove_nulls:
        before = len(df)
        df = df.dropna()
        removed = before - len(df)
        steps_log.append(f"Hapus baris kosong: {removed} baris dihapus")

    # ── 4. Filter status tetap: Checkout & Expired (selalu jalan, ini tujuan tool) ──
    state_col = next((c for c in STATE_COLUMN_CANDIDATES if c in df.columns), None)
    if state_col:
        before = len(df)
        df = df[df[state_col].astype(str).isin(TARGET_STATE_VALUES)]
        removed = before - len(df)
        steps_log.append(
            f"Filter status tetap ('{state_col}' = {TARGET_STATE_VALUES}): {removed} baris dihapus"
        )
    else:
        steps_log.append(
            f"Filter status tetap dilewati: kolom status ({'/'.join(STATE_COLUMN_CANDIDATES)}) tidak ditemukan"
        )

    # ── 5. Filter tambahan berdasarkan kategori (opsional, dari user) ──
    if filter_column and filter_values:
        values = json.loads(filter_values)
        if values:
            before = len(df)
            df = df[df[filter_column].astype(str).isin([str(v) for v in values])]
            removed = before - len(df)
            steps_log.append(f"Filter '{filter_column}': tersisa {len(df)} baris ({removed} dihapus)")

    return df, steps_log

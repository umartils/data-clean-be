"""
Logic pencocokan data hasil cleaning (data A) dengan data mutasi bank (data B).

Urutan pengecekan per baris data A:
  1. Cek NAMA dulu (kata utuh dari nama A ditemukan di kolom Keterangan B).
  2. Lalu cek NOMINAL dengan tingkatan berikut:

  Tier 1 - Nama cocok + nominal sama persis.
  Tier 2 - Nama cocok + nominal beda di 3-4 digit terakhir (kode unik),
           mis. 101.443 vs 100.334.
  Tier 3 - Nama cocok + salah satu nominal bulat, satunya ada kode unik,
           mis. 101.221 vs 100.000 (user salah input nominal transfer).
  Tier 4 - Nama TIDAK cocok, tapi nominal sama persis -> tetap diambil.
           (Nominal "mirip" tanpa nama TIDAK diambil, kecuali
           ALLOW_FUZZY_WITHOUT_NAME = True -> Tier 5.)

Satu mutasi hanya boleh dipakai SATU kali, tapi satu baris data A boleh
memakai banyak mutasi (mis. "Hamba Allah"): semua mutasi yang cocok
ditampilkan, 1 baris per mutasi, lengkap dengan kolom "Jenis Kecocokan".
"""

from __future__ import annotations

import io
import math
import re
from typing import Optional

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

# ---------------------------------------------------------------- konfigurasi
MIN_NAME_TOKEN_LENGTH = 3

# "any" = cukup SALAH SATU kata nama ditemukan (sesuai docstring lama,
#         "Herlina Ino" cocok dengan "HERLINA").
# "all" = SEMUA kata nama harus ditemukan.
NAME_MATCH_MODE = "any"

# Jumlah digit terakhir yang dianggap kode unik. 4 sudah mencakup kasus 3 digit.
UNIQUE_CODE_DIGITS = 4
# Nominal dianggap "bulat" jika kelipatan ini (100.000, 150.000, dst).
ROUND_UNIT = 1000
# Nominal di bawah ini tidak dipakai untuk pencocokan fuzzy (hindari
# 5.000 vs 8.000 dianggap sama karena 4 digit terakhir diabaikan).
MIN_FUZZY_NOMINAL = 10_000
# Nominal mirip tanpa nama cocok: default tidak diambil.
ALLOW_FUZZY_WITHOUT_NAME = False

# (tier, nama_cocok, jenis_nominal) -> label
TIER_LABELS = {
    1: "Nama cocok + nominal sama persis",
    2: "Nama cocok + nominal beda kode unik (3-4 digit terakhir)",
    3: "Nama cocok + nominal bulat vs kode unik",
    4: "Nama tidak cocok, nominal sama persis",
    5: "Nama tidak cocok, nominal mirip (kode unik)",
}


# ------------------------------------------------------------------- helpers
def _parse_jumlah(raw) -> Optional[float]:
    """
    Ubah nilai nominal jadi float. Menerima angka (int/float), atau teks
    seperti "200,052.00 CR" / "100000". Return None kalau kosong/NaN/tidak valid.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw) if math.isfinite(raw) else None
    s = str(raw).strip()
    s = re.sub(r"\b(CR|DR)\b", "", s, flags=re.IGNORECASE).strip()
    s = s.replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _normalize_text(s) -> str:
    if not isinstance(s, str):
        return ""
    return s.strip().lower()


def _tokenize_name(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    return [w for w in words if len(w) >= MIN_NAME_TOKEN_LENGTH]


def _name_matches_keterangan(name_tokens: list[str], keterangan_norm: str) -> bool:
    if not name_tokens:
        return False
    hits = (re.search(rf"\b{re.escape(w)}\b", keterangan_norm) for w in name_tokens)
    return any(hits) if NAME_MATCH_MODE == "any" else all(hits)


def _classify_nominal(a: Optional[float], b: Optional[float]) -> Optional[str]:
    """
    Bandingkan dua nominal. Return:
      "identik"            - sama persis
      "kode_unik"          - beda hanya di 3-4 digit terakhir (keduanya bukan bulat)
      "bulat_vs_kode_unik" - satu bulat, satunya punya kode unik
      None                 - tidak cocok
    """
    if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)):
        return None
    if abs(a - b) < 0.005:
        return "identik"

    ai, bi = int(round(a)), int(round(b))
    if min(ai, bi) < MIN_FUZZY_NOMINAL:
        return None

    base = 10 ** UNIQUE_CODE_DIGITS
    if ai // base != bi // base:
        return None

    a_round = ai % ROUND_UNIT == 0
    b_round = bi % ROUND_UNIT == 0
    if a_round and b_round:
        # dua nominal bulat berbeda (100.000 vs 105.000) = donasi berbeda
        return None
    if a_round != b_round:
        return "bulat_vs_kode_unik"
    return "kode_unik"


def _determine_tier(name_ok: bool, nominal_kind: Optional[str]) -> Optional[int]:
    if nominal_kind is None:
        return None  # nama saja tanpa nominal yang cocok -> tidak diambil
    if name_ok:
        return {"identik": 1, "kode_unik": 2, "bulat_vs_kode_unik": 3}[nominal_kind]
    if nominal_kind == "identik":
        return 4
    if ALLOW_FUZZY_WITHOUT_NAME:
        return 5
    return None


# ---------------------------------------------------------------- pencocokan
def match_transaksi_dengan_mutasi(
    df_transaksi: pd.DataFrame,
    df_mutasi: pd.DataFrame,
    nominal_column: str,
    nama_column: str,
    mutasi_keterangan_column: str = "Keterangan",
    mutasi_jumlah_column: str = "Jumlah",
) -> pd.DataFrame:
    """
    Bangun DataFrame hasil pencocokan.

    - Satu baris mutasi HANYA boleh dipakai satu kali (tidak dobel).
    - Satu baris data A BOLEH dipakai banyak mutasi: tiap mutasi yang cocok
      menjadi 1 baris hasil (data A di-explode, kolom aslinya sama persis).
    - Kalau satu mutasi jadi kandidat beberapa baris A, mutasi itu diberikan
      ke pasangan terbaik: tier terkecil, lalu selisih nominal terkecil,
      lalu urutan baris A paling awal.
    - Baris A tanpa mutasi sama sekali tetap 1 baris, status Tidak Cocok.
    """
    checks = [
        (nominal_column, df_transaksi, "data hasil cleaning (kolom nominal)"),
        (nama_column, df_transaksi, "data hasil cleaning (kolom nama)"),
        (mutasi_keterangan_column, df_mutasi, "data mutasi bank (kolom keterangan)"),
        (mutasi_jumlah_column, df_mutasi, "data mutasi bank (kolom jumlah)"),
    ]
    for col, df, label in checks:
        if col not in df.columns:
            raise ValueError(f"Kolom '{col}' tidak ditemukan di {label}. Kolom yang ada: {list(df.columns)}")

    mutasi_records = [
        {
            "nominal": _parse_jumlah(mrow[mutasi_jumlah_column]),
            "keterangan_raw": mrow[mutasi_keterangan_column],
            "jumlah_raw": mrow[mutasi_jumlah_column],
            "keterangan_norm": _normalize_text(mrow[mutasi_keterangan_column]),
        }
        for _, mrow in df_mutasi.iterrows()
    ]

    # 1) Kumpulkan semua pasangan (baris A, mutasi) yang memenuhi aturan.
    a_rows = [row for _, row in df_transaksi.iterrows()]
    candidates: list[tuple] = []  # (tier, |selisih|, a_pos, m_idx, selisih)
    for a_pos, row in enumerate(a_rows):
        nominal_val = _parse_jumlah(row[nominal_column])
        name_tokens = _tokenize_name(_normalize_text(row[nama_column]))

        for m_idx, m in enumerate(mutasi_records):
            name_ok = _name_matches_keterangan(name_tokens, m["keterangan_norm"])
            kind = _classify_nominal(nominal_val, m["nominal"])
            tier = _determine_tier(name_ok, kind)
            if tier is None:
                continue
            selisih = m["nominal"] - nominal_val
            candidates.append((tier, abs(selisih), a_pos, m_idx, selisih))

    # 2) Alokasi: pasangan terbaik dulu; satu mutasi hanya untuk satu baris A.
    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    used_mutasi: set[int] = set()
    assigned: dict[int, list[tuple]] = {}
    for tier, _, a_pos, m_idx, selisih in candidates:
        if m_idx in used_mutasi:
            continue
        used_mutasi.add(m_idx)
        assigned.setdefault(a_pos, []).append((tier, m_idx, selisih))

    # 3) Bangun output sesuai urutan data A; 1 baris per mutasi.
    original_columns = list(df_transaksi.columns)
    output_rows: list[dict] = []
    for a_pos, row in enumerate(a_rows):
        base = row.to_dict()
        matches = sorted(assigned.get(a_pos, []), key=lambda x: (x[0], x[1]))

        if matches:
            for tier, m_idx, selisih in matches:
                m = mutasi_records[m_idx]
                new_row = dict(base)
                new_row["Status Pencocokan"] = "Cocok"
                new_row["Jenis Kecocokan"] = TIER_LABELS[tier]
                new_row["Mutasi - Keterangan"] = m["keterangan_raw"]
                new_row["Mutasi - Jumlah"] = m["jumlah_raw"]
                new_row["Selisih Nominal"] = selisih
                output_rows.append(new_row)
        else:
            new_row = dict(base)
            new_row["Status Pencocokan"] = "Tidak Cocok"
            new_row["Jenis Kecocokan"] = ""
            new_row["Mutasi - Keterangan"] = ""
            new_row["Mutasi - Jumlah"] = ""
            new_row["Selisih Nominal"] = ""
            output_rows.append(new_row)

    result_columns = [
        *original_columns,
        "Status Pencocokan",
        "Jenis Kecocokan",
        "Mutasi - Keterangan",
        "Mutasi - Jumlah",
        "Selisih Nominal",
    ]
    return pd.DataFrame(output_rows, columns=result_columns)


# -------------------------------------------------------------------- export
def _style_header(ws) -> None:
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value is not None else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 4


def build_matching_workbook(df_matched_all: pd.DataFrame) -> bytes:
    """xlsx 3 sheet: 'Data Hasil Cleaning', 'Cocok', 'Tidak Cocok'."""
    cocok = df_matched_all[df_matched_all["Status Pencocokan"] == "Cocok"]
    tidak_cocok = df_matched_all[df_matched_all["Status Pencocokan"] == "Tidak Cocok"]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_matched_all.to_excel(writer, sheet_name="Data Hasil Cleaning", index=False)
        cocok.to_excel(writer, sheet_name="Cocok", index=False)
        tidak_cocok.to_excel(writer, sheet_name="Tidak Cocok", index=False)
    buffer.seek(0)

    wb = load_workbook(buffer)
    for sheet_name in ["Data Hasil Cleaning", "Cocok", "Tidak Cocok"]:
        _style_header(wb[sheet_name])

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()
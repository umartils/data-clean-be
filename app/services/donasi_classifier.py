"""
Logic klasifikasi donasi — porting dari notebook prototype ke bentuk
yang bisa dipanggil sebagai service oleh endpoint FastAPI.

Perbedaan dari notebook:
- Nama kolom (Keterangan/Transaksi/Program) jadi parameter, bukan konstanta
  fixed, supaya endpoint bisa dipakai untuk struktur data yang sedikit beda.
- Tidak lagi read/write ke file .xlsx secara langsung di sini — fungsi ini
  murni terima DataFrame, kembalikan DataFrame. Baca file & bikin response
  jadi tanggung jawab router (io.py / routers/sorting.py).
"""

from __future__ import annotations

import pandas as pd

from app.services.donasi_config import (
    KEYWORD_CATEGORIES,
    KEYWORD_EXCLUDES,
    NOMINAL_KECIL_BATAS,
    NOMINAL_BIG_DEAL_BATAS,
)


def classify_by_keyword(keterangan: str) -> str | None:
    if not isinstance(keterangan, str):
        return None
    teks = keterangan.lower()
    for kategori, keywords in KEYWORD_CATEGORIES.items():
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in teks:
                continue
            excludes = KEYWORD_EXCLUDES.get(kw_lower, [])
            if any(exc.lower() in teks for exc in excludes):
                continue
            return kategori
    return None


def classify_by_program(program: str | None) -> str | None:
    if not isinstance(program, str):
        return None
    if program.strip() == "Pembangunan Masjid":
        return "Masjid"
    return None


def _nominal_group_label(nominal, kecil_label: str, sedang_label: str, besar_label: str, invalid_label: str) -> str:
    try:
        nominal = float(nominal)
    except (TypeError, ValueError):
        return invalid_label
    if nominal < NOMINAL_KECIL_BATAS:
        return kecil_label
    if nominal > NOMINAL_BIG_DEAL_BATAS:
        return besar_label
    return sedang_label


def classify_by_nominal(nominal) -> str:
    """Label kategori fallback kalau tidak ada keyword/program yang cocok."""
    return _nominal_group_label(
        nominal,
        kecil_label="Infaq Umum (<100rb)",
        sedang_label="Infaq Umum (100rb-10jt)",
        besar_label="Big Deal (>10jt)",
        invalid_label="Nominal Tidak Valid",
    )


def classify_nominal_group(nominal) -> str:
    """Label kelompok nominal saja (dipakai sebagai kolom terpisah)."""
    return _nominal_group_label(
        nominal,
        kecil_label="(<100rb)",
        sedang_label="(100rb-10jt)",
        besar_label="(>10jt)",
        invalid_label="Nominal Tidak Valid",
    )


def classify_dataframe(
    df: pd.DataFrame,
    col_keterangan: str,
    col_nominal: str,
    col_program: str,
) -> pd.DataFrame:
    """
    Tambahkan kolom 'Kategori' dan 'Kelompok Nominal' ke df.

    Prioritas: program spesifik > keyword > fallback nominal — kecuali
    nominalnya "Big Deal" (>10jt), yang selalu menang supaya donasi besar
    tetap kelihatan terpisah walau keterangannya cocok kategori lain.
    """
    for col in (col_keterangan, col_nominal, col_program):
        if col not in df.columns:
            raise ValueError(f"Kolom '{col}' tidak ditemukan di data. Kolom yang ada: {list(df.columns)}")

    def classify_row(row):
        hasil_program = classify_by_program(row[col_program])
        hasil_keyword = classify_by_keyword(row[col_keterangan])
        is_big_deal = classify_by_nominal(row[col_nominal]) == "Big Deal (>10jt)"

        if hasil_program is not None and not is_big_deal:
            kategori = hasil_program
        elif hasil_keyword is not None and not is_big_deal:
            kategori = hasil_keyword
        else:
            kategori = classify_by_nominal(row[col_nominal])
            if kategori == "Nominal Tidak Valid":
                kategori = "Infaq Umum"

        kelompok_nominal = classify_nominal_group(row[col_nominal])
        return pd.Series([kategori, kelompok_nominal])

    result = df.copy()
    result[["Kategori", "Kelompok Nominal"]] = result.apply(classify_row, axis=1)
    return result

"""
Konfigurasi klasifikasi donasi.

Dipisah dari logic (classifier.py) supaya kategori/keyword bisa diubah
tanpa perlu sentuh kode. Ke depan, ini bisa dipindah ke DB/JSON file
kalau mau diedit lewat UI admin.
"""

KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "BYOND": ["bangun masjid pelosok negeri"],
    "Palestina": ["palestina", "palestine", "palestin", "gaza", "pal estina", "pales"],
    "Zakat Maal": ["zakat", "zakat fitrah", "zakat mal", "zakat maal"],
    "JMN": ["jelajah masjid nusantara", "jelajah masjid", "jmn"],
    "Bencana": ["korban", "bencana", "aceh", "sumatra", "sumatera"],
    "Air": [
        "air bersih", "sumber air", "bantuan air",
        "alirkan air", "kekeringan", "sumur masjid", "sumur",
    ],
    "Masjid": [
        "masjid", "mesjid", "bangun", "mas jid", "wakaf", "waqaf", "donasi masjid",
        "pembangunan masjid", "pembangunan mesjid", "infaq masjid", "shodaqoh masjid",
        "bangun masjid", "sedekah masjid", "infaq masjid", "sarana masjid", "untuk masjid",
        "donasi u masjid", "u/ masjid", "pemb", "bangun masjid", "masjidpelosok",
        "masjid pelosok", "masjid pedesaan",
    ],
}

KEYWORD_EXCLUDES: dict[str, list[str]] = {
    "masjid": ["yayasan masjid nusantara", "yayasan masjid", "yayasan masjid nusa", "masjid nusantara"],
    "aceh": ["bank", "bank aceh syariah"]
}

NOMINAL_KECIL_BATAS = 100_000
NOMINAL_BIG_DEAL_BATAS = 10_000_000

# Nama kolom default di file sumber. Bisa dioverride lewat request kalau
# struktur kolom lembaga lain beda.
DEFAULT_COL_KETERANGAN = "Keterangan"
DEFAULT_COL_NOMINAL = "Transaksi"
DEFAULT_COL_PROGRAM = "Program"

from __future__ import annotations

import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.services.matching import build_matching_workbook, match_transaksi_dengan_mutasi
from app.services.spreadsheet_io import read_uploaded_file

router = APIRouter(prefix="/api/matching", tags=["matching"])


@router.post("/cocokkan-mutasi")
async def cocokkan_mutasi(
    file_transaksi: UploadFile = File(..., description="File hasil cleaning (csv/xlsx)"),
    file_mutasi: UploadFile = File(..., description="File mutasi bank (csv)"),
    nominal_column: str = Form(...),
    nama_column: str = Form(...),
    mutasi_keterangan_column: str = Form("Description"),
    mutasi_jumlah_column: str = Form("Credit"),
    mutasi_csv_delimiter: str = Form(","),
    mutasi_csv_header_row: int = Form(0),
):
    try:
        raw_transaksi = await file_transaksi.read()
        df_transaksi = read_uploaded_file(
            io.BytesIO(raw_transaksi),
            filename=file_transaksi.filename or "",
            csv_delimiter=";",
            csv_header_row=0,
        )

        raw_mutasi = await file_mutasi.read()
        df_mutasi = read_uploaded_file(
            io.BytesIO(raw_mutasi),
            filename=file_mutasi.filename or "",
            csv_delimiter=mutasi_csv_delimiter,
            csv_header_row=mutasi_csv_header_row,
        )

        df_result = match_transaksi_dengan_mutasi(
            df_transaksi,
            df_mutasi,
            nominal_column=nominal_column,
            nama_column=nama_column,
            mutasi_keterangan_column=mutasi_keterangan_column,
            mutasi_jumlah_column=mutasi_jumlah_column,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    workbook_bytes = build_matching_workbook(df_result)
    jumlah_cocok = int((df_result["Status Pencocokan"] == "Cocok").sum())
    jumlah_tidak_cocok = int((df_result["Status Pencocokan"] == "Tidak Cocok").sum())

    return StreamingResponse(
        io.BytesIO(workbook_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="hasil_pencocokan_mutasi.xlsx"',
            "X-Matched-Count": str(jumlah_cocok),
            "X-Unmatched-Count": str(jumlah_tidak_cocok),
        },
    )
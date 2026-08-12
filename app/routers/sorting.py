from __future__ import annotations

import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.services.donasi_classifier import classify_dataframe
from app.services.donasi_config import (
    DEFAULT_COL_KETERANGAN,
    DEFAULT_COL_NOMINAL,
    DEFAULT_COL_PROGRAM,
)
from app.services.spreadsheet_io import build_classified_workbook, read_uploaded_file

router = APIRouter(prefix="/api/sorting", tags=["sorting"])


@router.post("/klasifikasi-donasi")
async def klasifikasi_donasi(
    file: UploadFile = File(..., description="File .csv/.xls/.xlsx data transaksi"),
    col_keterangan: str = Form(DEFAULT_COL_KETERANGAN),
    col_nominal: str = Form(DEFAULT_COL_NOMINAL),
    col_program: str = Form(DEFAULT_COL_PROGRAM),
    csv_delimiter: str = Form(";"),
    csv_header_row: int = Form(0),
):
    """
    Upload file transaksi donasi -> hasil klasifikasi per kategori,
    dikembalikan sebagai satu file .xlsx (multi-sheet) untuk didownload.
    """
    raw = await file.read()
    try:
        df_original = read_uploaded_file(
            io.BytesIO(raw),
            filename=file.filename or "",
            csv_delimiter=csv_delimiter,
            csv_header_row=csv_header_row,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        df_classified = classify_dataframe(
            df_original,
            col_keterangan=col_keterangan,
            col_nominal=col_nominal,
            col_program=col_program,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbook_bytes = build_classified_workbook(df_original, df_classified)

    out_name = f"donatur_scrapt_result_{(file.filename or 'data').rsplit('.', 1)[0]}.xlsx"
    return StreamingResponse(
        io.BytesIO(workbook_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )

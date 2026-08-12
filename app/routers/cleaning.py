from __future__ import annotations

import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from typing import Optional

from app.services.cleaning import analyze_dataframe, clean_dataframe
from app.services.spreadsheet_io import read_uploaded_file

# Tanpa prefix tambahan — path dibuat sama persis dengan repo data-clean-be
# asli (/api/analyze, /api/clean) supaya frontend data-clean-fe bisa
# langsung diarahkan ke backend gabungan ini tanpa ubah kode frontend,
# tinggal ganti NEXT_PUBLIC_API_URL.
router = APIRouter(prefix="/api", tags=["cleaning"])


@router.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    """Analisis file dan kembalikan info kolom, tipe data, dan nilai unik."""
    try:
        raw = await file.read()
        df = read_uploaded_file(
            io.BytesIO(raw),
            filename=file.filename or "",
            csv_delimiter=",",
            csv_header_row=0,
        )
        return analyze_dataframe(df)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/clean")
async def clean_file(
    file: UploadFile = File(...),
    normalize_col_names: bool = Form(False),
    remove_duplicates: bool = Form(False),
    dedup_time_column: Optional[str] = Form(None),
    dedup_subset: Optional[str] = Form(None),
    remove_nulls: bool = Form(False),
    filter_column: Optional[str] = Form(None),
    filter_values: Optional[str] = Form(None),
    output_format: str = Form("csv"),
):
    """Bersihkan file dan kembalikan hasilnya sebagai file download."""
    try:
        raw = await file.read()
        df = read_uploaded_file(
            io.BytesIO(raw),
            filename=file.filename or "",
            csv_delimiter=",",
            csv_header_row=0,
        )
        original_rows = len(df)

        df_clean, steps_log = clean_dataframe(
            df,
            normalize_col_names=normalize_col_names,
            remove_duplicates=remove_duplicates,
            dedup_time_column=dedup_time_column,
            dedup_subset=dedup_subset,
            remove_nulls=remove_nulls,
            filter_column=filter_column,
            filter_values=filter_values,
        )

        input_filename = file.filename or "data"
        input_filename = input_filename.rsplit(".", 1)[0] if "." in input_filename else input_filename

        output = io.BytesIO()
        if output_format == "xlsx":
            df_clean.to_excel(output, index=False, engine="openpyxl")
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"{input_filename}_cleaned.xlsx"
        else:
            df_clean.to_csv(output, index=False)
            media_type = "text/csv"
            filename = f"{input_filename}_cleaned.csv"
        output.seek(0)

        import json as _json

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Original-Rows": str(original_rows),
            "X-Final-Rows": str(len(df_clean)),
            "X-Steps-Log": _json.dumps(steps_log),
        }
        return StreamingResponse(output, media_type=media_type, headers=headers)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import cleaning, sorting

app = FastAPI(title="Lembaga CSV Tools API")

# Sesuaikan allow_origins ke domain frontend Next.js kamu waktu deploy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # X-Original-Rows dkk dipakai frontend data-clean-fe untuk nampilin
    # ringkasan hasil cleaning (jumlah baris sebelum/sesudah, log langkah)
    expose_headers=["Content-Disposition", "X-Original-Rows", "X-Final-Rows", "X-Steps-Log"],
)

app.include_router(sorting.router)
app.include_router(cleaning.router)


@app.get("/health")
def health():
    return {"status": "ok"}

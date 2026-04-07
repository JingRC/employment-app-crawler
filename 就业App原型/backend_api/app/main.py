from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.core.database import init_database

app = FastAPI(title=settings.app_name)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix="/api")

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@app.on_event("startup")
def startup_event() -> None:
    init_database()


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

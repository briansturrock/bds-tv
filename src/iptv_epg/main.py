from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .db import get_status, init_db
from .settings import ensure_runtime_dirs


app = FastAPI(title="iptv_epg", version=__version__)


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs()
    init_db()


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "app": "iptv_epg",
        "version": __version__,
        "message": "running",
    }


@app.get("/api/status")
def api_status() -> dict:
    status = get_status()
    return {
        "ok": True,
        "app": "iptv_epg",
        "version": __version__,
        **status,
    }

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(tags=["epg-product"])
STATIC_DIR = Path(__file__).parent / "static"


@router.get("/epg", response_model=None)
def epg_management_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "epg.html", media_type="text/html")

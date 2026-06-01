from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(prefix="/dev", tags=["epgshare-review"])
STATIC_DIR = Path(__file__).parent / "static"


@router.get("/epgshare-matching", response_model=None)
def epgshare_matching_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "epgshare_matching.html", media_type="text/html")

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query

from .db import create_job, update_job
from .epgshare import epgshare_matches, epgshare_status, import_epgshare_index, search_epgshare


router = APIRouter(prefix="/api/epgshare", tags=["epgshare"])
executor = ThreadPoolExecutor(max_workers=1)


def _run_index_job(job_id: str) -> None:
    try:
        result = import_epgshare_index(job_id=job_id)
        update_job(
            job_id,
            status="complete",
            message=(
                f"Imported EPGShare index: "
                f"{result['channel_source_row_count']:,} channel/source rows, "
                f"{result['source_count']:,} sources"
            ),
            progress_current=int(result["channel_source_row_count"]),
            progress_total=int(result["channel_source_row_count"]),
            finish=True,
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            message="EPGShare index import failed",
            error=str(exc),
            finish=True,
        )


@router.post("/index")
def api_epgshare_index() -> dict:
    job_id = str(uuid.uuid4())
    create_job(job_id, "epgshare_index", "Queued EPGShare index import")
    executor.submit(_run_index_job, job_id)
    return {"ok": True, "job_id": job_id, "message": "EPGShare index import job started"}


@router.get("/status")
def api_epgshare_status() -> dict:
    return epgshare_status()


@router.get("/search")
def api_epgshare_search(q: str = Query("", min_length=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return {"ok": True, "query": q, "results": search_epgshare(q=q, limit=limit)}


@router.get("/matches")
def api_epgshare_matches() -> dict:
    return epgshare_matches()

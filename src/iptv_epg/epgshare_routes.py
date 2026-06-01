from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .db import create_job, update_job
from .epgshare import epgshare_mapping_review, epgshare_matches, epgshare_saved_mappings, epgshare_status, generate_filtered_epgshare, import_epgshare_index, save_epgshare_mappings, search_epgshare


router = APIRouter(prefix="/api/epgshare", tags=["epgshare"])
executor = ThreadPoolExecutor(max_workers=1)


class EpgshareMappingIn(BaseModel):
    channel_id: str
    xmltv_id: str | None = None
    source_key: str | None = None
    mapping_type: str = "manual"
    confidence: float | None = None
    ignored: bool = False
    notes: str | None = None


class EpgshareMappingsIn(BaseModel):
    mappings: list[EpgshareMappingIn] = Field(default_factory=list)


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


@router.get("/mapping-review")
def api_epgshare_mapping_review() -> dict:
    return epgshare_mapping_review()


@router.get("/mappings")
def api_epgshare_mappings() -> dict:
    return {"ok": True, "mappings": epgshare_saved_mappings()}


@router.post("/mappings")
def api_save_epgshare_mappings(payload: EpgshareMappingsIn) -> dict:
    return save_epgshare_mappings([item.model_dump() for item in payload.mappings])


def _run_generate_filtered_job(job_id: str, days: int) -> None:
    try:
        result = generate_filtered_epgshare(job_id=job_id, days=days)
        update_job(
            job_id,
            status="complete",
            message=(
                f"Generated EPGShare filtered EPG with "
                f"{result['channel_count']} channels and {result['programme_count']} programmes"
            ),
            progress_current=int(result["source_count"]),
            progress_total=int(result["source_count"]),
            finish=True,
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            message="EPGShare filtered EPG generation failed",
            error=str(exc),
            finish=True,
        )


@router.post("/generate-filtered")
def api_generate_filtered_epgshare(days: int = Query(3, ge=1, le=14)) -> dict:
    job_id = str(uuid.uuid4())
    create_job(job_id, "epgshare_filtered_epg", "Queued EPGShare filtered EPG generation")
    executor.submit(_run_generate_filtered_job, job_id, days)
    return {
        "ok": True,
        "job_id": job_id,
        "message": "EPGShare filtered EPG generation job started",
        "days": days,
    }

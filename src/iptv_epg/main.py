from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .db import (
    connect,
    create_job,
    get_channels,
    get_groups,
    get_job,
    get_selected_channels,
    get_setting,
    get_status,
    init_db,
    row_to_dict,
    set_channels_selected,
    set_group_selected,
    set_setting,
    update_job,
)
from .m3u import fetch_and_index_m3u, generate_filtered_m3u
from .settings import FILTERED_M3U, ensure_runtime_dirs


app = FastAPI(title="iptv_epg", version=__version__)
executor = ThreadPoolExecutor(max_workers=2)


class SettingsIn(BaseModel):
    m3u_url: str | None = Field(default=None)


class SettingsOut(BaseModel):
    m3u_url: str | None = None


class ChannelSelectionIn(BaseModel):
    channel_ids: list[str] = Field(default_factory=list)
    selected: bool = True


class GroupSelectionIn(BaseModel):
    selected: bool = True


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
    return get_status(__version__)


@app.get("/api/settings", response_model=SettingsOut)
def api_get_settings() -> SettingsOut:
    return SettingsOut(m3u_url=get_setting("m3u_url"))


@app.post("/api/settings", response_model=SettingsOut)
def api_set_settings(payload: SettingsIn) -> SettingsOut:
    if payload.m3u_url is not None:
        set_setting("m3u_url", payload.m3u_url.strip())
    return SettingsOut(m3u_url=get_setting("m3u_url"))


def run_m3u_fetch_job(job_id: str, url: str) -> None:
    try:
        fetch_and_index_m3u(url, job_id)
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                "UPDATE m3u_sources SET last_error = ? WHERE id = 1",
                (str(exc),),
            )
            conn.commit()
        update_job(
            job_id,
            status="failed",
            message="M3U fetch/index failed",
            error=str(exc),
            finish=True,
        )


@app.post("/api/m3u/fetch")
def api_fetch_m3u() -> dict:
    url = get_setting("m3u_url")
    if not url:
        raise HTTPException(status_code=400, detail="m3u_url is not configured")

    job_id = str(uuid.uuid4())
    create_job(job_id, "m3u_fetch", "Queued M3U fetch/index")
    executor.submit(run_m3u_fetch_job, job_id, url)

    return {
        "ok": True,
        "job_id": job_id,
        "message": "M3U fetch/index job started",
    }


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job}


@app.get("/api/source")
def api_source() -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM m3u_sources WHERE id = 1"
        ).fetchone()
    return {"ok": True, "source": row_to_dict(row)}


@app.get("/api/groups")
def api_groups() -> dict:
    return {
        "ok": True,
        "groups": get_groups(),
    }


@app.get("/api/channels")
def api_channels(
    group_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    return {
        "ok": True,
        **get_channels(group_id=group_id, offset=offset, limit=limit),
    }


@app.get("/api/selected-channels")
def api_selected_channels() -> dict:
    return {
        "ok": True,
        "channels": get_selected_channels(),
    }


@app.post("/api/channels/select")
def api_select_channels(payload: ChannelSelectionIn) -> dict:
    result = set_channels_selected(payload.channel_ids, payload.selected)
    return {
        "ok": True,
        **result,
    }


@app.post("/api/groups/{group_id}/select")
def api_select_group(group_id: str, payload: GroupSelectionIn) -> dict:
    result = set_group_selected(group_id, payload.selected)
    return {
        "ok": True,
        "group_id": group_id,
        **result,
    }


def run_filtered_m3u_job(job_id: str) -> None:
    try:
        result = generate_filtered_m3u(job_id)
        update_job(
            job_id,
            status="complete",
            message=f"Generated filtered.m3u with {result['selected_count']:,} channels",
            progress_current=int(result["selected_count"]),
            progress_total=int(result["selected_count"]),
            finish=True,
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            message="Filtered M3U generation failed",
            error=str(exc),
            finish=True,
        )


@app.post("/api/m3u/generate-filtered")
def api_generate_filtered_m3u() -> dict:
    job_id = str(uuid.uuid4())
    create_job(job_id, "filtered_m3u", "Queued filtered M3U generation")
    executor.submit(run_filtered_m3u_job, job_id)

    return {
        "ok": True,
        "job_id": job_id,
        "message": "Filtered M3U generation job started",
    }


@app.get("/filtered.m3u")
def filtered_m3u() -> FileResponse | PlainTextResponse:
    if not FILTERED_M3U.exists():
        return PlainTextResponse("#EXTM3U\n", media_type="application/vnd.apple.mpegurl")
    return FileResponse(
        FILTERED_M3U,
        media_type="application/vnd.apple.mpegurl",
        filename="filtered.m3u",
    )

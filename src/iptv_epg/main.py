from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__
from .db import (
    connect,
    create_job,
    get_channels,
    get_groups,
    get_job,
    get_setting,
    get_status,
    init_db,
    row_to_dict,
    set_setting,
    update_job,
)
from .m3u import fetch_and_index_m3u
from .settings import ensure_runtime_dirs


app = FastAPI(title="iptv_epg", version=__version__)
executor = ThreadPoolExecutor(max_workers=2)


class SettingsIn(BaseModel):
    m3u_url: str | None = Field(default=None)


class SettingsOut(BaseModel):
    m3u_url: str | None = None


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs()
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "app": "iptv_epg", "version": __version__, "message": "running"}


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
            conn.execute("UPDATE m3u_sources SET last_error = ? WHERE id = 1", (str(exc),))
            conn.commit()
        update_job(job_id, status="failed", message="M3U fetch/index failed", error=str(exc), finish=True)


@app.post("/api/m3u/fetch")
def api_fetch_m3u() -> dict:
    url = get_setting("m3u_url")
    if not url:
        raise HTTPException(status_code=400, detail="m3u_url is not configured")
    job_id = str(uuid.uuid4())
    create_job(job_id, "m3u_fetch", "Queued M3U fetch/index")
    executor.submit(run_m3u_fetch_job, job_id, url)
    return {"ok": True, "job_id": job_id, "message": "M3U fetch/index job started"}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job}


@app.get("/api/source")
def api_source() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM m3u_sources WHERE id = 1").fetchone()
    return {"ok": True, "source": row_to_dict(row)}


@app.get("/api/groups")
def api_groups() -> dict:
    return {"ok": True, "groups": get_groups()}


@app.get("/api/channels")
def api_channels(
    group_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    return {"ok": True, **get_channels(group_id=group_id, offset=offset, limit=limit)}

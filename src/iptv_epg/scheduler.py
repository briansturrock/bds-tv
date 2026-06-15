from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connect, create_job, get_job, get_setting, set_setting, update_job
from .epgshare import generate_filtered_epgshare


router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])
executor = ThreadPoolExecutor(max_workers=1)

DEFAULT_DAYS = 3
DEFAULT_TIME = "04:00"
CHECK_SECONDS = 60

_started = False
_start_lock = threading.Lock()


class SchedulerSettingsIn(BaseModel):
    enabled: bool = False
    days: int = Field(default=DEFAULT_DAYS, ge=1, le=14)
    run_time: str = Field(default=DEFAULT_TIME, pattern=r"^\d{2}:\d{2}$")


def _bool_setting(key: str, default: bool = False) -> bool:
    value = get_setting(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_setting(key: str, default: int, minimum: int, maximum: int) -> int:
    value = get_setting(key)
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _time_setting(key: str, default: str = DEFAULT_TIME) -> str:
    value = (get_setting(key) or default).strip()
    if _parse_run_time(value) is None:
        return default
    return value


def _parse_run_time(value: str) -> tuple[int, int] | None:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def scheduler_settings() -> dict[str, Any]:
    return {
        "enabled": _bool_setting("scheduler_enabled", False),
        "days": _int_setting("scheduler_days", DEFAULT_DAYS, 1, 14),
        "run_time": _time_setting("scheduler_run_time", DEFAULT_TIME),
        "last_run_date": get_setting("scheduler_last_run_date"),
        "last_job_id": get_setting("scheduler_last_job_id"),
        "last_started_at": get_setting("scheduler_last_started_at"),
    }


def _running_scheduler_job() -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM jobs
            WHERE job_type IN ('scheduled_epg', 'epgshare_filtered_epg')
              AND status = 'running'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
    return row is not None


def _run_scheduled_epg_job(job_id: str, days: int, scheduled: bool) -> None:
    try:
        result = generate_filtered_epgshare(job_id=job_id, days=days)
        update_job(
            job_id,
            status="complete",
            message=(
                f"Generated scheduled EPG with "
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
            message="Scheduled EPG generation failed",
            error=str(exc),
            finish=True,
        )


def start_scheduler_job(days: int, scheduled: bool = False) -> str:
    if _running_scheduler_job():
        raise RuntimeError("A scheduled EPG job is already running")

    job_id = str(uuid.uuid4())
    create_job(job_id, "scheduled_epg", "Queued scheduled EPG generation")
    set_setting("scheduler_last_job_id", job_id)
    set_setting("scheduler_last_started_at", datetime.now().isoformat(timespec="seconds"))
    if scheduled:
        set_setting("scheduler_last_run_date", datetime.now().date().isoformat())
    executor.submit(_run_scheduled_epg_job, job_id, days, scheduled)
    return job_id


def scheduler_snapshot() -> dict[str, Any]:
    settings = scheduler_settings()
    last_job = get_job(settings["last_job_id"]) if settings.get("last_job_id") else None
    return {
        "ok": True,
        **settings,
        "last_job": last_job,
    }


@router.get("")
def api_get_scheduler() -> dict[str, Any]:
    return scheduler_snapshot()


@router.post("")
def api_save_scheduler(payload: SchedulerSettingsIn) -> dict[str, Any]:
    if _parse_run_time(payload.run_time) is None:
        raise HTTPException(status_code=400, detail="Run time must be HH:MM")

    set_setting("scheduler_enabled", "1" if payload.enabled else "0")
    set_setting("scheduler_days", str(payload.days))
    set_setting("scheduler_run_time", payload.run_time)
    return scheduler_snapshot()


@router.post("/run-now")
def api_scheduler_run_now() -> dict[str, Any]:
    settings = scheduler_settings()
    try:
        job_id = start_scheduler_job(days=int(settings["days"]), scheduled=False)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "job_id": job_id, "message": "Scheduled EPG generation job started"}


def scheduler_loop() -> None:
    while True:
        try:
            settings = scheduler_settings()
            if settings["enabled"]:
                run_time = _parse_run_time(settings["run_time"])
                now = datetime.now()
                today = now.date().isoformat()

                if (
                    run_time
                    and settings.get("last_run_date") != today
                    and (now.hour, now.minute) >= run_time
                    and not _running_scheduler_job()
                ):
                    start_scheduler_job(days=int(settings["days"]), scheduled=True)
        except Exception:
            pass

        time.sleep(CHECK_SECONDS)


def start_scheduler_thread() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        thread = threading.Thread(target=scheduler_loop, name="iptv_epg_scheduler", daemon=True)
        thread.start()
        _started = True

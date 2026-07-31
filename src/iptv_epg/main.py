from __future__ import annotations

import os
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
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
    set_channel_order,
    set_channel_preferred_logo,
    set_channels_selected,
    set_group_order,
    set_group_selected,
    set_setting,
    update_job,
)
from .diagnostics_routes import router as diagnostics_router
from .dlna import router as dlna_router
from .epgshare_routes import router as epgshare_router
from .epgshare_review_routes import router as epgshare_review_router
from .guide_routes import router as guide_router
from .hdhr import active_status, router as hdhr_router, start_ssdp_service, start_stream_safety_service, stop_ssdp_service
from .m3u import fetch_and_index_m3u, generate_filtered_m3u, import_m3u_file
from .scheduler import router as scheduler_router, start_scheduler_thread
from .settings import readable_filtered_epg, readable_filtered_m3u, ensure_runtime_dirs
from .stream_safety import (
    cached_public_ip,
    enforce_stream_killswitch,
    get_killswitch_settings,
    save_killswitch_settings,
    stream_killswitch_status,
)
from .tv_app import router as tv_app_router


app = FastAPI(title="bds-tv", version=__version__)

HLS_ROOT = Path("/tmp/iptv_epg_hls")
HLS_PROCESSES: dict[str, subprocess.Popen] = {}
HLS_LOCK = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)
STARTED_AT = time.time()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(diagnostics_router)
app.include_router(dlna_router)
app.include_router(epgshare_router)
app.include_router(epgshare_review_router)
app.include_router(guide_router)
app.include_router(hdhr_router)
app.include_router(scheduler_router)
app.include_router(tv_app_router)


class SettingsIn(BaseModel):
    m3u_url: str | None = Field(default=None)
    provider_stream_limit: int = Field(default=1, ge=1, le=16)
    killswitch_enabled: bool = False
    killswitch_home_country_code: str | None = None
    sonarr_base_url: str | None = None
    sonarr_api_key: str | None = None
    sonarr_quality_profile_id: int | None = None
    sonarr_root_folder_path: str | None = None


class SettingsOut(BaseModel):
    m3u_url: str | None = None
    provider_stream_limit: int = 1
    killswitch_enabled: bool = False
    killswitch_home_country_code: str = ""
    killswitch_status: dict | None = None
    sonarr_base_url: str = ""
    sonarr_api_key: str = ""
    sonarr_quality_profile_id: int | None = None
    sonarr_root_folder_path: str = ""


class SonarrTestIn(BaseModel):
    sonarr_base_url: str | None = None
    sonarr_api_key: str | None = None


class ChannelSelectionIn(BaseModel):
    channel_ids: list[str] = Field(default_factory=list)
    selected: bool = True


class GroupSelectionIn(BaseModel):
    selected: bool = True


class GroupOrderIn(BaseModel):
    group_ids: list[str] = Field(default_factory=list)


class ChannelOrderIn(BaseModel):
    group_id: str
    channel_ids: list[str] = Field(default_factory=list)


class ChannelLogoIn(BaseModel):
    preferred_logo_url: str | None = None


def settings_payload(force_refresh_ip: bool = False) -> SettingsOut:
    killswitch = get_killswitch_settings()
    try:
        provider_stream_limit = int(get_setting("hdhr_max_upstream_streams", "1") or "1")
    except ValueError:
        provider_stream_limit = 1
    try:
        quality_profile_id = int(get_setting("sonarr_quality_profile_id", "") or "0") or None
    except ValueError:
        quality_profile_id = None
    return SettingsOut(
        m3u_url=get_setting("m3u_url"),
        provider_stream_limit=max(1, min(provider_stream_limit, 16)),
        killswitch_enabled=bool(killswitch["enabled"]),
        killswitch_home_country_code=killswitch["home_country_code"],
        killswitch_status=stream_killswitch_status(force_refresh_ip),
        sonarr_base_url=get_setting("sonarr_base_url", ""),
        sonarr_api_key=get_setting("sonarr_api_key", ""),
        sonarr_quality_profile_id=quality_profile_id,
        sonarr_root_folder_path=get_setting("sonarr_root_folder_path", ""),
    )


def normalise_sonarr_base_url(value: str | None) -> str:
    base_url = (value or "").strip().rstrip("/")
    if base_url and not re.match(r"^https?://", base_url, flags=re.IGNORECASE):
        base_url = f"http://{base_url}"
    return base_url


def sonarr_connection_status(base_url: str, api_key: str) -> dict[str, str | bool]:
    if not base_url:
        raise HTTPException(status_code=400, detail="Sonarr URL is required")
    if not api_key:
        raise HTTPException(status_code=400, detail="Sonarr API key is required")

    url = f"{base_url}/api/v3/system/status"
    request = Request(url, headers={"X-Api-Key": api_key, "Accept": "application/json"})

    try:
        with urlopen(request, timeout=10) as response:
            import json

            body = json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(status_code=exc.code, detail="Sonarr rejected the API key") from exc
        raise HTTPException(status_code=exc.code, detail=f"Sonarr returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Could not connect to Sonarr: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Timed out connecting to Sonarr") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sonarr test failed: {exc}") from exc

    version = str(body.get("version") or "")
    app_name = str(body.get("appName") or body.get("instanceName") or "Sonarr")
    return {
        "ok": True,
        "base_url": base_url,
        "app_name": app_name,
        "version": version,
        "message": f"Connected to {app_name}{(' ' + version) if version else ''}",
    }


def sonarr_api_get(path: str, params: dict[str, str] | None = None) -> object:
    base_url = normalise_sonarr_base_url(get_setting("sonarr_base_url", ""))
    api_key = get_setting("sonarr_api_key", "")
    if not base_url:
        raise HTTPException(status_code=400, detail="Sonarr URL is not configured")
    if not api_key:
        raise HTTPException(status_code=400, detail="Sonarr API key is not configured")

    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{base_url}{path}{query}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )

    try:
        with urlopen(request, timeout=20) as response:
            import json

            return json.loads(response.read().decode("utf-8") or "null")
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(status_code=exc.code, detail="Sonarr rejected the API key") from exc
        raise HTTPException(status_code=exc.code, detail=f"Sonarr returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Could not connect to Sonarr: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Timed out connecting to Sonarr") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sonarr request failed: {exc}") from exc


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs()
    init_db()
    start_ssdp_service()
    start_stream_safety_service()
    start_scheduler_thread()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_all_hls_processes()
    stop_ssdp_service()


@app.get("/", response_model=None)
def index() -> Response:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/tv", response_model=None)
def tv_index() -> Response:
    return FileResponse(STATIC_DIR / "tv.html", media_type="text/html")


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "app": "bds-tv",
        "version": __version__,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "message": "running",
    }


@app.get("/health/deep")
async def health_deep() -> dict:
    return {
        "ok": True,
        "app": "bds-tv",
        "version": __version__,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "threads": [thread.name for thread in threading.enumerate()],
        "proxy": active_status(),
    }


@app.get("/api/status")
def api_status() -> dict:
    return get_status(__version__)


@app.get("/api/public-ip")
def api_public_ip(refresh: bool = Query(False)) -> dict:
    return cached_public_ip(refresh)


@app.get("/api/settings", response_model=SettingsOut)
def api_get_settings(refresh_ip: bool = Query(False)) -> SettingsOut:
    return settings_payload(refresh_ip)


@app.post("/api/settings", response_model=SettingsOut)
def api_set_settings(payload: SettingsIn) -> SettingsOut:
    if payload.m3u_url is not None:
        set_setting("m3u_url", payload.m3u_url.strip())
    if payload.sonarr_base_url is not None:
        set_setting("sonarr_base_url", normalise_sonarr_base_url(payload.sonarr_base_url))
    if payload.sonarr_api_key is not None:
        set_setting("sonarr_api_key", payload.sonarr_api_key.strip())
    if payload.sonarr_quality_profile_id is not None:
        set_setting("sonarr_quality_profile_id", str(max(0, payload.sonarr_quality_profile_id)))
    if payload.sonarr_root_folder_path is not None:
        set_setting("sonarr_root_folder_path", payload.sonarr_root_folder_path.strip())
    set_setting("hdhr_max_upstream_streams", str(max(1, min(payload.provider_stream_limit, 16))))
    save_killswitch_settings(payload.killswitch_enabled, payload.killswitch_home_country_code)
    return settings_payload(force_refresh_ip=True)


@app.post("/api/settings/sonarr/test")
def api_test_sonarr(payload: SonarrTestIn) -> dict[str, str | bool]:
    base_url = normalise_sonarr_base_url(payload.sonarr_base_url) or get_setting("sonarr_base_url", "")
    api_key = (payload.sonarr_api_key or "").strip() or get_setting("sonarr_api_key", "")
    return sonarr_connection_status(base_url, api_key)


@app.get("/api/sonarr/series/lookup")
def api_sonarr_series_lookup(term: str = Query(..., min_length=1)) -> dict[str, object]:
    clean_term = term.strip()
    if not clean_term:
        raise HTTPException(status_code=400, detail="Search term is required")
    results = sonarr_api_get("/api/v3/series/lookup", {"term": clean_term})
    if not isinstance(results, list):
        raise HTTPException(status_code=502, detail="Unexpected Sonarr lookup response")
    return {"ok": True, "term": clean_term, "results": results, "result_count": len(results)}


@app.get("/api/sonarr/quality-profiles")
def api_sonarr_quality_profiles() -> dict[str, object]:
    results = sonarr_api_get("/api/v3/qualityprofile")
    if not isinstance(results, list):
        raise HTTPException(status_code=502, detail="Unexpected Sonarr quality profile response")
    profiles = [
        {
            "id": item.get("id"),
            "name": item.get("name") or f"Profile {item.get('id')}",
        }
        for item in results
        if isinstance(item, dict) and item.get("id") is not None
    ]
    return {
        "ok": True,
        "profiles": profiles,
        "profile_count": len(profiles),
        "selected_profile_id": settings_payload().sonarr_quality_profile_id,
    }


@app.get("/api/sonarr/root-folders")
def api_sonarr_root_folders() -> dict[str, object]:
    results = sonarr_api_get("/api/v3/rootfolder")
    if not isinstance(results, list):
        raise HTTPException(status_code=502, detail="Unexpected Sonarr root folder response")
    folders = [
        {
            "id": item.get("id"),
            "path": item.get("path") or "",
            "free_space": item.get("freeSpace"),
        }
        for item in results
        if isinstance(item, dict) and item.get("path")
    ]
    return {
        "ok": True,
        "root_folders": folders,
        "root_folder_count": len(folders),
        "selected_root_folder_path": settings_payload().sonarr_root_folder_path,
    }


def run_m3u_fetch_job(job_id: str, url: str) -> None:
    try:
        fetch_and_index_m3u(url, job_id)
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE m3u_sources SET last_error = ? WHERE id = 1", (str(exc),))
            conn.commit()
        update_job(job_id, status="failed", message="M3U fetch/index failed", error=str(exc), finish=True)


def run_m3u_upload_job(job_id: str, upload_path: str, source_label: str) -> None:
    path = Path(upload_path)
    try:
        import_m3u_file(path, job_id, source_label)
    except Exception as exc:
        if path.exists():
            path.unlink(missing_ok=True)
        with connect() as conn:
            conn.execute("UPDATE m3u_sources SET last_error = ? WHERE id = 1", (str(exc),))
            conn.commit()
        update_job(job_id, status="failed", message="Uploaded M3U import failed", error=str(exc), finish=True)


@app.post("/api/m3u/fetch")
def api_fetch_m3u() -> dict:
    url = get_setting("m3u_url")
    if not url:
        raise HTTPException(status_code=400, detail="m3u_url is not configured")

    job_id = str(uuid.uuid4())
    create_job(job_id, "m3u_fetch", "Queued M3U fetch/index")
    executor.submit(run_m3u_fetch_job, job_id, url)

    return {"ok": True, "job_id": job_id, "message": "M3U fetch/index job started"}


@app.post("/api/m3u/upload")
async def api_upload_m3u(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "uploaded.m3u"
    suffix = ".m3u8" if filename.lower().endswith(".m3u8") else ".m3u"
    with tempfile.NamedTemporaryFile("wb", delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        try:
            while True:
                chunk = await file.read(1024 * 512)
                if not chunk:
                    break
                tmp.write(chunk)
        finally:
            await file.close()

    job_id = str(uuid.uuid4())
    create_job(job_id, "m3u_upload", "Queued uploaded M3U import")
    executor.submit(run_m3u_upload_job, job_id, str(tmp_path), f"uploaded:{filename}")

    return {"ok": True, "job_id": job_id, "message": "Uploaded M3U import job started"}



@app.get("/api/jobs")
def api_list_jobs(limit: int = Query(25, ge=1, le=200)) -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"ok": True, "jobs": [dict(r) for r in rows]}


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


@app.post("/api/groups/order")
def api_group_order(payload: GroupOrderIn) -> dict:
    result = set_group_order(payload.group_ids)
    return {"ok": True, **result}


@app.get("/api/channels")
def api_channels(
    group_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    return {"ok": True, **get_channels(group_id=group_id, offset=offset, limit=limit)}


@app.get("/api/selected-channels")
def api_selected_channels() -> dict:
    return {"ok": True, "channels": get_selected_channels()}


@app.get("/watch/{channel_id}", response_class=HTMLResponse)
def watch_channel(channel_id: str, mode: str = Query("copy")):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, name
            FROM channels
            WHERE id = ?
              AND selected = 1
              AND missing = 0
            """,
            (channel_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Selected channel not found")

    mode = "compatible" if mode == "compatible" else "copy"
    alternate_mode = "copy" if mode == "compatible" else "compatible"
    alternate_label = "Fast mode" if mode == "compatible" else "Compatible mode"

    channel_name = str(row["name"] or "Channel")
    safe_name = (
        channel_name
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{safe_name}</title>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js"></script>
  <style>
    html, body {{
      width: 100%;
      height: 100%;
      overflow: hidden;
    }}
    body {{
      margin: 0;
      background: #101217;
      color: #f8fafc;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      display: flex;
      flex-direction: column;
    }}
    header {{
      flex: 0 0 38px;
      height: 38px;
      box-sizing: border-box;
      padding: 6px 12px;
      background: #171b23;
      border-bottom: 1px solid #2b3240;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      overflow: hidden;
    }}
    h1 {{
      margin: 0;
      font-size: 15px;
      font-weight: 600;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }}
    main {{
      flex: 1 1 auto;
      min-height: 0;
      box-sizing: border-box;
      display: grid;
      place-items: center;
      position: relative;
      overflow: hidden;
      padding: 8px 8px 42px;
    }}
    video {{
      width: 100%;
      height: 100%;
      max-width: 100%;
      max-height: 100%;
      background: #000;
      object-fit: contain;
      display: block;
      box-sizing: border-box;
    }}
    a {{
      color: #93c5fd;
      white-space: nowrap;
    }}
    button {{
      border: 1px solid #475569;
      background: #253044;
      color: #f8fafc;
      border-radius: 6px;
      padding: 4px 8px;
      font: inherit;
      font-size: 12px;
      cursor: pointer;
      white-space: nowrap;
    }}
    button:hover {{
      border-color: #93c5fd;
      color: #93c5fd;
    }}
    .hint, #status {{
      font-size: 12px;
      color: #cbd5e1;
    }}
    .hint {{
      display: flex;
      gap: 10px;
      align-items: center;
    }}
    #status {{
      position: absolute;
      left: 14px;
      top: 14px;
      background: rgba(0, 0, 0, 0.72);
      padding: 6px 8px;
      border-radius: 6px;
      max-width: calc(100vw - 28px);
      z-index: 3;
      pointer-events: none;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_name}</h1>
    <div class="hint">
      <span>{mode}</span>
      <a href="/watch/{channel_id}?mode={alternate_mode}">{alternate_label}</a>
      <a href="/stream/{channel_id}">Raw stream</a>
      <button id="stop-preview" type="button">Stop preview</button>
    </div>
  </header>
  <main>
    <video id="player" controls playsinline preload="auto"></video>
    <div id="status">Loading stream…</div>
  </main>
  <script>
    const hlsUrl = "/hls/{channel_id}/{mode}/index.m3u8";
    const hlsStopUrl = "/api/hls/{channel_id}/{mode}/stop";
    const video = document.getElementById("player");
    const statusEl = document.getElementById("status");
    const stopButton = document.getElementById("stop-preview");
    let hls = null;
    let sawVideoFrame = false;
    let releaseStarted = false;

    function setStatus(message) {{
      statusEl.textContent = message;
    }}

    function releasePreview(useBeacon = false) {{
      if (releaseStarted) return;
      releaseStarted = true;

      if (hls) {{
        hls.destroy();
        hls = null;
      }}

      video.pause();
      video.removeAttribute("src");
      video.load();
      setStatus("Preview stopped. Provider stream released.");

      if (useBeacon && navigator.sendBeacon) {{
        navigator.sendBeacon(hlsStopUrl, new Blob([], {{ type: "text/plain" }}));
        return;
      }}

      fetch(hlsStopUrl, {{
        method: "POST",
        keepalive: true,
      }}).catch(() => {{}});
    }}

    video.addEventListener("loadedmetadata", () => {{
      if (video.videoWidth && video.videoHeight) {{
        sawVideoFrame = true;
        setStatus("Stream ready. Press play in the video controls.");
      }} else {{
        setStatus("Audio track loaded, but no video track is visible. Try Compatible mode.");
      }}
    }});

    video.addEventListener("playing", () => {{
      if (sawVideoFrame || (video.videoWidth && video.videoHeight)) {{
        setStatus("Playing.");
      }} else {{
        setStatus("Audio is playing, but no video frames are visible. Try Compatible mode.");
      }}
    }});

    video.addEventListener("timeupdate", () => {{
      if (video.videoWidth && video.videoHeight) {{
        sawVideoFrame = true;
      }}
    }});

    video.addEventListener("error", () => {{
      const err = video.error;
      setStatus("Video element error" + (err ? ` (${{err.code}})` : "") + ". Try Compatible mode.");
    }});

    video.addEventListener("pause", () => {{
      if (!releaseStarted && !video.ended) {{
        releasePreview();
      }}
    }});

    video.addEventListener("ended", () => {{
      releasePreview();
    }});

    stopButton.addEventListener("click", () => {{
      releasePreview();
    }});

    window.addEventListener("pagehide", () => {{
      releasePreview(true);
    }});

    window.addEventListener("beforeunload", () => {{
      releasePreview(true);
    }});

    document.addEventListener("visibilitychange", () => {{
      if (document.visibilityState === "hidden") {{
        releasePreview(true);
      }}
    }});

    async function startPlayer() {{
      releaseStarted = false;
      setStatus("Starting {mode} HLS stream through container…");

      if (video.canPlayType("application/vnd.apple.mpegurl")) {{
        video.src = hlsUrl;
        setStatus("Stream ready. Press play in the video controls.");
        return;
      }}

      if (!window.Hls || !Hls.isSupported()) {{
        setStatus("HLS player is not supported in this browser. Try the raw stream link.");
        return;
      }}

      hls = new Hls({{
        liveSyncDurationCount: 3,
        lowLatencyMode: false,
      }});

      hls.on(Hls.Events.ERROR, (_event, data) => {{
        if (!data.fatal) {{
          setStatus("Recovering stream: " + data.details);
          return;
        }}

        setStatus("HLS error: " + data.type + " / " + data.details + ". Try {alternate_label}.");
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {{
          hls.startLoad();
        }} else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {{
          hls.recoverMediaError();
        }}
      }});

      let manifestLoaded = false;
      hls.on(Hls.Events.MANIFEST_PARSED, () => {{
        manifestLoaded = true;
        setStatus("Stream ready. Press play in the video controls.");
      }});

      setTimeout(() => {{
        if (!manifestLoaded) {{
          setStatus("Still waiting for stream. Try {alternate_label} or refresh this tab.");
        }} else if (!sawVideoFrame) {{
          setStatus("Stream is loaded. Press play. If you only get audio, try Compatible mode.");
        }}
      }}, 15000);

      hls.loadSource(hlsUrl);
      hls.attachMedia(video);
    }}

    startPlayer().catch((err) => {{
      setStatus("Playback failed: " + err.message);
    }});
  </script>
</body>
</html>"""


def hls_key(channel_id: str, mode: str) -> str:
    return f"{mode}:{channel_id}"


def hls_channel_dir(channel_id: str, mode: str = "copy") -> Path:
    safe_channel = "".join(ch for ch in channel_id if ch.isalnum() or ch in ("-", "_"))
    safe_mode = "compatible" if mode == "compatible" else "copy"
    return HLS_ROOT / safe_mode / safe_channel


def stop_hls_process(key: str) -> None:
    with HLS_LOCK:
        proc = HLS_PROCESSES.pop(key, None)

    if not proc or proc.poll() is not None:
        return

    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            pass


def stop_other_hls_processes(active_key: str) -> None:
    with HLS_LOCK:
        keys = list(HLS_PROCESSES.keys())
    for key in keys:
        if key == active_key:
            continue
        stop_hls_process(key)


def stop_all_hls_processes() -> None:
    with HLS_LOCK:
        keys = list(HLS_PROCESSES.keys())
    for key in keys:
        stop_hls_process(key)


def selected_channel_stream_url(channel_id: str) -> tuple[str, str]:
    enforce_stream_killswitch()

    with connect() as conn:
        row = conn.execute(
            """
            SELECT name, stream_url
            FROM channels
            WHERE id = ?
              AND selected = 1
              AND missing = 0
            """,
            (channel_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Selected channel not found")

    stream_url = row["stream_url"]
    if not stream_url:
        raise HTTPException(status_code=404, detail="Channel has no stream URL")

    return str(row["name"] or "Channel"), str(stream_url)


def ffmpeg_hls_command(stream_url: str, playlist: Path, segment_pattern: str, mode: str) -> list[str]:
    common = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-user_agent",
        "VLC/3.0.0 LibVLC/3.0.0",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-fflags",
        "+genpts",
        "-i",
        stream_url,
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
    ]

    if mode == "compatible":
        codecs = [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-profile:v",
            "baseline",
            "-level",
            "3.1",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-b:a",
            "128k",
        ]
    else:
        codecs = [
            "-c",
            "copy",
        ]

    hls = [
        "-f",
        "hls",
        "-hls_time",
        "3",
        "-hls_list_size",
        "10",
        "-hls_flags",
        "delete_segments+append_list+omit_endlist+independent_segments",
        "-hls_segment_filename",
        segment_pattern,
        str(playlist),
    ]

    return common + codecs + hls


def ensure_hls_stream(channel_id: str, mode: str = "copy") -> Path:
    mode = "compatible" if mode == "compatible" else "copy"
    _name, stream_url = selected_channel_stream_url(channel_id)

    key = hls_key(channel_id, mode)
    stop_other_hls_processes(key)

    hls_dir = hls_channel_dir(channel_id, mode)
    playlist = hls_dir / "index.m3u8"

    with HLS_LOCK:
        proc = HLS_PROCESSES.get(key)
    if proc and proc.poll() is None and playlist.exists():
        return playlist

    stop_hls_process(key)

    if hls_dir.exists():
        shutil.rmtree(hls_dir, ignore_errors=True)
    hls_dir.mkdir(parents=True, exist_ok=True)

    segment_pattern = str(hls_dir / "seg_%05d.ts")
    cmd = ffmpeg_hls_command(stream_url, playlist, segment_pattern, mode)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    with HLS_LOCK:
        HLS_PROCESSES[key] = proc

    deadline = time.time() + (24 if mode == "compatible" else 12)
    while time.time() < deadline:
        with HLS_LOCK:
            proc = HLS_PROCESSES.get(key)
        if proc and proc.poll() is not None:
            break
        if playlist.exists() and playlist.stat().st_size > 0:
            return playlist
        time.sleep(0.25)

    raise HTTPException(status_code=504, detail=f"Timed out waiting for {mode} HLS stream to start")


@app.get("/hls/{channel_id}/{mode}/index.m3u8")
def hls_playlist(channel_id: str, mode: str):
    playlist = ensure_hls_stream(channel_id, mode)
    return FileResponse(
        playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/hls/{channel_id}/{mode}/{segment_name}")
def hls_segment(channel_id: str, mode: str, segment_name: str):
    if not segment_name.endswith(".ts"):
        raise HTTPException(status_code=404, detail="Segment not found")

    segment = hls_channel_dir(channel_id, mode) / segment_name
    if not segment.exists():
        raise HTTPException(status_code=404, detail="Segment not found")

    return FileResponse(
        segment,
        media_type="video/mp2t",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/hls/{channel_id}/{mode}/stop")
def api_stop_hls(channel_id: str, mode: str) -> dict:
    mode = "compatible" if mode == "compatible" else "copy"
    stop_hls_process(hls_key(channel_id, mode))
    return {"ok": True, "channel_id": channel_id, "mode": mode, "stopped": True}


@app.get("/stream/{channel_id}")
def stream_channel(channel_id: str):
    enforce_stream_killswitch()
    stop_all_hls_processes()

    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, stream_url
            FROM channels
            WHERE id = ?
              AND selected = 1
              AND missing = 0
            """,
            (channel_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Selected channel not found")

    stream_url = row["stream_url"]
    if not stream_url:
        raise HTTPException(status_code=404, detail="Channel has no stream URL")

    try:
        req = Request(
            stream_url,
            headers={
                "User-Agent": "VLC/3.0.0 LibVLC/3.0.0",
                "Accept": "*/*",
            },
        )
        upstream = urlopen(req, timeout=20)
    except HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=f"Upstream stream error: {exc.reason}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Could not open upstream stream: {exc.reason}") from exc

    content_type = upstream.headers.get("Content-Type") or "video/mp2t"

    def iter_stream():
        try:
            while True:
                chunk = upstream.read(1024 * 256)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        iter_stream(),
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/channels/select")
def api_select_channels(payload: ChannelSelectionIn) -> dict:
    result = set_channels_selected(payload.channel_ids, payload.selected)
    return {"ok": True, **result}


@app.post("/api/channels/order")
def api_channel_order(payload: ChannelOrderIn) -> dict:
    result = set_channel_order(payload.group_id, payload.channel_ids)
    return {"ok": True, **result}


@app.post("/api/channels/{channel_id}/preferred-logo")
def api_channel_preferred_logo(channel_id: str, payload: ChannelLogoIn) -> dict:
    result = set_channel_preferred_logo(channel_id, payload.preferred_logo_url)
    if not result.get("updated"):
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"ok": True, **result}


@app.post("/api/groups/{group_id}/select")
def api_select_group(group_id: str, payload: GroupSelectionIn) -> dict:
    result = set_group_selected(group_id, payload.selected)
    return {"ok": True, "group_id": group_id, **result}


def run_filtered_m3u_job(job_id: str) -> None:
    try:
        result = generate_filtered_m3u(job_id)
        update_job(
            job_id,
            status="complete",
            message=f"Generated bds-tv.m3u with {result['selected_count']:,} channels",
            progress_current=int(result["selected_count"]),
            progress_total=int(result["selected_count"]),
            finish=True,
        )
    except Exception as exc:
        update_job(job_id, status="failed", message="Filtered M3U generation failed", error=str(exc), finish=True)


@app.post("/api/m3u/generate-filtered")
def api_generate_filtered_m3u() -> dict:
    job_id = str(uuid.uuid4())
    create_job(job_id, "filtered_m3u", "Queued BDS-TV M3U generation")
    executor.submit(run_filtered_m3u_job, job_id)
    return {"ok": True, "job_id": job_id, "message": "BDS-TV M3U generation job started"}


@app.get("/bds-tv.m3u", response_model=None)
def bds_tv_m3u() -> Response:
    path = readable_filtered_m3u()
    if not path.exists():
        return PlainTextResponse("#EXTM3U\n", media_type="application/vnd.apple.mpegurl")
    return FileResponse(path, media_type="application/vnd.apple.mpegurl", filename="bds-tv.m3u")


@app.get("/bds-tv.xml", response_model=None)
def bds_tv_xml() -> Response:
    path = readable_filtered_epg()
    if not path.exists():
        return PlainTextResponse('<?xml version="1.0" encoding="UTF-8"?><tv></tv>\n', media_type="application/xml")
    return FileResponse(path, media_type="application/xml", filename="bds-tv.xml")


@app.get("/filtered.m3u", response_model=None)
def filtered_m3u() -> Response:
    path = readable_filtered_m3u()
    if not path.exists():
        return PlainTextResponse("#EXTM3U\n", media_type="application/vnd.apple.mpegurl")
    return FileResponse(path, media_type="application/vnd.apple.mpegurl", filename="filtered.m3u")


@app.get("/filtered_epg.xml", response_model=None)
def filtered_epg() -> Response:
    path = readable_filtered_epg()
    if not path.exists():
        return PlainTextResponse('<?xml version="1.0" encoding="UTF-8"?><tv></tv>\n', media_type="application/xml")
    return FileResponse(path, media_type="application/xml", filename="filtered_epg.xml")

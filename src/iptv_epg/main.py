from __future__ import annotations

import os
import signal
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query
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
from .m3u import fetch_and_index_m3u, generate_filtered_m3u
from .scheduler import router as scheduler_router, start_scheduler_thread
from .settings import FILTERED_EPG, FILTERED_M3U, ensure_runtime_dirs
from .stream_safety import (
    cached_public_ip,
    enforce_stream_killswitch,
    get_killswitch_settings,
    save_killswitch_settings,
    stream_killswitch_status,
)


app = FastAPI(title="iptv_epg", version=__version__)

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


class SettingsIn(BaseModel):
    m3u_url: str | None = Field(default=None)
    killswitch_enabled: bool = False
    killswitch_home_country_code: str | None = None


class SettingsOut(BaseModel):
    m3u_url: str | None = None
    killswitch_enabled: bool = False
    killswitch_home_country_code: str = ""
    killswitch_status: dict | None = None


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
    return SettingsOut(
        m3u_url=get_setting("m3u_url"),
        killswitch_enabled=bool(killswitch["enabled"]),
        killswitch_home_country_code=killswitch["home_country_code"],
        killswitch_status=stream_killswitch_status(force_refresh_ip),
    )


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


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "app": "iptv_epg",
        "version": __version__,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "message": "running",
    }


@app.get("/health/deep")
async def health_deep() -> dict:
    return {
        "ok": True,
        "app": "iptv_epg",
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
    save_killswitch_settings(payload.killswitch_enabled, payload.killswitch_home_country_code)
    return settings_payload(force_refresh_ip=True)


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
            message=f"Generated filtered.m3u with {result['selected_count']:,} channels",
            progress_current=int(result["selected_count"]),
            progress_total=int(result["selected_count"]),
            finish=True,
        )
    except Exception as exc:
        update_job(job_id, status="failed", message="Filtered M3U generation failed", error=str(exc), finish=True)


@app.post("/api/m3u/generate-filtered")
def api_generate_filtered_m3u() -> dict:
    job_id = str(uuid.uuid4())
    create_job(job_id, "filtered_m3u", "Queued filtered M3U generation")
    executor.submit(run_filtered_m3u_job, job_id)
    return {"ok": True, "job_id": job_id, "message": "Filtered M3U generation job started"}


@app.get("/filtered.m3u", response_model=None)
def filtered_m3u() -> Response:
    if not FILTERED_M3U.exists():
        return PlainTextResponse("#EXTM3U\n", media_type="application/vnd.apple.mpegurl")
    return FileResponse(FILTERED_M3U, media_type="application/vnd.apple.mpegurl", filename="filtered.m3u")


@app.get("/filtered_epg.xml", response_model=None)
def filtered_epg() -> Response:
    if not FILTERED_EPG.exists():
        return PlainTextResponse('<?xml version="1.0" encoding="UTF-8"?><tv></tv>\n', media_type="application/xml")
    return FileResponse(FILTERED_EPG, media_type="application/xml", filename="filtered_epg.xml")

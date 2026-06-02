from __future__ import annotations

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
from .epg import detect_epg_urls, generate_filtered_epg, scan_epg_channels
from .diagnostics_routes import router as diagnostics_router
from .epgshare_routes import router as epgshare_router
from .epgshare_review_routes import router as epgshare_review_router
from .guide_routes import router as guide_router
from .m3u import fetch_and_index_m3u, generate_filtered_m3u
from .settings import FILTERED_EPG, FILTERED_M3U, ensure_runtime_dirs


app = FastAPI(title="iptv_epg", version=__version__)
executor = ThreadPoolExecutor(max_workers=2)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(diagnostics_router)
app.include_router(epgshare_router)
app.include_router(epgshare_review_router)
app.include_router(guide_router)


class SettingsIn(BaseModel):
    m3u_url: str | None = Field(default=None)


class SettingsOut(BaseModel):
    m3u_url: str | None = None


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


class EpgSourceIn(BaseModel):
    name: str
    url: str
    enabled: bool = True
    source_type: str = "manual"


class EpgSourceEnableIn(BaseModel):
    enabled: bool = True


class EpgMappingIn(BaseModel):
    channel_id: str
    source_id: int | None = None
    xmltv_id: str | None = None
    mapping_type: str = "manual"


class EpgMappingsIn(BaseModel):
    mappings: list[EpgMappingIn] = Field(default_factory=list)


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs()
    init_db()


@app.get("/", response_model=None)
def index() -> Response:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


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
def watch_channel(channel_id: str):
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
  <script src="https://cdn.jsdelivr.net/npm/mpegts.js@1.7.3/dist/mpegts.min.js"></script>
  <style>
    body {{
      margin: 0;
      background: #101217;
      color: #f8fafc;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 10px 14px;
      background: #171b23;
      border-bottom: 1px solid #2b3240;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }}
    h1 {{
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }}
    main {{
      height: calc(100vh - 46px);
      display: grid;
      place-items: center;
      position: relative;
    }}
    video {{
      width: 100%;
      height: 100%;
      background: #000;
    }}
    a {{
      color: #93c5fd;
    }}
    .hint, #status {{
      font-size: 12px;
      color: #cbd5e1;
    }}
    #status {{
      position: absolute;
      left: 12px;
      bottom: 10px;
      background: rgba(0, 0, 0, 0.72);
      padding: 6px 8px;
      border-radius: 6px;
      max-width: calc(100vw - 24px);
      z-index: 3;
    }}
    #play-overlay {{
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      background: radial-gradient(circle at center, rgba(15, 23, 42, 0.45), rgba(0, 0, 0, 0.72));
      z-index: 2;
    }}
    #play-button {{
      border: 1px solid #93c5fd;
      background: #1d4ed8;
      color: #fff;
      border-radius: 999px;
      padding: 14px 26px;
      font-size: 18px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    }}
    #play-button:hover {{
      background: #2563eb;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_name}</h1>
    <div class="hint">
      <a href="/stream/{channel_id}">Open raw stream</a>
    </div>
  </header>
  <main>
    <video id="player" controls playsinline></video>
    <div id="play-overlay">
      <button id="play-button" type="button">▶ Play</button>
    </div>
    <div id="status">Click Play to start the stream.</div>
  </main>
  <script>
    const streamUrl = "/stream/{channel_id}";
    const video = document.getElementById("player");
    const statusEl = document.getElementById("status");
    const overlay = document.getElementById("play-overlay");
    const playButton = document.getElementById("play-button");
    let player = null;

    function setStatus(message) {{
      statusEl.textContent = message;
    }}

    function hideOverlay() {{
      overlay.style.display = "none";
    }}

    async function playVideo() {{
      try {{
        await video.play();
        hideOverlay();
        setStatus("Playing.");
      }} catch (err) {{
        overlay.style.display = "grid";
        setStatus("Click Play to start. " + err.message);
      }}
    }}

    function destroyPlayer() {{
      if (!player) return;
      try {{
        player.unload();
        player.detachMediaElement();
        player.destroy();
      }} catch (_err) {{}}
      player = null;
    }}

    async function startNative() {{
      destroyPlayer();
      setStatus("Trying browser native playback…");
      video.src = streamUrl;
      await playVideo();
    }}

    async function startMpegTs() {{
      destroyPlayer();

      if (!window.mpegts) {{
        setStatus("MPEG-TS player did not load. Trying browser native playback…");
        await startNative();
        return;
      }}

      const features = mpegts.getFeatureList ? mpegts.getFeatureList() : {{}};
      if (!features.mseLivePlayback) {{
        setStatus("MPEG-TS live playback not supported here. Trying browser native playback…");
        await startNative();
        return;
      }}

      setStatus("Starting MPEG-TS player…");
      player = mpegts.createPlayer({{
        type: "mpegts",
        isLive: true,
        url: streamUrl,
      }}, {{
        enableWorker: true,
        liveBufferLatencyChasing: true,
        stashInitialSize: 384 * 1024,
      }});

      player.on(mpegts.Events.ERROR, (type, detail) => {{
        setStatus("Player error: " + type + " / " + detail + ". Try the raw stream link or refresh.");
      }});

      player.attachMediaElement(video);
      player.load();
      await playVideo();
    }}

    playButton.addEventListener("click", () => {{
      startMpegTs().catch((err) => {{
        setStatus("Playback failed: " + err.message);
      }});
    }});
  </script>
</body>
</html>"""


@app.get("/stream/{channel_id}")
def stream_channel(channel_id: str):
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


@app.get("/api/epg/sources")
def api_epg_sources() -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM epg_sources ORDER BY id").fetchall()
    return {"ok": True, "sources": [dict(r) for r in rows]}


@app.post("/api/epg/sources")
def api_add_epg_source(payload: EpgSourceIn) -> dict:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO epg_sources(name, url, enabled, source_type)
            VALUES (?, ?, ?, ?)
            """,
            (payload.name.strip(), payload.url.strip(), 1 if payload.enabled else 0, payload.source_type),
        )
        conn.commit()
        source_id = cur.lastrowid
    return {"ok": True, "source_id": source_id}


@app.post("/api/epg/sources/{source_id}/enable")
def api_enable_epg_source(source_id: int, payload: EpgSourceEnableIn) -> dict:
    with connect() as conn:
        conn.execute("UPDATE epg_sources SET enabled = ? WHERE id = ?", (1 if payload.enabled else 0, source_id))
        conn.commit()
    return {"ok": True, "source_id": source_id, "enabled": payload.enabled}


@app.post("/api/epg/detect")
def api_detect_epg() -> dict:
    m3u_url = get_setting("m3u_url")
    detected = detect_epg_urls(m3u_url)

    created = []
    with connect() as conn:
        for item in detected:
            existing = conn.execute("SELECT id FROM epg_sources WHERE url = ?", (item["url"],)).fetchone()
            if existing:
                created.append({"source_id": existing["id"], **item, "existing": True})
                continue
            cur = conn.execute(
                """
                INSERT INTO epg_sources(name, url, enabled, source_type)
                VALUES (?, ?, 1, ?)
                """,
                (item["name"], item["url"], item["source_type"]),
            )
            created.append({"source_id": cur.lastrowid, **item, "existing": False})
        conn.commit()

    return {"ok": True, "detected": created}


def run_epg_test_job(job_id: str, source_id: int) -> None:
    try:
        with connect() as conn:
            source = conn.execute("SELECT id, url FROM epg_sources WHERE id = ?", (source_id,)).fetchone()
        if not source:
            raise RuntimeError("EPG source not found")

        result = scan_epg_channels(source_id, source["url"], job_id=job_id)
        update_job(
            job_id,
            status="complete",
            message=f"Scanned {result['epg_channel_count']:,} EPG channels; {result['match_count']:,} selected-channel matches",
            progress_current=result["epg_channel_count"],
            progress_total=result["epg_channel_count"],
            finish=True,
        )
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE epg_sources SET last_error = ? WHERE id = ?", (str(exc), source_id))
            conn.commit()
        update_job(job_id, status="failed", message="EPG test failed", error=str(exc), finish=True)


@app.post("/api/epg/test")
def api_test_epg(source_id: int | None = None) -> dict:
    if source_id is None:
        with connect() as conn:
            row = conn.execute("SELECT id FROM epg_sources WHERE enabled = 1 ORDER BY id LIMIT 1").fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="No enabled EPG source")
        source_id = int(row["id"])

    job_id = str(uuid.uuid4())
    create_job(job_id, "epg_test", "Queued EPG test")
    executor.submit(run_epg_test_job, job_id, source_id)
    return {"ok": True, "job_id": job_id, "source_id": source_id}


@app.get("/api/epg/channels/search")
def api_epg_channel_search(q: str = Query("", min_length=0), source_id: int | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
    query = f"%{q.strip()}%"
    sql = """
        SELECT source_id, xmltv_id, display_name
        FROM epg_channels
        WHERE (? IS NULL OR source_id = ?)
          AND (? = '' OR xmltv_id LIKE ? OR display_name LIKE ?)
        ORDER BY display_name
        LIMIT ?
    """
    with connect() as conn:
        rows = conn.execute(sql, (source_id, source_id, q.strip(), query, query, limit)).fetchall()
    return {"ok": True, "channels": [dict(r) for r in rows]}


@app.get("/api/epg/mappings")
def api_epg_mappings() -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                channels.id AS channel_id,
                channels.name,
                groups.name AS group_name,
                channels.tvg_id,
                channels.epg_xmltv_id,
                epg_mappings.source_id,
                epg_mappings.xmltv_id,
                epg_mappings.mapping_type
            FROM channels
            JOIN groups ON groups.id = channels.group_id
            LEFT JOIN epg_mappings ON epg_mappings.channel_id = channels.id
            WHERE channels.selected = 1
              AND channels.missing = 0
            ORDER BY
                CASE WHEN groups.user_order IS NULL THEN 1 ELSE 0 END,
                groups.user_order ASC,
                groups.provider_order ASC,
                CASE WHEN channels.user_order IS NULL THEN 1 ELSE 0 END,
                channels.user_order ASC,
                channels.provider_order ASC
            """
        ).fetchall()
    return {"ok": True, "mappings": [dict(r) for r in rows]}


@app.post("/api/epg/mappings")
def api_save_epg_mappings(payload: EpgMappingsIn) -> dict:
    with connect() as conn:
        for item in payload.mappings:
            if item.xmltv_id:
                conn.execute(
                    """
                    INSERT INTO epg_mappings(channel_id, source_id, xmltv_id, mapping_type, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        source_id = excluded.source_id,
                        xmltv_id = excluded.xmltv_id,
                        mapping_type = excluded.mapping_type,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (item.channel_id, item.source_id, item.xmltv_id, item.mapping_type),
                )
            else:
                conn.execute("DELETE FROM epg_mappings WHERE channel_id = ?", (item.channel_id,))
        conn.commit()
    return {"ok": True, "updated": len(payload.mappings)}


def run_filtered_epg_job(job_id: str, days: int, source_id: int | None) -> None:
    try:
        result = generate_filtered_epg(days=days, source_id=source_id, job_id=job_id)
        update_job(
            job_id,
            status="complete",
            message=f"Generated filtered_epg.xml: {result['channels']} channels, {result['programmes']} programmes, {result['days']} days",
            progress_current=int(result["programmes"]),
            progress_total=int(result["programmes"]),
            finish=True,
        )
    except Exception as exc:
        update_job(job_id, status="failed", message="Filtered EPG generation failed", error=str(exc), finish=True)


@app.post("/api/epg/generate-filtered")
def api_generate_filtered_epg(days: int = Query(3, ge=1, le=14), source_id: int | None = None) -> dict:
    job_id = str(uuid.uuid4())
    create_job(job_id, "filtered_epg", "Queued filtered EPG generation")
    executor.submit(run_filtered_epg_job, job_id, days, source_id)
    return {"ok": True, "job_id": job_id, "message": "Filtered EPG generation job started"}


@app.get("/filtered_epg.xml", response_model=None)
def filtered_epg() -> Response:
    if not FILTERED_EPG.exists():
        return PlainTextResponse('<?xml version="1.0" encoding="UTF-8"?><tv></tv>\n', media_type="application/xml")
    return FileResponse(FILTERED_EPG, media_type="application/xml", filename="filtered_epg.xml")

from __future__ import annotations

import secrets
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .db import connect, get_selected_channels, get_setting, set_setting
from .m3u import extinf_with_logo
from .settings import DATA_DIR, FILTERED_EPG


router = APIRouter(tags=["hdhr"])

HDHR_PROXY_M3U = DATA_DIR / "hdhr.m3u"
SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_THREAD: threading.Thread | None = None
SSDP_STOP = threading.Event()
SSDP_STATUS: dict[str, Any] = {
    "running": False,
    "listening": False,
    "last_error": None,
    "last_request_from": None,
    "last_search_target": None,
    "last_response_at": None,
    "last_notify_at": None,
}


class HdhrSettingsIn(BaseModel):
    enabled: bool = False
    device_name: str = "iptv-epg"
    device_id: str | None = None
    channel_limit: int = Field(default=450, ge=1, le=5000)
    tuner_count: int = Field(default=1, ge=1, le=16)
    max_upstream_streams: int = Field(default=1, ge=1, le=16)
    public_base_url: str = ""
    stream_mode: str = "direct"
    conflict_policy: str = "reject_new"
    ffmpeg_path: str = "ffmpeg"
    buffer_seconds: int = Field(default=30, ge=0, le=120)
    buffer_max_mb: int = Field(default=256, ge=16, le=2048)
    stream_cleanup_enabled: bool = True
    max_stream_age_minutes: int = Field(default=240, ge=1, le=1440)
    idle_timeout_seconds: int = Field(default=120, ge=0, le=3600)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=300)
    scheduled_drop_enabled: bool = False
    scheduled_drop_time: str = "04:00"


@dataclass
class HdhrSettings:
    enabled: bool
    device_name: str
    device_id: str
    channel_limit: int
    tuner_count: int
    max_upstream_streams: int
    public_base_url: str
    stream_mode: str
    conflict_policy: str
    ffmpeg_path: str
    buffer_seconds: int
    buffer_max_mb: int
    stream_cleanup_enabled: bool
    max_stream_age_minutes: int
    idle_timeout_seconds: int
    cleanup_interval_seconds: int
    scheduled_drop_enabled: bool
    scheduled_drop_time: str


@dataclass
class StreamSession:
    session_id: str
    channel_id: str
    channel_name: str
    mode: str
    started_at: float
    last_activity_at: float
    bytes_sent: int = 0
    buffer_bytes: int = 0
    buffer_target_seconds: int = 0
    upstream: Any = None
    process: subprocess.Popen | None = None


@dataclass
class BufferedChunk:
    data: bytes
    read_at: float


STREAM_LOCK = threading.Lock()
ACTIVE_STREAMS: dict[str, StreamSession] = {}
STREAM_SAFETY_THREAD: threading.Thread | None = None
STREAM_SAFETY_STOP = threading.Event()
STREAM_SAFETY_STATUS: dict[str, Any] = {
    "running": False,
    "last_cleanup_at": None,
    "last_cleanup_reason": None,
    "last_drop_at": None,
}


def bool_setting(key: str, default: bool) -> bool:
    value = get_setting(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def int_setting(key: str, default: int, min_value: int, max_value: int) -> int:
    value = get_setting(key)
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(min_value, min(parsed, max_value))


def normalise_base_url(value: str | None) -> str:
    cleaned = (value or "").strip().rstrip("/")
    return cleaned


def normalise_hhmm(value: str | None, default: str = "04:00") -> str:
    cleaned = (value or "").strip()
    try:
        hour_text, minute_text = cleaned.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return default
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return default
    return f"{hour:02d}:{minute:02d}"


def get_or_create_device_id() -> str:
    existing = (get_setting("hdhr_device_id") or "").strip()
    if existing:
        return existing

    generated = secrets.token_hex(4).upper()
    set_setting("hdhr_device_id", generated)
    return generated


def get_hdhr_settings() -> HdhrSettings:
    stream_mode = (get_setting("hdhr_stream_mode", "direct") or "direct").strip().lower()
    if stream_mode not in {"direct", "ffmpeg", "buffered"}:
        stream_mode = "direct"

    conflict_policy = (get_setting("hdhr_conflict_policy", "reject_new") or "reject_new").strip().lower()
    if conflict_policy not in {"reject_new", "stop_existing"}:
        conflict_policy = "reject_new"

    return HdhrSettings(
        enabled=bool_setting("hdhr_enabled", False),
        device_name=(get_setting("hdhr_device_name", "iptv-epg") or "iptv-epg").strip() or "iptv-epg",
        device_id=get_or_create_device_id(),
        channel_limit=int_setting("hdhr_channel_limit", 450, 1, 5000),
        tuner_count=int_setting("hdhr_tuner_count", 1, 1, 16),
        max_upstream_streams=int_setting("hdhr_max_upstream_streams", 1, 1, 16),
        public_base_url=normalise_base_url(get_setting("hdhr_public_base_url")),
        stream_mode=stream_mode,
        conflict_policy=conflict_policy,
        ffmpeg_path=(get_setting("hdhr_ffmpeg_path", "ffmpeg") or "ffmpeg").strip() or "ffmpeg",
        buffer_seconds=int_setting("hdhr_buffer_seconds", 30, 0, 120),
        buffer_max_mb=int_setting("hdhr_buffer_max_mb", 256, 16, 2048),
        stream_cleanup_enabled=bool_setting("hdhr_stream_cleanup_enabled", True),
        max_stream_age_minutes=int_setting("hdhr_max_stream_age_minutes", 240, 1, 1440),
        idle_timeout_seconds=int_setting("hdhr_idle_timeout_seconds", 120, 0, 3600),
        cleanup_interval_seconds=int_setting("hdhr_cleanup_interval_seconds", 30, 5, 300),
        scheduled_drop_enabled=bool_setting("hdhr_scheduled_drop_enabled", False),
        scheduled_drop_time=normalise_hhmm(get_setting("hdhr_scheduled_drop_time"), "04:00"),
    )


def save_hdhr_settings(payload: HdhrSettingsIn) -> HdhrSettings:
    device_id = (payload.device_id or "").strip().upper() or get_or_create_device_id()
    stream_mode = payload.stream_mode.strip().lower()
    if stream_mode not in {"direct", "ffmpeg", "buffered"}:
        stream_mode = "direct"

    conflict_policy = payload.conflict_policy.strip().lower()
    if conflict_policy not in {"reject_new", "stop_existing"}:
        conflict_policy = "reject_new"

    values = {
        "hdhr_enabled": "true" if payload.enabled else "false",
        "hdhr_device_name": payload.device_name.strip() or "iptv-epg",
        "hdhr_device_id": device_id,
        "hdhr_channel_limit": str(max(1, min(payload.channel_limit, 5000))),
        "hdhr_tuner_count": str(max(1, min(payload.tuner_count, 16))),
        "hdhr_max_upstream_streams": str(max(1, min(payload.max_upstream_streams, 16))),
        "hdhr_public_base_url": normalise_base_url(payload.public_base_url),
        "hdhr_stream_mode": stream_mode,
        "hdhr_conflict_policy": conflict_policy,
        "hdhr_ffmpeg_path": payload.ffmpeg_path.strip() or "ffmpeg",
        "hdhr_buffer_seconds": str(max(0, min(payload.buffer_seconds, 120))),
        "hdhr_buffer_max_mb": str(max(16, min(payload.buffer_max_mb, 2048))),
        "hdhr_stream_cleanup_enabled": "true" if payload.stream_cleanup_enabled else "false",
        "hdhr_max_stream_age_minutes": str(max(1, min(payload.max_stream_age_minutes, 1440))),
        "hdhr_idle_timeout_seconds": str(max(0, min(payload.idle_timeout_seconds, 3600))),
        "hdhr_cleanup_interval_seconds": str(max(5, min(payload.cleanup_interval_seconds, 300))),
        "hdhr_scheduled_drop_enabled": "true" if payload.scheduled_drop_enabled else "false",
        "hdhr_scheduled_drop_time": normalise_hhmm(payload.scheduled_drop_time, "04:00"),
    }
    for key, value in values.items():
        set_setting(key, value)

    start_ssdp_service()
    start_stream_safety_service()
    return get_hdhr_settings()


def base_url_for_request(request: Request, settings: HdhrSettings | None = None) -> str:
    settings = settings or get_hdhr_settings()
    if settings.public_base_url:
        return settings.public_base_url
    return str(request.base_url).rstrip("/")


def selected_channel_row(channel_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                channels.id AS channel_id,
                channels.name,
                channels.tvg_name,
                channels.tvg_id,
                channels.stream_url
            FROM channels
            JOIN groups ON groups.id = channels.group_id
            WHERE channels.id = ?
              AND channels.selected = 1
              AND channels.missing = 0
              AND groups.missing = 0
            """,
            (channel_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Selected channel not found")
    if not row["stream_url"]:
        raise HTTPException(status_code=404, detail="Channel has no stream URL")
    return dict(row)


def selected_catalogue_channels(limit: int | None = None) -> list[dict[str, Any]]:
    channels = []
    for index, channel in enumerate(get_selected_channels(), start=1):
        if limit is not None and index > limit:
            break
        channels.append(
            {
                "number": index,
                "channel_id": channel["id"],
                "name": channel.get("name") or channel.get("tvg_name") or f"Channel {index}",
                "tvg_name": channel.get("tvg_name") or "",
                "tvg_id": channel.get("tvg_id") or "",
                "group_id": channel.get("group_id") or "",
                "group_name": channel.get("group_name") or "Ungrouped",
                "logo_url": channel.get("effective_logo_url") or channel.get("logo_url") or "",
                "stream_url": channel.get("stream_url") or "",
                "extinf": channel.get("extinf") or "",
            }
        )
    return channels


def hdhr_catalogue_channels(settings: HdhrSettings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_hdhr_settings()
    return selected_catalogue_channels(settings.channel_limit)


def selected_catalogue_groups(channels: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    channels = channels if channels is not None else selected_catalogue_channels()
    groups: list[dict[str, Any]] = []
    by_group_id: dict[str, dict[str, Any]] = {}

    for channel in channels:
        group_id = channel["group_id"] or "ungrouped"
        group = by_group_id.get(group_id)
        if not group:
            group = {
                "group_id": group_id,
                "name": channel["group_name"] or "Ungrouped",
                "channels": [],
            }
            by_group_id[group_id] = group
            groups.append(group)
        group["channels"].append(channel)

    return groups


def catalogue_payload(base_url: str, settings: HdhrSettings | None = None) -> dict[str, Any]:
    channels = hdhr_catalogue_channels(settings)
    groups = selected_catalogue_groups(channels)
    return {
        "containers": [
            {
                "id": "channels",
                "title": "Channels",
                "channel_count": len(channels),
            },
            {
                "id": "favourites",
                "title": "Favourites",
                "channel_count": len(channels),
            },
            {
                "id": "groups",
                "title": "Groups",
                "group_count": len(groups),
                "channel_count": len(channels),
            },
        ],
        "channels": [
            {
                **channel,
                "url": urljoin(f"{base_url}/", f"auto/v{channel['number']}"),
            }
            for channel in channels
        ],
        "groups": [
            {
                **group,
                "channels": [
                    {
                        **channel,
                        "url": urljoin(f"{base_url}/", f"auto/v{channel['number']}"),
                    }
                    for channel in group["channels"]
                ],
            }
            for group in groups
        ],
    }


def active_status() -> dict[str, Any]:
    now = time.time()
    with STREAM_LOCK:
        sessions = [
            {
                "session_id": session.session_id,
                "channel_id": session.channel_id,
                "channel_name": session.channel_name,
                "mode": session.mode,
                "seconds": int(now - session.started_at),
                "idle_seconds": int(now - session.last_activity_at),
                "bytes_sent": session.bytes_sent,
                "buffer_bytes": session.buffer_bytes,
                "buffer_target_seconds": session.buffer_target_seconds,
            }
            for session in ACTIVE_STREAMS.values()
        ]

    return {
        "active_client_count": len(sessions),
        "active_upstream_count": len(sessions),
        "streams": sessions,
        "ssdp": dict(SSDP_STATUS),
        "stream_safety": dict(STREAM_SAFETY_STATUS),
    }


def stop_stream_session(session_id: str) -> None:
    with STREAM_LOCK:
        session = ACTIVE_STREAMS.pop(session_id, None)

    if not session:
        return

    if session.upstream is not None:
        try:
            session.upstream.close()
        except Exception:
            pass

    if session.process is not None and session.process.poll() is None:
        try:
            session.process.terminate()
            session.process.wait(timeout=2)
        except Exception:
            try:
                session.process.kill()
            except Exception:
                pass


def stop_all_proxy_streams() -> None:
    with STREAM_LOCK:
        ids = list(ACTIVE_STREAMS.keys())
    for session_id in ids:
        stop_stream_session(session_id)


def record_stream_chunk(session: StreamSession, chunk: bytes) -> None:
    now = time.time()
    with STREAM_LOCK:
        active = ACTIVE_STREAMS.get(session.session_id)
        if not active:
            return
        active.last_activity_at = now
        active.bytes_sent += len(chunk)


def set_stream_buffer_bytes(session: StreamSession, buffer_bytes: int) -> None:
    with STREAM_LOCK:
        active = ACTIVE_STREAMS.get(session.session_id)
        if active:
            active.buffer_bytes = buffer_bytes


def reserve_stream_session(channel: dict[str, Any], settings: HdhrSettings) -> StreamSession:
    now = time.time()
    session = StreamSession(
        session_id=str(uuid.uuid4()),
        channel_id=channel["channel_id"],
        channel_name=str(channel["name"] or "Channel"),
        mode=settings.stream_mode,
        started_at=now,
        last_activity_at=now,
        buffer_target_seconds=settings.buffer_seconds if settings.stream_mode == "buffered" else 0,
    )

    stream_limit = min(settings.tuner_count, settings.max_upstream_streams)

    with STREAM_LOCK:
        if len(ACTIVE_STREAMS) >= stream_limit:
            if settings.conflict_policy == "stop_existing":
                existing_ids = list(ACTIVE_STREAMS.keys())
            else:
                raise HTTPException(status_code=409, detail="No tuner available")
        else:
            existing_ids = []

    for existing_id in existing_ids:
        stop_stream_session(existing_id)

    with STREAM_LOCK:
        if len(ACTIVE_STREAMS) >= stream_limit:
            raise HTTPException(status_code=409, detail="No tuner available")
        ACTIVE_STREAMS[session.session_id] = session

    return session


def direct_stream_iterator(session: StreamSession) -> Iterator[bytes]:
    try:
        while True:
            chunk = session.upstream.read(1024 * 256)
            if not chunk:
                break
            record_stream_chunk(session, chunk)
            yield chunk
    finally:
        stop_stream_session(session.session_id)


def open_direct_upstream(session: StreamSession, stream_url: str) -> None:
    try:
        req = Request(
            stream_url,
            headers={
                "User-Agent": "VLC/3.0.0 LibVLC/3.0.0",
                "Accept": "*/*",
            },
        )
        session.upstream = urlopen(req, timeout=20)
    except HTTPError as exc:
        stop_stream_session(session.session_id)
        raise HTTPException(status_code=exc.code, detail=f"Upstream stream error: {exc.reason}") from exc
    except URLError as exc:
        stop_stream_session(session.session_id)
        raise HTTPException(status_code=502, detail=f"Could not open upstream stream: {exc.reason}") from exc


def ffmpeg_command(stream_url: str, ffmpeg_path: str) -> list[str]:
    return [
        ffmpeg_path,
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
        "-i",
        stream_url,
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
        "-c",
        "copy",
        "-f",
        "mpegts",
        "pipe:1",
    ]


def open_ffmpeg_process(session: StreamSession, stream_url: str, ffmpeg_path: str) -> None:
    try:
        session.process = subprocess.Popen(
            ffmpeg_command(stream_url, ffmpeg_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        stop_stream_session(session.session_id)
        raise HTTPException(status_code=500, detail=f"Could not start ffmpeg: {exc}") from exc


def ffmpeg_stream_iterator(session: StreamSession) -> Iterator[bytes]:
    try:
        if session.process is None or session.process.stdout is None:
            return

        while True:
            chunk = session.process.stdout.read(1024 * 256)
            if not chunk:
                break
            record_stream_chunk(session, chunk)
            yield chunk
    finally:
        stop_stream_session(session.session_id)


def buffered_ffmpeg_stream_iterator(session: StreamSession, buffer_seconds: int, buffer_max_mb: int) -> Iterator[bytes]:
    chunks: Deque[BufferedChunk] = deque()
    max_buffer_bytes = buffer_max_mb * 1024 * 1024
    startup_delay_seconds = min(buffer_seconds, 2)
    buffered_bytes = 0
    done = False
    condition = threading.Condition()

    def reader() -> None:
        nonlocal buffered_bytes, done
        try:
            if session.process is None or session.process.stdout is None:
                return

            while True:
                chunk = session.process.stdout.read(1024 * 256)
                if not chunk:
                    break
                item = BufferedChunk(data=chunk, read_at=time.monotonic())
                with condition:
                    while buffered_bytes + len(chunk) > max_buffer_bytes and not STREAM_SAFETY_STOP.is_set():
                        condition.wait(timeout=0.25)
                    chunks.append(item)
                    buffered_bytes += len(chunk)
                    set_stream_buffer_bytes(session, buffered_bytes)
                    condition.notify_all()
        finally:
            with condition:
                done = True
                condition.notify_all()

    thread = threading.Thread(target=reader, name=f"hdhr-buffer-{session.session_id[:8]}", daemon=True)
    thread.start()

    try:
        while True:
            with condition:
                while not chunks and not done:
                    condition.wait(timeout=0.25)
                if not chunks and done:
                    break
                item = chunks[0]

            release_at = item.read_at + startup_delay_seconds
            wait_for = release_at - time.monotonic()
            if wait_for > 0:
                time.sleep(min(wait_for, 0.25))
                continue

            with condition:
                if not chunks:
                    continue
                item = chunks.popleft()
                buffered_bytes -= len(item.data)
                set_stream_buffer_bytes(session, buffered_bytes)
                condition.notify_all()

            record_stream_chunk(session, item.data)
            yield item.data
    finally:
        stop_stream_session(session.session_id)
        with condition:
            done = True
            chunks.clear()
            buffered_bytes = 0
            set_stream_buffer_bytes(session, 0)
            condition.notify_all()


def stream_safety_cleanup(settings: HdhrSettings) -> None:
    if not settings.stream_cleanup_enabled:
        return

    now = time.time()
    max_age_seconds = settings.max_stream_age_minutes * 60
    idle_timeout = settings.idle_timeout_seconds
    stale_sessions: list[tuple[str, str]] = []

    with STREAM_LOCK:
        for session in ACTIVE_STREAMS.values():
            if now - session.started_at >= max_age_seconds:
                stale_sessions.append((session.session_id, "max_age"))
                continue
            if idle_timeout and now - session.last_activity_at >= idle_timeout:
                stale_sessions.append((session.session_id, "idle_timeout"))

    for session_id, reason in stale_sessions:
        stop_stream_session(session_id)
        STREAM_SAFETY_STATUS["last_cleanup_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        STREAM_SAFETY_STATUS["last_cleanup_reason"] = reason


def scheduled_drop_due(settings: HdhrSettings, last_drop_day: str | None) -> tuple[bool, str | None]:
    if not settings.scheduled_drop_enabled:
        return False, last_drop_day

    now = time.localtime()
    today = time.strftime("%Y-%m-%d", now)
    if today == last_drop_day:
        return False, last_drop_day

    if time.strftime("%H:%M", now) == settings.scheduled_drop_time:
        return True, today
    return False, last_drop_day


def stream_safety_loop() -> None:
    last_drop_day: str | None = None
    STREAM_SAFETY_STATUS["running"] = True
    while not STREAM_SAFETY_STOP.is_set():
        settings = get_hdhr_settings()
        try:
            stream_safety_cleanup(settings)
            should_drop, last_drop_day = scheduled_drop_due(settings, last_drop_day)
            if should_drop:
                stop_all_proxy_streams()
                STREAM_SAFETY_STATUS["last_drop_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        except Exception as exc:
            STREAM_SAFETY_STATUS["last_cleanup_reason"] = f"error: {exc}"
        STREAM_SAFETY_STOP.wait(settings.cleanup_interval_seconds)
    STREAM_SAFETY_STATUS["running"] = False


def hdhr_discovery_payload(base_url: str, settings: HdhrSettings) -> dict[str, Any]:
    return {
        "FriendlyName": settings.device_name,
        "Manufacturer": "Silicondust",
        "ModelNumber": "HDTC-2US",
        "FirmwareName": "hdhomeruntc_atsc",
        "FirmwareVersion": "20250101",
        "DeviceID": settings.device_id,
        "DeviceAuth": "iptv-epg",
        "BaseURL": base_url,
        "LineupURL": urljoin(f"{base_url}/", "lineup.json"),
        "GuideURL": urljoin(f"{base_url}/", "hdhr_epg.xml"),
        "TunerCount": settings.tuner_count,
    }


def lineup_rows(base_url: str, settings: HdhrSettings | None = None) -> list[dict[str, str]]:
    rows = []
    for channel in hdhr_catalogue_channels(settings):
        guide_number = str(channel["number"])
        rows.append(
            {
                "GuideNumber": guide_number,
                "GuideName": channel["name"] or guide_number,
                "URL": urljoin(f"{base_url}/", f"auto/v{guide_number}"),
            }
        )
    return rows


def channel_id_for_guide_number(guide_number: str) -> str | None:
    try:
        index = int(guide_number)
    except ValueError:
        return None
    if index < 1:
        return None

    channels = hdhr_catalogue_channels()
    if index > len(channels):
        return None
    return channels[index - 1]["channel_id"]


def generate_hdhr_m3u(base_url: str, settings: HdhrSettings | None = None) -> dict[str, Any]:
    HDHR_PROXY_M3U.parent.mkdir(parents=True, exist_ok=True)
    rows = hdhr_catalogue_channels(settings)

    tmp = HDHR_PROXY_M3U.with_suffix(".m3u.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for row in rows:
            extinf = extinf_with_logo(row["extinf"].rstrip(), row.get("logo_url"))
            f.write(extinf + "\n")
            f.write(urljoin(f"{base_url}/", f"auto/v{row['number']}") + "\n")

    tmp.replace(HDHR_PROXY_M3U)
    return {"path": str(HDHR_PROXY_M3U), "selected_count": len(rows)}


def serialize_xmltv_element(elem: ET.Element) -> str:
    return ET.tostring(elem, encoding="unicode", short_empty_elements=True)


def hdhr_xmltv_stream() -> Iterator[str]:
    settings = get_hdhr_settings()
    channels = hdhr_catalogue_channels(settings)
    by_xmltv_id: dict[str, list[dict[str, Any]]] = {}
    for channel in channels:
        xmltv_id = (channel.get("tvg_id") or channel.get("channel_id") or "").strip()
        if not xmltv_id:
            continue
        by_xmltv_id.setdefault(xmltv_id, []).append(channel)

    yield '<?xml version="1.0" encoding="UTF-8"?>\n'
    yield '<tv generator-info-name="iptv_epg HDHR filtered">\n'

    for channel in channels:
        channel_elem = ET.Element("channel", {"id": str(channel["number"])})
        display_number = ET.SubElement(channel_elem, "display-name")
        display_number.text = str(channel["number"])
        display_name = ET.SubElement(channel_elem, "display-name")
        display_name.text = channel["name"]
        if channel.get("tvg_id"):
            display_tvg = ET.SubElement(channel_elem, "display-name")
            display_tvg.text = channel["tvg_id"]
        if channel.get("logo_url"):
            ET.SubElement(channel_elem, "icon", {"src": channel["logo_url"]})
        yield serialize_xmltv_element(channel_elem)
        yield "\n"

    if not FILTERED_EPG.exists() or not by_xmltv_id:
        yield "</tv>\n"
        return

    try:
        context = ET.iterparse(FILTERED_EPG, events=("end",))
        for _event, elem in context:
            if elem.tag != "programme":
                continue

            source_channel = elem.attrib.get("channel") or ""
            target_channels = by_xmltv_id.get(source_channel, [])
            if not target_channels:
                elem.clear()
                continue

            original_channel = elem.attrib.get("channel")
            for target in target_channels:
                elem.attrib["channel"] = str(target["number"])
                yield serialize_xmltv_element(elem)
                yield "\n"
            if original_channel is not None:
                elem.attrib["channel"] = original_channel
            elem.clear()
    except ET.ParseError:
        pass

    yield "</tv>\n"


@router.get("/api/hdhr/settings")
def api_hdhr_settings(request: Request) -> dict:
    settings = get_hdhr_settings()
    return {
        "ok": True,
        "settings": {
            **settings.__dict__,
            "resolved_base_url": base_url_for_request(request, settings),
        },
        "status": active_status(),
    }


@router.post("/api/hdhr/settings")
def api_save_hdhr_settings(payload: HdhrSettingsIn, request: Request) -> dict:
    settings = save_hdhr_settings(payload)
    return {
        "ok": True,
        "settings": {
            **settings.__dict__,
            "resolved_base_url": base_url_for_request(request, settings),
        },
        "status": active_status(),
    }


@router.post("/api/hdhr/generate-m3u")
def api_generate_hdhr_m3u(request: Request) -> dict:
    settings = get_hdhr_settings()
    result = generate_hdhr_m3u(base_url_for_request(request, settings), settings)
    return {"ok": True, **result}


@router.get("/hdhr.m3u", response_model=None)
def hdhr_m3u(request: Request) -> PlainTextResponse | FileResponse:
    if not HDHR_PROXY_M3U.exists():
        settings = get_hdhr_settings()
        generate_hdhr_m3u(base_url_for_request(request, settings), settings)
    if not HDHR_PROXY_M3U.exists():
        return PlainTextResponse("#EXTM3U\n", media_type="application/vnd.apple.mpegurl")
    return FileResponse(HDHR_PROXY_M3U, media_type="application/vnd.apple.mpegurl", filename="hdhr.m3u")


@router.get("/hdhr_epg.xml", response_model=None)
def hdhr_epg() -> StreamingResponse:
    return StreamingResponse(
        hdhr_xmltv_stream(),
        media_type="application/xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/discover.json")
def discover_json(request: Request) -> dict:
    settings = get_hdhr_settings()
    return hdhr_discovery_payload(base_url_for_request(request, settings), settings)


@router.get("/lineup.json")
def lineup_json(request: Request) -> list[dict[str, str]]:
    settings = get_hdhr_settings()
    return lineup_rows(base_url_for_request(request, settings), settings)


@router.get("/lineup_status.json")
def lineup_status_json() -> dict:
    settings = get_hdhr_settings()
    return {
        "ScanInProgress": 0,
        "ScanPossible": 1 if settings.enabled else 0,
        "Source": "Cable",
        "SourceList": ["Cable"],
    }


@router.get("/auto/v{guide_number}", response_model=None)
def hdhr_auto_stream(guide_number: str) -> StreamingResponse:
    channel_id = channel_id_for_guide_number(guide_number)
    if not channel_id:
        raise HTTPException(status_code=404, detail="Channel not found")
    return hdhr_stream_channel(channel_id)


@router.get("/hdhr/channel/{channel_id}", response_model=None)
def hdhr_stream_channel(channel_id: str) -> StreamingResponse:
    settings = get_hdhr_settings()
    if not settings.enabled:
        raise HTTPException(status_code=403, detail="HDHR is disabled")

    channel = selected_channel_row(channel_id)
    session = reserve_stream_session(channel, settings)

    if settings.stream_mode == "buffered":
        open_ffmpeg_process(session, channel["stream_url"], settings.ffmpeg_path)
        iterator = buffered_ffmpeg_stream_iterator(session, settings.buffer_seconds, settings.buffer_max_mb)
    elif settings.stream_mode == "ffmpeg":
        open_ffmpeg_process(session, channel["stream_url"], settings.ffmpeg_path)
        iterator = ffmpeg_stream_iterator(session)
    else:
        open_direct_upstream(session, channel["stream_url"])
        iterator = direct_stream_iterator(session)

    return StreamingResponse(
        iterator,
        media_type="video/mp2t",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/hdhr/streams/stop")
def api_stop_hdhr_streams() -> dict:
    stop_all_proxy_streams()
    return {"ok": True, "status": active_status()}


@router.get("/api/hdhr/status")
def api_hdhr_status() -> dict:
    return {"ok": True, "status": active_status()}


@router.get("/api/hdhr/catalogue")
def api_hdhr_catalogue(request: Request) -> dict:
    settings = get_hdhr_settings()
    return {
        "ok": True,
        "catalogue": catalogue_payload(base_url_for_request(request, settings), settings),
    }


def ssdp_headers(message: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_line in message.replace("\r\n", "\n").split("\n"):
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        headers[key.strip().upper()] = value.strip()
    return headers


def ssdp_response(location: str, settings: HdhrSettings, search_target: str) -> bytes:
    st = search_target or "ssdp:all"
    usn = f"uuid:{settings.device_id}"
    if st.lower() not in {"ssdp:all", "upnp:rootdevice"}:
        usn = f"{usn}::{st}"

    lines = [
        "HTTP/1.1 200 OK",
        "CACHE-CONTROL: max-age=1800",
        "EXT:",
        f"LOCATION: {location}",
        "SERVER: iptv-epg/1.0 UPnP/1.0 HDHomeRun/1.0",
        f"ST: {st}",
        f"USN: {usn}",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8")


def ssdp_search_target(message: str) -> str | None:
    headers = ssdp_headers(message)
    return headers.get("ST")


def ssdp_should_respond(message: str, search_target: str | None) -> bool:
    upper = message.upper()
    if "M-SEARCH" not in upper:
        return False
    if "SSDP:DISCOVER" not in upper:
        return False
    target = (search_target or "").upper()
    return (
        target in {"SSDP:ALL", "UPNP:ROOTDEVICE"}
        or "MEDIA SERVER" in target
        or "MEDIASERVER" in target
        or "HDHOMERUN" in target
        or "DIAL-MULTISCREEN" in target
    )


def ssdp_notify_messages(location: str, settings: HdhrSettings) -> list[bytes]:
    targets = [
        "upnp:rootdevice",
        "urn:schemas-upnp-org:device:MediaServer:1",
        "urn:schemas-upnp-org:device:MediaServer:2",
        "urn:schemas-upnp-org:device:MediaServer:3",
        "urn:schemas-upnp-org:device:dial:1",
    ]
    messages = []
    for target in targets:
        usn = f"uuid:{settings.device_id}::{target}"
        lines = [
            "NOTIFY * HTTP/1.1",
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}",
            "CACHE-CONTROL: max-age=1800",
            f"LOCATION: {location}",
            "SERVER: iptv-epg/1.0 UPnP/1.0 HDHomeRun/1.0",
            f"NT: {target}",
            "NTS: ssdp:alive",
            f"USN: {usn}",
            "",
            "",
        ]
        messages.append("\r\n".join(lines).encode("utf-8"))
    return messages


def ssdp_loop() -> None:
    SSDP_STATUS["running"] = True
    while not SSDP_STOP.is_set():
        settings = get_hdhr_settings()
        if not settings.enabled or not settings.public_base_url:
            SSDP_STATUS["listening"] = False
            SSDP_STOP.wait(2)
            continue

        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("", SSDP_PORT))
            except OSError:
                SSDP_STATUS["listening"] = False
                SSDP_STATUS["last_error"] = f"Could not bind UDP {SSDP_PORT}"
                SSDP_STOP.wait(5)
                continue
            sock.settimeout(1)
            SSDP_STATUS["listening"] = True
            SSDP_STATUS["last_error"] = None

            try:
                group = socket.inet_aton(SSDP_ADDR)
                mreq = group + socket.inet_aton("0.0.0.0")
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass

            location = urljoin(f"{settings.public_base_url}/", "discover.json")
            notify_payloads = ssdp_notify_messages(location, settings)
            next_notify_at = 0.0

            while not SSDP_STOP.is_set():
                now = time.monotonic()
                if now >= next_notify_at:
                    for notify_payload in notify_payloads:
                        try:
                            sock.sendto(notify_payload, (SSDP_ADDR, SSDP_PORT))
                        except OSError:
                            pass
                    SSDP_STATUS["last_notify_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    next_notify_at = now + 300

                try:
                    data, addr = sock.recvfrom(2048)
                except socket.timeout:
                    next_settings = get_hdhr_settings()
                    if (
                        not next_settings.enabled
                        or next_settings.public_base_url != settings.public_base_url
                        or next_settings.device_id != settings.device_id
                    ):
                        break
                    continue
                except OSError:
                    break

                try:
                    message = data.decode("utf-8", errors="ignore")
                    search_target = ssdp_search_target(message) or "ssdp:all"
                    if ssdp_should_respond(message, search_target):
                        SSDP_STATUS["last_request_from"] = f"{addr[0]}:{addr[1]}"
                        SSDP_STATUS["last_search_target"] = search_target
                        sock.sendto(ssdp_response(location, settings, search_target), addr)
                        SSDP_STATUS["last_response_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                except OSError:
                    pass
        finally:
            SSDP_STATUS["listening"] = False
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
    SSDP_STATUS["running"] = False


def start_ssdp_service() -> None:
    global SSDP_THREAD
    if SSDP_THREAD and SSDP_THREAD.is_alive():
        return
    SSDP_STOP.clear()
    SSDP_THREAD = threading.Thread(target=ssdp_loop, name="hdhr-ssdp", daemon=True)
    SSDP_THREAD.start()


def start_stream_safety_service() -> None:
    global STREAM_SAFETY_THREAD
    if STREAM_SAFETY_THREAD and STREAM_SAFETY_THREAD.is_alive():
        return
    STREAM_SAFETY_STOP.clear()
    STREAM_SAFETY_THREAD = threading.Thread(target=stream_safety_loop, name="hdhr-stream-safety", daemon=True)
    STREAM_SAFETY_THREAD.start()


def stop_stream_safety_service() -> None:
    STREAM_SAFETY_STOP.set()


def stop_ssdp_service() -> None:
    SSDP_STOP.set()
    stop_stream_safety_service()
    stop_all_proxy_streams()

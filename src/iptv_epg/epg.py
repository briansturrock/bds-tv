from __future__ import annotations

import gzip
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import xml.etree.ElementTree as ET

import requests

from .db import connect, update_job
from .settings import EPG_CACHE_DIR, FILTERED_EPG, SOURCE_M3U


URL_TVG_RE = re.compile(r'url-tvg="([^"]+)"', re.IGNORECASE)


def strip_xml_namespace(root: ET.Element) -> None:
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]


def detect_url_tvg_from_m3u(path: Path = SOURCE_M3U) -> str | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for _ in range(25):
            line = f.readline()
            if not line:
                break
            match = URL_TVG_RE.search(line)
            if match:
                return match.group(1).strip()
    return None


def infer_xtream_xmltv_url(m3u_url: str | None) -> str | None:
    if not m3u_url:
        return None

    parsed = urlparse(m3u_url)
    if not parsed.scheme or not parsed.netloc:
        return None

    if "get.php" not in parsed.path:
        return None

    query = parse_qs(parsed.query)
    username = query.get("username", [None])[0]
    password = query.get("password", [None])[0]
    if not username or not password:
        return None

    new_query = urlencode({"username": username, "password": password})
    return urlunparse((parsed.scheme, parsed.netloc, "/xmltv.php", "", new_query, ""))


def detect_epg_urls(m3u_url: str | None) -> list[dict]:
    results: list[dict] = []

    url_tvg = detect_url_tvg_from_m3u()
    if url_tvg:
        results.append({
            "name": "Detected from M3U url-tvg",
            "url": url_tvg,
            "source_type": "m3u_url_tvg",
        })

    inferred = infer_xtream_xmltv_url(m3u_url)
    if inferred and inferred not in {r["url"] for r in results}:
        results.append({
            "name": "Inferred Xtream XMLTV",
            "url": inferred,
            "source_type": "xtream_inferred",
        })

    return results


def download_epg(url: str, source_id: int, job_id: str | None = None) -> Path:
    EPG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".xml.gz" if url.lower().endswith(".gz") else ".xml"
    destination = EPG_CACHE_DIR / f"source_{source_id}{suffix}"

    size = 0
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(EPG_CACHE_DIR)) as tmp:
        tmp_path = Path(tmp.name)
        with requests.get(url, stream=True, timeout=(20, 240), headers={"User-Agent": "iptv_epg/0.8"}) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if not chunk:
                    continue
                tmp.write(chunk)
                size += len(chunk)
                if job_id:
                    update_job(job_id, message=f"Downloading EPG ({size // (1024 * 1024)} MB)")

    shutil.move(str(tmp_path), str(destination))
    return destination


def open_epg_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        return gzip.decompress(raw)
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def scan_epg_channels(source_id: int, url: str, job_id: str | None = None) -> dict[str, int]:
    path = download_epg(url, source_id, job_id=job_id)
    if job_id:
        update_job(job_id, message="Parsing EPG channel list")

    root = ET.fromstring(open_epg_bytes(path))
    strip_xml_namespace(root)

    channels: list[tuple[str, str]] = []
    for channel in root.findall("channel"):
        xmltv_id = channel.attrib.get("id", "").strip()
        display_name = ""
        display = channel.find("display-name")
        if display is not None and display.text:
            display_name = display.text.strip()
        if not display_name:
            display_name = xmltv_id
        if xmltv_id:
            channels.append((xmltv_id, display_name))

    with connect() as conn:
        conn.execute("DELETE FROM epg_channels WHERE source_id = ?", (source_id,))
        conn.executemany(
            """
            INSERT INTO epg_channels(source_id, xmltv_id, display_name, last_seen_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_id, xmltv_id) DO UPDATE SET
                display_name = excluded.display_name,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            [(source_id, xmltv_id, display_name) for xmltv_id, display_name in channels],
        )

        match_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM channels
            JOIN epg_channels
              ON epg_channels.source_id = ?
             AND epg_channels.xmltv_id = channels.tvg_id
            WHERE channels.selected = 1
              AND channels.missing = 0
              AND channels.tvg_id IS NOT NULL
              AND channels.tvg_id != ''
            """,
            (source_id,),
        ).fetchone()[0]

        conn.execute(
            """
            UPDATE epg_sources
            SET last_tested_at = CURRENT_TIMESTAMP,
                last_channel_count = ?,
                last_match_count = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (len(channels), match_count, source_id),
        )
        conn.commit()

    return {
        "epg_channel_count": len(channels),
        "match_count": int(match_count),
    }


def parse_xmltv_time(value: str) -> datetime | None:
    if not value:
        return None

    value = value.strip()
    main = value[:14]
    try:
        dt = datetime.strptime(main, "%Y%m%d%H%M%S")
    except ValueError:
        return None

    rest = value[14:].strip()
    if re.match(r"^[+-]\d{4}$", rest):
        sign = 1 if rest[0] == "+" else -1
        hours = int(rest[1:3])
        minutes = int(rest[3:5])
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return dt.replace(tzinfo=offset).astimezone(timezone.utc)

    return dt.replace(tzinfo=timezone.utc)


def source_ids_enabled() -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM epg_sources WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    return [int(r["id"]) for r in rows]


def build_selected_channel_map(source_id: int) -> dict[str, dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                channels.id AS channel_id,
                channels.name,
                channels.tvg_id,
                channels.logo_url,
                channels.stream_url,
                COALESCE(epg_mappings.xmltv_id, channels.epg_xmltv_id, channels.tvg_id) AS xmltv_id
            FROM channels
            LEFT JOIN epg_mappings ON epg_mappings.channel_id = channels.id
            WHERE channels.selected = 1
              AND channels.missing = 0
            """
        ).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        xmltv_id = (row["xmltv_id"] or "").strip()
        if xmltv_id:
            result[xmltv_id] = dict(row)
    return result


def generate_filtered_epg(days: int = 3, source_id: int | None = None, job_id: str | None = None) -> dict[str, int | str]:
    days = max(1, min(int(days), 14))
    ids = [source_id] if source_id else source_ids_enabled()

    if not ids:
        FILTERED_EPG.write_text('<?xml version="1.0" encoding="UTF-8"?><tv></tv>\n', encoding="utf-8")
        return {"path": str(FILTERED_EPG), "channels": 0, "programmes": 0, "days": days}

    active_source_id = ids[0]

    with connect() as conn:
        source = conn.execute(
            "SELECT id, url FROM epg_sources WHERE id = ?",
            (active_source_id,),
        ).fetchone()

    if not source:
        raise RuntimeError("EPG source not found")

    path = download_epg(source["url"], active_source_id, job_id=job_id)
    if job_id:
        update_job(job_id, message="Filtering EPG programmes")

    selected = build_selected_channel_map(active_source_id)
    wanted_xmltv_ids = set(selected.keys())

    if not wanted_xmltv_ids:
        FILTERED_EPG.write_text('<?xml version="1.0" encoding="UTF-8"?><tv></tv>\n', encoding="utf-8")
        return {"path": str(FILTERED_EPG), "channels": 0, "programmes": 0, "days": days}

    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days)

    root = ET.fromstring(open_epg_bytes(path))
    strip_xml_namespace(root)

    out_root = ET.Element("tv")
    channel_count = 0
    programme_count = 0

    for channel in root.findall("channel"):
        channel_id = channel.attrib.get("id", "")
        if channel_id in wanted_xmltv_ids:
            out_root.append(channel)
            channel_count += 1

    for programme in root.findall("programme"):
        channel_id = programme.attrib.get("channel", "")
        if channel_id not in wanted_xmltv_ids:
            continue

        start = parse_xmltv_time(programme.attrib.get("start", ""))
        if start is None:
            continue
        if not (now <= start <= until):
            continue

        out_root.append(programme)
        programme_count += 1

    tmp = FILTERED_EPG.with_suffix(".xml.tmp")
    ET.ElementTree(out_root).write(tmp, encoding="utf-8", xml_declaration=True)
    shutil.move(str(tmp), str(FILTERED_EPG))

    return {
        "path": str(FILTERED_EPG),
        "channels": channel_count,
        "programmes": programme_count,
        "days": days,
    }

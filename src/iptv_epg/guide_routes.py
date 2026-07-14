from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Query

from .db import apply_inherited_preferred_logos, connect


router = APIRouter(prefix="/api/guide", tags=["guide"])


def filtered_epg_path() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "filtered_epg.xml"


def parse_xmltv_time(value: str | None) -> datetime | None:
    if not value:
        return None

    value = value.strip()
    match = re.match(r"^(\d{14})(?:\s*([+-]\d{4}))?", value)
    if not match:
        return None

    date_part = match.group(1)
    offset_part = match.group(2) or "+0000"

    try:
        return datetime.strptime(f"{date_part} {offset_part}", "%Y%m%d%H%M%S %z")
    except ValueError:
        return None


def first_text(elem: ET.Element, name: str) -> str:
    child = elem.find(name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def selected_guide_groups() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                groups.id,
                groups.name,
                COUNT(channels.id) AS selected_channel_count
            FROM groups
            JOIN channels ON channels.group_id = groups.id
            WHERE groups.missing = 0
              AND channels.missing = 0
              AND channels.selected = 1
            GROUP BY groups.id, groups.name, groups.user_order, groups.provider_order
            HAVING COUNT(channels.id) > 0
            ORDER BY
                CASE WHEN groups.user_order IS NULL THEN 1 ELSE 0 END,
                groups.user_order ASC,
                groups.provider_order ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def selected_channels_for_group(group_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                channels.id AS channel_id,
                channels.name,
                channels.tvg_name,
                channels.tvg_id,
                channels.logo_url AS default_logo_url,
                channels.preferred_logo_url,
                COALESCE(NULLIF(channels.preferred_logo_url, ''), channels.logo_url) AS logo_url,
                COALESCE(NULLIF(channels.preferred_logo_url, ''), channels.logo_url) AS effective_logo_url,
                channels.provider_order,
                channels.user_order,
                groups.id AS group_id,
                groups.name AS group_name
            FROM channels
            JOIN groups ON groups.id = channels.group_id
            WHERE groups.id = ?
              AND groups.missing = 0
              AND channels.missing = 0
              AND channels.selected = 1
            ORDER BY
                CASE WHEN channels.user_order IS NULL THEN 1 ELSE 0 END,
                channels.user_order ASC,
                channels.provider_order ASC
            """,
            (group_id,),
        ).fetchall()

    return apply_inherited_preferred_logos([dict(row) for row in rows])


def selected_tvg_ids() -> set[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT channels.tvg_id
            FROM channels
            JOIN groups ON groups.id = channels.group_id
            WHERE groups.missing = 0
              AND channels.missing = 0
              AND channels.selected = 1
              AND channels.tvg_id IS NOT NULL
              AND channels.tvg_id != ''
            """
        ).fetchall()

    return {row["tvg_id"] for row in rows}


def guide_date_label(date_value: str) -> str:
    try:
        date_obj = datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError:
        return date_value

    today = datetime.now(timezone.utc).date()

    if date_obj == today:
        return "Today"

    if date_obj == today + timedelta(days=1):
        return "Tomorrow"

    return date_obj.strftime("%A")


def available_guide_dates() -> list[dict[str, str]]:
    epg_path = filtered_epg_path()
    tvg_ids = selected_tvg_ids()
    dates: set[str] = set()

    if not epg_path.exists() or not tvg_ids:
        return []

    today = datetime.now(timezone.utc).date()

    try:
        context = ET.iterparse(epg_path, events=("end",))
        for _event, elem in context:
            if elem.tag != "programme":
                continue

            channel = elem.attrib.get("channel") or ""
            if channel not in tvg_ids:
                elem.clear()
                continue

            start = parse_xmltv_time(elem.attrib.get("start"))
            stop = parse_xmltv_time(elem.attrib.get("stop"))

            if start:
                start_date = start.astimezone(timezone.utc).date()
                if start_date >= today:
                    dates.add(start_date.isoformat())

            if stop:
                stop_date = stop.astimezone(timezone.utc).date()
                if stop_date >= today:
                    dates.add(stop_date.isoformat())

            elem.clear()
    except ET.ParseError:
        return []

    return [
        {
            "date": date_value,
            "label": guide_date_label(date_value),
        }
        for date_value in sorted(dates)[:14]
    ]



def floor_to_previous_half_hour(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    minute = 30 if value.minute >= 30 else 0
    return value.replace(minute=minute, second=0, microsecond=0)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def guide_default_window(date_value: str | None = None) -> tuple[datetime, datetime, str]:
    """Return a useful guide timeline window.

    Today starts at the previous half-hour mark, not midnight. This keeps the
    current/near-current guide visible while still allowing long programmes that
    began earlier to appear because overlap logic is used.

    Future/past dates start at midnight for the selected day.
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    if date_value:
        try:
            selected_day = datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            selected_day = today
    else:
        selected_day = today

    if selected_day == today:
        window_start = floor_to_previous_half_hour(now)
        window_end = window_start + timedelta(hours=8)
        return window_start, window_end, selected_day.isoformat()

    window_start = datetime.combine(selected_day, datetime.min.time(), tzinfo=timezone.utc)
    window_end = window_start + timedelta(hours=8)
    return window_start, window_end, selected_day.isoformat()


def programme_overlaps_window(start: datetime | None, stop: datetime | None, window_start: datetime, window_end: datetime) -> bool:
    if start is None and stop is None:
        return True

    start_utc = start.astimezone(timezone.utc) if start else None
    stop_utc = stop.astimezone(timezone.utc) if stop else None

    if stop_utc is not None and stop_utc <= window_start:
        return False

    if start_utc is not None and start_utc >= window_end:
        return False

    return True


def programmes_for_tvg_ids(
    tvg_ids: set[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[dict[str, Any]]]:
    epg_path = filtered_epg_path()
    programmes: dict[str, list[dict[str, Any]]] = defaultdict(list)

    if not epg_path.exists() or not tvg_ids:
        return programmes

    now = datetime.now(timezone.utc)

    try:
        context = ET.iterparse(epg_path, events=("end",))
        for _event, elem in context:
            # Do not clear child elements such as <title>, <desc>, <category>,
            # etc. before the parent <programme> has been processed. Clearing
            # non-programme elements here strips useful guide metadata.
            if elem.tag != "programme":
                continue

            channel = elem.attrib.get("channel") or ""
            if channel not in tvg_ids:
                elem.clear()
                continue

            start = parse_xmltv_time(elem.attrib.get("start"))
            stop = parse_xmltv_time(elem.attrib.get("stop"))

            if not programme_overlaps_window(start, stop, window_start, window_end):
                elem.clear()
                continue

            start_utc = start.astimezone(timezone.utc) if start else None
            stop_utc = stop.astimezone(timezone.utc) if stop else None

            programmes[channel].append(
                {
                    "channel": channel,
                    "title": first_text(elem, "title") or "Untitled",
                    "sub_title": first_text(elem, "sub-title"),
                    "desc": first_text(elem, "desc"),
                    "category": first_text(elem, "category"),
                    "start": start_utc.isoformat() if start_utc else None,
                    "stop": stop_utc.isoformat() if stop_utc else None,
                    "is_now": bool(start_utc and stop_utc and start_utc <= now <= stop_utc),
                }
            )
            elem.clear()
    except ET.ParseError:
        return programmes

    for items in programmes.values():
        items.sort(key=lambda p: p.get("start") or "")

    return programmes


@router.get("/groups")
def api_guide_groups() -> dict[str, Any]:
    groups = selected_guide_groups()
    return {
        "ok": True,
        "groups": groups,
        "group_count": len(groups),
    }


@router.get("/dates")
def api_guide_dates() -> dict[str, Any]:
    dates = available_guide_dates()
    return {
        "ok": True,
        "dates": dates,
        "date_count": len(dates),
    }


@router.get("")
def api_guide(
    group_id: str = Query(...),
    date: str | None = Query(None, description="Guide date in YYYY-MM-DD format"),
    start: str | None = Query(None, description="Timeline start as ISO datetime"),
    hours: float = Query(8, ge=1, le=24),
) -> dict[str, Any]:
    groups = selected_guide_groups()
    group = next((item for item in groups if item["id"] == group_id), None)

    if not group:
        return {
            "ok": True,
            "group": None,
            "channels": [],
            "channel_count": 0,
            "programme_count": 0,
            "epg_path": str(filtered_epg_path()),
            "message": "Group not found or has no selected channels.",
        }

    channels = selected_channels_for_group(group_id)
    requested_start = parse_iso_datetime(start)
    if requested_start:
        window_start = floor_to_previous_half_hour(requested_start)
        selected_date = window_start.date().isoformat()
    else:
        window_start, _default_window_end, selected_date = guide_default_window(date)

    window_end = window_start + timedelta(hours=max(1, min(float(hours), 24)))

    tvg_ids = {channel["tvg_id"] for channel in channels if channel.get("tvg_id")}
    programmes_by_channel = programmes_for_tvg_ids(tvg_ids, window_start, window_end)

    programme_count = 0
    for channel in channels:
        programmes = programmes_by_channel.get(channel.get("tvg_id") or "", [])
        channel["programmes"] = programmes
        programme_count += len(programmes)

    return {
        "ok": True,
        "group": group,
        "channels": channels,
        "channel_count": len(channels),
        "programme_count": programme_count,
        "epg_path": str(filtered_epg_path()),
        "date": selected_date,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "hours": hours,
    }

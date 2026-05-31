from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import requests

from .db import connect, update_job
from .settings import SOURCE_M3U


ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass(frozen=True)
class M3UEntry:
    group_name: str
    name: str
    tvg_name: str
    tvg_id: str
    logo_url: str
    stream_url: str
    extinf: str
    provider_order: int


def parse_attrs(line: str) -> dict[str, str]:
    return dict(ATTR_RE.findall(line))


def display_name_from_extinf(extinf: str) -> str:
    return extinf.split(",", 1)[-1].strip() if "," in extinf else ""


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def group_id_for_name(name: str) -> str:
    return short_hash(f"group:{name}")


def stable_key_for_channel(entry: M3UEntry) -> str:
    return "|".join([
        entry.group_name.strip(),
        entry.name.strip(),
        entry.tvg_id.strip(),
        entry.stream_url.strip(),
    ])


def channel_id_for_stable_key(stable_key: str) -> str:
    return short_hash(f"channel:{stable_key}")


def parse_m3u_file(path: Path) -> Iterator[M3UEntry]:
    provider_order = 0
    pending_extinf: str | None = None

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue

            if line.startswith("#EXTINF"):
                pending_extinf = line
                continue

            if pending_extinf is not None and not line.startswith("#"):
                attrs = parse_attrs(pending_extinf)
                group_name = attrs.get("group-title", "") or "Ungrouped"
                tvg_name = attrs.get("tvg-name", "")
                tvg_id = attrs.get("tvg-id", "")
                logo_url = attrs.get("tvg-logo", "")
                name = display_name_from_extinf(pending_extinf) or tvg_name or "Unnamed"

                yield M3UEntry(
                    group_name=group_name,
                    name=name,
                    tvg_name=tvg_name,
                    tvg_id=tvg_id,
                    logo_url=logo_url,
                    stream_url=line,
                    extinf=pending_extinf,
                    provider_order=provider_order,
                )
                provider_order += 1
                pending_extinf = None


def download_m3u(url: str, destination: Path, job_id: str | None = None) -> dict[str, str | int]:
    destination.parent.mkdir(parents=True, exist_ok=True)

    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    size = 0

    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(destination.parent)) as tmp:
        tmp_path = Path(tmp.name)
        with requests.get(url, stream=True, timeout=(20, 180), headers={"User-Agent": "iptv_epg/0.8"}) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if not chunk:
                    continue
                tmp.write(chunk)
                md5.update(chunk)
                sha256.update(chunk)
                size += len(chunk)
                if job_id:
                    update_job(job_id, message=f"Downloading source M3U ({size // (1024 * 1024)} MB)")

    shutil.move(str(tmp_path), str(destination))

    return {
        "local_path": str(destination),
        "size_bytes": size,
        "md5": md5.hexdigest(),
        "sha256": sha256.hexdigest(),
    }


def index_m3u(source_path: Path = SOURCE_M3U, job_id: str | None = None) -> dict[str, int]:
    group_order: dict[str, int] = {}
    group_channel_counts: dict[str, int] = {}
    group_selected_counts: dict[str, int] = {}
    channel_count = 0

    with connect() as conn:
        conn.execute("UPDATE groups SET missing = 1")
        conn.execute("UPDATE channels SET missing = 1")

        for entry in parse_m3u_file(source_path):
            group_id = group_id_for_name(entry.group_name)
            if group_id not in group_order:
                group_order[group_id] = len(group_order)

            stable_key = stable_key_for_channel(entry)
            channel_id = channel_id_for_stable_key(stable_key)

            existing = conn.execute(
                "SELECT selected, user_order, epg_xmltv_id FROM channels WHERE stable_key = ?",
                (stable_key,),
            ).fetchone()

            selected = int(existing["selected"]) if existing else 0
            user_order = existing["user_order"] if existing else None
            epg_xmltv_id = existing["epg_xmltv_id"] if existing else None

            conn.execute(
                """
                INSERT INTO groups(id, name, provider_order, channel_count, selected_count, missing, last_seen_at)
                VALUES (?, ?, ?, 0, 0, 0, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    provider_order = excluded.provider_order,
                    missing = 0,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (group_id, entry.group_name, group_order[group_id]),
            )

            conn.execute(
                """
                INSERT INTO channels(
                    id, stable_key, group_id, name, tvg_name, tvg_id, logo_url,
                    stream_url, extinf, provider_order, user_order, selected,
                    epg_xmltv_id, missing, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                ON CONFLICT(stable_key) DO UPDATE SET
                    group_id = excluded.group_id,
                    name = excluded.name,
                    tvg_name = excluded.tvg_name,
                    tvg_id = excluded.tvg_id,
                    logo_url = excluded.logo_url,
                    stream_url = excluded.stream_url,
                    extinf = excluded.extinf,
                    provider_order = excluded.provider_order,
                    user_order = COALESCE(channels.user_order, excluded.user_order),
                    selected = channels.selected,
                    epg_xmltv_id = COALESCE(channels.epg_xmltv_id, excluded.epg_xmltv_id),
                    missing = 0,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (
                    channel_id, stable_key, group_id, entry.name, entry.tvg_name,
                    entry.tvg_id, entry.logo_url, entry.stream_url, entry.extinf,
                    entry.provider_order, user_order, selected, epg_xmltv_id,
                ),
            )

            group_channel_counts[group_id] = group_channel_counts.get(group_id, 0) + 1
            group_selected_counts[group_id] = group_selected_counts.get(group_id, 0) + selected
            channel_count += 1

            if job_id and channel_count % 5000 == 0:
                update_job(job_id, message=f"Indexing channels ({channel_count:,})", progress_current=channel_count)

        for group_id, count in group_channel_counts.items():
            conn.execute(
                "UPDATE groups SET channel_count = ?, selected_count = ? WHERE id = ?",
                (count, group_selected_counts.get(group_id, 0), group_id),
            )

        conn.execute(
            """
            UPDATE m3u_sources
            SET indexed_at = CURRENT_TIMESTAMP,
                channel_count = ?,
                group_count = ?,
                last_error = NULL
            WHERE id = 1
            """,
            (channel_count, len(group_channel_counts)),
        )
        conn.commit()

    return {"channel_count": channel_count, "group_count": len(group_channel_counts)}


def fetch_and_index_m3u(url: str, job_id: str) -> dict[str, int | bool | str]:
    update_job(job_id, message="Downloading source M3U")
    metadata = download_m3u(url, SOURCE_M3U, job_id=job_id)

    with connect() as conn:
        previous = conn.execute("SELECT sha256 FROM m3u_sources WHERE id = 1").fetchone()
        previous_sha = previous["sha256"] if previous else None
        unchanged = previous_sha == metadata["sha256"]

        conn.execute(
            """
            INSERT INTO m3u_sources(id, url, local_path, size_bytes, md5, sha256, fetched_at, last_error)
            VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, NULL)
            ON CONFLICT(id) DO UPDATE SET
                url = excluded.url,
                local_path = excluded.local_path,
                size_bytes = excluded.size_bytes,
                md5 = excluded.md5,
                sha256 = excluded.sha256,
                fetched_at = CURRENT_TIMESTAMP,
                last_error = NULL
            """,
            (url, metadata["local_path"], metadata["size_bytes"], metadata["md5"], metadata["sha256"]),
        )
        conn.commit()

    if unchanged:
        update_job(job_id, status="complete", message="Source M3U unchanged; existing index kept", finish=True)
        return {"unchanged": True, "channel_count": 0, "group_count": 0}

    update_job(job_id, message="Source M3U changed; indexing channels")
    counts = index_m3u(SOURCE_M3U, job_id=job_id)
    update_job(
        job_id,
        status="complete",
        message=f"Indexed {counts['channel_count']:,} channels in {counts['group_count']:,} groups",
        progress_current=counts["channel_count"],
        progress_total=counts["channel_count"],
        finish=True,
    )
    return {"unchanged": False, **counts}

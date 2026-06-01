from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import requests

from .db import connect, update_job


EPGSHARE_BASE_URL = "https://epgshare01.online/epgshare01"
EPGSHARE_ALL_SOURCES_URL = f"{EPGSHARE_BASE_URL}/epg_ripper_ALL_SOURCES1.txt"

SECTION_RE = re.compile(r"^\s*--\s*(epg_ripper_[A-Za-z0-9_]+)\s*--\s*$")


@dataclass(frozen=True)
class EpgshareEntry:
    source_key: str
    xmltv_id: str


def normalize_xmltv_id(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "", value)
    return value


def source_txt_url(source_key: str) -> str:
    return f"{EPGSHARE_BASE_URL}/{source_key}.txt"


def source_xml_url(source_key: str) -> str:
    return f"{EPGSHARE_BASE_URL}/{source_key}.xml.gz"


def ensure_epgshare_tables() -> None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS epgshare_sources (
                    source_key TEXT PRIMARY KEY,
                    txt_url TEXT NOT NULL,
                    xml_url TEXT NOT NULL,
                    channel_count INTEGER NOT NULL DEFAULT 0,
                    last_indexed_at TEXT,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS epgshare_channel_index (
                    xmltv_id TEXT NOT NULL,
                    normalized_xmltv_id TEXT NOT NULL,
                    source_key TEXT NOT NULL REFERENCES epgshare_sources(source_key) ON DELETE CASCADE,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (xmltv_id, source_key)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_epgshare_channel_index_normalized
                ON epgshare_channel_index(normalized_xmltv_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_epgshare_channel_index_source
                ON epgshare_channel_index(source_key)
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def parse_all_sources_text(text: str) -> list[EpgshareEntry]:
    entries: list[EpgshareEntry] = []
    seen: set[tuple[str, str]] = set()
    current_source: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        section = SECTION_RE.match(line)
        if section:
            current_source = section.group(1)
            continue

        if not current_source:
            continue

        if line.startswith("--") and line.endswith("--"):
            continue

        # Lines are XMLTV IDs. Keep punctuation/case as supplied, only trim whitespace.
        # The upstream index can contain duplicates within the same section, so dedupe
        # before inserting into the table whose primary key is (xmltv_id, source_key).
        xmltv_id = line.strip()
        if not xmltv_id:
            continue

        key = (current_source, xmltv_id)
        if key in seen:
            continue

        seen.add(key)
        entries.append(EpgshareEntry(source_key=current_source, xmltv_id=xmltv_id))

    return entries


def download_all_sources_text() -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; iptv_epg/0.1)",
        "Accept": "text/plain,*/*",
    }
    response = requests.get(EPGSHARE_ALL_SOURCES_URL, timeout=(20, 240), headers=headers)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def import_epgshare_index(job_id: str | None = None) -> dict[str, Any]:
    ensure_epgshare_tables()

    if job_id:
        update_job(job_id, message="Downloading EPGShare all-sources index")

    text = download_all_sources_text()
    entries = parse_all_sources_text(text)

    if job_id:
        update_job(job_id, message=f"Parsed {len(entries):,} EPGShare channel/source rows")

    source_counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        source_counts[entry.source_key] += 1

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM epgshare_channel_index")
            conn.execute("DELETE FROM epgshare_sources")

            conn.executemany(
                """
                INSERT INTO epgshare_sources(source_key, txt_url, xml_url, channel_count, last_indexed_at, last_error)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, NULL)
                """,
                [
                    (source_key, source_txt_url(source_key), source_xml_url(source_key), count)
                    for source_key, count in sorted(source_counts.items())
                ],
            )

            conn.executemany(
                """
                INSERT OR IGNORE INTO epgshare_channel_index(xmltv_id, normalized_xmltv_id, source_key, last_seen_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (entry.xmltv_id, normalize_xmltv_id(entry.xmltv_id), entry.source_key)
                    for entry in entries
                ],
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "source_count": len(source_counts),
        "channel_source_row_count": len(entries),
        "all_sources_url": EPGSHARE_ALL_SOURCES_URL,
    }


def epgshare_status() -> dict[str, Any]:
    ensure_epgshare_tables()

    with connect() as conn:
        source_count = conn.execute("SELECT COUNT(*) AS c FROM epgshare_sources").fetchone()["c"]
        row_count = conn.execute("SELECT COUNT(*) AS c FROM epgshare_channel_index").fetchone()["c"]
        distinct_channel_count = conn.execute(
            "SELECT COUNT(DISTINCT xmltv_id) AS c FROM epgshare_channel_index"
        ).fetchone()["c"]
        latest = conn.execute(
            "SELECT MAX(last_indexed_at) AS latest FROM epgshare_sources"
        ).fetchone()["latest"]
        sample_sources = conn.execute(
            """
            SELECT source_key, channel_count, txt_url, xml_url, last_indexed_at
            FROM epgshare_sources
            ORDER BY source_key
            LIMIT 20
            """
        ).fetchall()

    return {
        "ok": True,
        "all_sources_url": EPGSHARE_ALL_SOURCES_URL,
        "source_count": int(source_count),
        "channel_source_row_count": int(row_count),
        "distinct_channel_count": int(distinct_channel_count),
        "last_indexed_at": latest,
        "sample_sources": [dict(r) for r in sample_sources],
    }


def search_epgshare(q: str, limit: int = 50) -> list[dict[str, Any]]:
    ensure_epgshare_tables()
    limit = max(1, min(int(limit), 500))
    q = (q or "").strip()
    like = f"%{q}%"
    normalized_like = f"%{normalize_xmltv_id(q)}%"

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                epgshare_channel_index.xmltv_id,
                epgshare_channel_index.source_key,
                epgshare_sources.txt_url,
                epgshare_sources.xml_url
            FROM epgshare_channel_index
            JOIN epgshare_sources ON epgshare_sources.source_key = epgshare_channel_index.source_key
            WHERE ? = ''
               OR epgshare_channel_index.xmltv_id LIKE ?
               OR epgshare_channel_index.normalized_xmltv_id LIKE ?
            ORDER BY epgshare_channel_index.xmltv_id, epgshare_channel_index.source_key
            LIMIT ?
            """,
            (q, like, normalized_like, limit),
        ).fetchall()

    return [dict(r) for r in rows]


def selected_channels_for_epgshare() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                channels.id AS channel_id,
                channels.name,
                channels.tvg_name,
                channels.tvg_id,
                groups.name AS group_name
            FROM channels
            JOIN groups ON groups.id = channels.group_id
            WHERE channels.selected = 1
              AND channels.missing = 0
              AND groups.missing = 0
            ORDER BY
                CASE WHEN groups.user_order IS NULL THEN 1 ELSE 0 END,
                groups.user_order ASC,
                groups.provider_order ASC,
                CASE WHEN channels.user_order IS NULL THEN 1 ELSE 0 END,
                channels.user_order ASC,
                channels.provider_order ASC
            """
        ).fetchall()

    return [dict(r) for r in rows]


def epgshare_matches() -> dict[str, Any]:
    ensure_epgshare_tables()
    selected = selected_channels_for_epgshare()

    matches = []
    unmatched = []
    required_sources: dict[str, dict[str, Any]] = {}

    with connect() as conn:
        for channel in selected:
            tvg_id = (channel.get("tvg_id") or "").strip()
            if not tvg_id:
                unmatched.append({**channel, "reason": "missing tvg_id"})
                continue

            rows = conn.execute(
                """
                SELECT
                    epgshare_channel_index.xmltv_id,
                    epgshare_channel_index.source_key,
                    epgshare_sources.txt_url,
                    epgshare_sources.xml_url
                FROM epgshare_channel_index
                JOIN epgshare_sources ON epgshare_sources.source_key = epgshare_channel_index.source_key
                WHERE epgshare_channel_index.normalized_xmltv_id = ?
                ORDER BY epgshare_channel_index.source_key
                """,
                (normalize_xmltv_id(tvg_id),),
            ).fetchall()

            if not rows:
                unmatched.append({**channel, "reason": "tvg_id not found in epgshare index"})
                continue

            row_dicts = [dict(r) for r in rows]
            matches.append({
                **channel,
                "match_type": "exact_normalized_tvg_id",
                "epgshare_matches": row_dicts,
            })

            for row in row_dicts:
                source_key = row["source_key"]
                if source_key not in required_sources:
                    required_sources[source_key] = {
                        "source_key": source_key,
                        "txt_url": row["txt_url"],
                        "xml_url": row["xml_url"],
                        "matched_channel_count": 0,
                        "matched_xmltv_ids": [],
                    }
                required_sources[source_key]["matched_channel_count"] += 1
                if row["xmltv_id"] not in required_sources[source_key]["matched_xmltv_ids"]:
                    required_sources[source_key]["matched_xmltv_ids"].append(row["xmltv_id"])

    return {
        "ok": True,
        "selected_channel_count": len(selected),
        "matched_channel_count": len(matches),
        "unmatched_channel_count": len(unmatched),
        "required_source_count": len(required_sources),
        "required_sources": sorted(required_sources.values(), key=lambda r: r["source_key"]),
        "matches": matches,
        "unmatched": unmatched,
    }

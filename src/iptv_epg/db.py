from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .settings import DB_PATH, ensure_runtime_dirs


SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS m3u_sources (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        url TEXT,
        local_path TEXT,
        size_bytes INTEGER,
        md5 TEXT,
        sha256 TEXT,
        fetched_at TEXT,
        indexed_at TEXT,
        channel_count INTEGER NOT NULL DEFAULT 0,
        group_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS groups (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        provider_order INTEGER NOT NULL,
        user_order INTEGER,
        channel_count INTEGER NOT NULL DEFAULT 0,
        selected_count INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        missing INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_groups_order
    ON groups(missing, selected_count DESC, user_order, provider_order)
    """,
    """
    CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY,
        stable_key TEXT NOT NULL UNIQUE,
        group_id TEXT NOT NULL REFERENCES groups(id),
        name TEXT NOT NULL,
        tvg_name TEXT,
        tvg_id TEXT,
        logo_url TEXT,
        stream_url TEXT NOT NULL,
        extinf TEXT NOT NULL,
        provider_order INTEGER NOT NULL,
        user_order INTEGER,
        selected INTEGER NOT NULL DEFAULT 0,
        epg_xmltv_id TEXT,
        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        missing INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_channels_group_order
    ON channels(group_id, missing, selected DESC, user_order, provider_order)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_channels_selected
    ON channels(selected, missing)
    """,
    """
    CREATE TABLE IF NOT EXISTS epg_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        source_type TEXT NOT NULL DEFAULT 'manual',
        last_tested_at TEXT,
        last_channel_count INTEGER,
        last_match_count INTEGER,
        last_error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS epg_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES epg_sources(id) ON DELETE CASCADE,
        xmltv_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_id, xmltv_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS epg_mappings (
        channel_id TEXT PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
        source_id INTEGER REFERENCES epg_sources(id) ON DELETE SET NULL,
        xmltv_id TEXT,
        mapping_type TEXT NOT NULL DEFAULT 'auto',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT,
        progress_current INTEGER,
        progress_total INTEGER,
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TEXT,
        error TEXT
    )
    """,
)


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_runtime_dirs()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (1,))
        conn.execute("INSERT OR IGNORE INTO m3u_sources(id) VALUES (1)")
        conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        conn.commit()


def refresh_group_selected_counts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE groups
        SET selected_count = (
            SELECT COUNT(*)
            FROM channels
            WHERE channels.group_id = groups.id
              AND channels.selected = 1
              AND channels.missing = 0
        )
        """
    )


def get_status(app_version: str) -> dict[str, Any]:
    with connect() as conn:
        source = conn.execute(
            "SELECT url, local_path, size_bytes, md5, sha256, fetched_at, indexed_at, channel_count, group_count, last_error FROM m3u_sources WHERE id = 1"
        ).fetchone()
        selected = conn.execute(
            "SELECT COUNT(*) AS c FROM channels WHERE selected = 1 AND missing = 0"
        ).fetchone()["c"]
        groups_with_selected = conn.execute(
            "SELECT COUNT(*) AS c FROM groups WHERE selected_count > 0 AND missing = 0"
        ).fetchone()["c"]

    source_dict = row_to_dict(source) or {}
    return {
        "ok": True,
        "app": "iptv_epg",
        "version": app_version,
        "source": source_dict,
        "channel_count": int(source_dict.get("channel_count") or 0),
        "group_count": int(source_dict.get("group_count") or 0),
        "selected_count": int(selected),
        "groups_with_selected": int(groups_with_selected),
        "indexed_at": source_dict.get("indexed_at"),
        "last_error": source_dict.get("last_error"),
    }


def create_job(job_id: str, job_type: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs(id, job_type, status, message, progress_current, progress_total)
            VALUES (?, ?, 'running', ?, 0, NULL)
            """,
            (job_id, job_type, message),
        )
        conn.commit()


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    message: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
    error: str | None = None,
    finish: bool = False,
) -> None:
    fields: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if message is not None:
        fields.append("message = ?")
        values.append(message)
    if progress_current is not None:
        fields.append("progress_current = ?")
        values.append(progress_current)
    if progress_total is not None:
        fields.append("progress_total = ?")
        values.append(progress_total)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if finish:
        fields.append("finished_at = CURRENT_TIMESTAMP")

    values.append(job_id)

    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()


def get_job(job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_dict(row)


def get_groups() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                name,
                provider_order,
                user_order,
                channel_count,
                selected_count,
                missing
            FROM groups
            WHERE missing = 0
            ORDER BY
                CASE WHEN selected_count > 0 THEN 0 ELSE 1 END,
                CASE WHEN user_order IS NULL THEN 1 ELSE 0 END,
                user_order ASC,
                provider_order ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_channels(group_id: str, offset: int = 0, limit: int = 200) -> dict[str, Any]:
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)

    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM channels WHERE group_id = ? AND missing = 0",
            (group_id,),
        ).fetchone()["c"]
        rows = conn.execute(
            """
            SELECT
                id,
                stable_key,
                group_id,
                name,
                tvg_name,
                tvg_id,
                logo_url,
                provider_order,
                user_order,
                selected,
                epg_xmltv_id
            FROM channels
            WHERE group_id = ? AND missing = 0
            ORDER BY
                selected DESC,
                CASE WHEN user_order IS NULL THEN 1 ELSE 0 END,
                user_order ASC,
                provider_order ASC
            LIMIT ? OFFSET ?
            """,
            (group_id, limit, offset),
        ).fetchall()

    return {
        "group_id": group_id,
        "offset": offset,
        "limit": limit,
        "total": int(total),
        "channels": [dict(r) for r in rows],
    }


def set_channels_selected(channel_ids: list[str], selected: bool) -> dict[str, int]:
    if not channel_ids:
        return {"updated": 0}

    value = 1 if selected else 0

    with connect() as conn:
        conn.executemany(
            "UPDATE channels SET selected = ? WHERE id = ? AND missing = 0",
            [(value, channel_id) for channel_id in channel_ids],
        )
        updated = conn.total_changes
        refresh_group_selected_counts(conn)
        conn.commit()

    return {"updated": int(updated)}


def set_group_selected(group_id: str, selected: bool) -> dict[str, int]:
    value = 1 if selected else 0

    with connect() as conn:
        conn.execute(
            "UPDATE channels SET selected = ? WHERE group_id = ? AND missing = 0",
            (value, group_id),
        )
        updated = conn.total_changes
        refresh_group_selected_counts(conn)
        conn.commit()

    return {"updated": int(updated)}


def get_selected_channels() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                channels.id,
                channels.stable_key,
                channels.group_id,
                groups.name AS group_name,
                channels.name,
                channels.tvg_name,
                channels.tvg_id,
                channels.logo_url,
                channels.stream_url,
                channels.extinf,
                groups.provider_order AS group_provider_order,
                groups.user_order AS group_user_order,
                channels.provider_order,
                channels.user_order,
                channels.epg_xmltv_id
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

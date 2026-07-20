from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .settings import DB_PATH, ensure_runtime_dirs


SQLITE_TIMEOUT_SECONDS = 60.0
SQLITE_BUSY_TIMEOUT_MS = 60000


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
        preferred_logo_url TEXT,
        stream_url TEXT NOT NULL,
        extinf TEXT NOT NULL,
        provider_order INTEGER NOT NULL,
        user_order INTEGER,
        selected INTEGER NOT NULL DEFAULT 0,
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
    conn = sqlite3.connect(
        path,
        timeout=SQLITE_TIMEOUT_SECONDS,
        check_same_thread=False,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def ensure_runtime_schema(conn: sqlite3.Connection) -> None:
    """Apply lightweight schema updates for existing runtime databases."""
    channel_columns = {row["name"] for row in conn.execute("PRAGMA table_info(channels)").fetchall()}
    if "preferred_logo_url" not in channel_columns:
        conn.execute("ALTER TABLE channels ADD COLUMN preferred_logo_url TEXT")


def init_db(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in SCHEMA:
                conn.execute(statement)
            ensure_runtime_schema(conn)
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (1,))
            conn.execute("INSERT OR IGNORE INTO m3u_sources(id) VALUES (1)")
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def normalise_tvg_id(value: str | None) -> str:
    return "".join(str(value or "").strip().lower().split())


def apply_inherited_preferred_logos(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred_by_tvg_id: dict[str, str] = {}
    keys_needing_lookup: set[str] = set()
    channel_ids: list[str] = []

    for row in rows:
        key = normalise_tvg_id(row.get("tvg_id"))
        preferred = (row.get("preferred_logo_url") or "").strip()
        channel_id = str(row.get("channel_id") or row.get("id") or "").strip()
        if channel_id:
            channel_ids.append(channel_id)
        if key and preferred and key not in preferred_by_tvg_id:
            preferred_by_tvg_id[key] = preferred
        elif key:
            keys_needing_lookup.add(key)

    missing_keys = sorted(keys_needing_lookup - set(preferred_by_tvg_id.keys()))
    if missing_keys:
        placeholders = ",".join("?" for _ in missing_keys)
        with connect() as conn:
            lookup_rows = conn.execute(
                f"""
                SELECT tvg_id, preferred_logo_url
                FROM channels
                WHERE missing = 0
                  AND preferred_logo_url IS NOT NULL
                  AND preferred_logo_url != ''
                  AND LOWER(REPLACE(tvg_id, ' ', '')) IN ({placeholders})
                """,
                missing_keys,
            ).fetchall()

        for lookup in lookup_rows:
            key = normalise_tvg_id(lookup["tvg_id"])
            preferred = (lookup["preferred_logo_url"] or "").strip()
            if key and preferred and key not in preferred_by_tvg_id:
                preferred_by_tvg_id[key] = preferred

    guide_id_by_channel_id: dict[str, str] = {}
    preferred_by_guide_id: dict[str, str] = {}
    if channel_ids:
        placeholders = ",".join("?" for _ in channel_ids)
        try:
            with connect() as conn:
                mapping_rows = conn.execute(
                    f"""
                    SELECT channel_id, xmltv_id
                    FROM epgshare_mappings
                    WHERE ignored = 0
                      AND xmltv_id IS NOT NULL
                      AND xmltv_id != ''
                      AND channel_id IN ({placeholders})
                    """,
                    channel_ids,
                ).fetchall()

                guide_id_by_channel_id = {
                    str(row["channel_id"]): str(row["xmltv_id"])
                    for row in mapping_rows
                    if row["channel_id"] and row["xmltv_id"]
                }
                guide_ids = sorted(set(guide_id_by_channel_id.values()))

                if guide_ids:
                    guide_placeholders = ",".join("?" for _ in guide_ids)
                    logo_rows = conn.execute(
                        f"""
                        SELECT epgshare_mappings.xmltv_id, channels.preferred_logo_url
                        FROM epgshare_mappings
                        JOIN channels ON channels.id = epgshare_mappings.channel_id
                        WHERE epgshare_mappings.ignored = 0
                          AND epgshare_mappings.xmltv_id IN ({guide_placeholders})
                          AND channels.missing = 0
                          AND channels.preferred_logo_url IS NOT NULL
                          AND channels.preferred_logo_url != ''
                        ORDER BY epgshare_mappings.updated_at DESC
                        """,
                        guide_ids,
                    ).fetchall()

                    for logo_row in logo_rows:
                        guide_id = str(logo_row["xmltv_id"] or "").strip()
                        preferred = str(logo_row["preferred_logo_url"] or "").strip()
                        if guide_id and preferred and guide_id not in preferred_by_guide_id:
                            preferred_by_guide_id[guide_id] = preferred
        except sqlite3.Error:
            guide_id_by_channel_id = {}
            preferred_by_guide_id = {}

    for row in rows:
        key = normalise_tvg_id(row.get("tvg_id"))
        channel_id = str(row.get("channel_id") or row.get("id") or "").strip()
        guide_id = guide_id_by_channel_id.get(channel_id)
        inherited = preferred_by_tvg_id.get(key) or preferred_by_guide_id.get(guide_id or "")
        if not inherited or row.get("preferred_logo_url"):
            continue

        row["preferred_logo_url"] = inherited
        row["logo_url"] = inherited
        row["effective_logo_url"] = inherited

    return rows


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def get_settings(keys: list[str] | tuple[str, ...] | set[str] | None = None) -> dict[str, str]:
    with connect() as conn:
        if keys is None:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        else:
            cleaned = sorted({key for key in keys if key})
            if not cleaned:
                return {}
            placeholders = ",".join("?" for _ in cleaned)
            rows = conn.execute(
                f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
                cleaned,
            ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
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
        except Exception:
            conn.rollback()
            raise


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
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO jobs(id, job_type, status, message, progress_current, progress_total)
                VALUES (?, ?, 'running', ?, 0, NULL)
                """,
                (job_id, job_type, message),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


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
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


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
                logo_url AS default_logo_url,
                preferred_logo_url,
                COALESCE(NULLIF(preferred_logo_url, ''), logo_url) AS logo_url,
                COALESCE(NULLIF(preferred_logo_url, ''), logo_url) AS effective_logo_url,
                provider_order,
                user_order,
                selected
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

    rows = apply_inherited_preferred_logos([dict(r) for r in rows])

    return {
        "group_id": group_id,
        "offset": offset,
        "limit": limit,
        "total": int(total),
        "channels": rows,
    }


def set_channels_selected(channel_ids: list[str], selected: bool) -> dict[str, int]:
    if not channel_ids:
        return {"updated": 0}

    value = 1 if selected else 0

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = conn.total_changes

            if selected:
                rows = conn.execute(
                    """
                    SELECT id, group_id, selected, user_order, provider_order
                    FROM channels
                    WHERE id IN ({placeholders}) AND missing = 0
                    ORDER BY group_id, provider_order ASC
                    """.format(placeholders=",".join("?" for _ in channel_ids)),
                    channel_ids,
                ).fetchall()

                next_order_by_group: dict[str, int] = {}

                for row in rows:
                    group_id = row["group_id"]

                    if group_id not in next_order_by_group:
                        # Normalise the existing selected block first. Older
                        # selections may have NULL user_order values; if we only
                        # give the newly selected channel a user_order, the UI
                        # sort places it above the NULL-ordered existing
                        # selections. Assigning stable orders to the existing
                        # selected channels preserves their current/provider
                        # order and lets new selections append to the bottom.
                        existing_selected = conn.execute(
                            """
                            SELECT id
                            FROM channels
                            WHERE group_id = ?
                              AND selected = 1
                              AND missing = 0
                            ORDER BY
                              CASE WHEN user_order IS NULL THEN 1 ELSE 0 END,
                              user_order ASC,
                              provider_order ASC
                            """,
                            (group_id,),
                        ).fetchall()

                        next_order = 0
                        for existing in existing_selected:
                            conn.execute(
                                "UPDATE channels SET user_order = ? WHERE id = ? AND missing = 0",
                                (next_order, existing["id"]),
                            )
                            next_order += 1

                        next_order_by_group[group_id] = next_order

                    # Existing selected channels keep their normalised order.
                    # Newly selected channels are appended to the bottom of the
                    # selected block so existing user ordering is preserved.
                    if int(row["selected"] or 0) == 0:
                        conn.execute(
                            "UPDATE channels SET selected = 1, user_order = ? WHERE id = ? AND missing = 0",
                            (next_order_by_group[group_id], row["id"]),
                        )
                        next_order_by_group[group_id] += 1
                    else:
                        conn.execute(
                            "UPDATE channels SET selected = 1 WHERE id = ? AND missing = 0",
                            (row["id"],),
                        )
            else:
                conn.executemany(
                    "UPDATE channels SET selected = ? WHERE id = ? AND missing = 0",
                    [(value, channel_id) for channel_id in channel_ids],
                )

            refresh_group_selected_counts(conn)
            updated = conn.total_changes - before
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {"updated": int(updated)}


def set_group_selected(group_id: str, selected: bool) -> dict[str, int]:
    value = 1 if selected else 0

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = conn.total_changes
            conn.execute(
                "UPDATE channels SET selected = ? WHERE group_id = ? AND missing = 0",
                (value, group_id),
            )
            refresh_group_selected_counts(conn)
            updated = conn.total_changes - before
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {"updated": int(updated)}


def set_group_order(group_ids: list[str]) -> dict[str, int]:
    cleaned = [gid for gid in group_ids if gid]
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = conn.total_changes
            for order, group_id in enumerate(cleaned):
                conn.execute(
                    """
                    UPDATE groups
                    SET user_order = ?
                    WHERE id = ?
                      AND missing = 0
                      AND selected_count > 0
                    """,
                    (order, group_id),
                )
            updated = conn.total_changes - before
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"updated": int(updated)}


def set_channel_order(group_id: str, channel_ids: list[str]) -> dict[str, int]:
    cleaned = [cid for cid in channel_ids if cid]
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = conn.total_changes
            for order, channel_id in enumerate(cleaned):
                conn.execute(
                    """
                    UPDATE channels
                    SET user_order = ?
                    WHERE id = ?
                      AND group_id = ?
                      AND selected = 1
                      AND missing = 0
                    """,
                    (order, channel_id, group_id),
                )
            updated = conn.total_changes - before
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"updated": int(updated)}


def set_channel_preferred_logo(channel_id: str, preferred_logo_url: str | None) -> dict[str, Any]:
    cleaned = (preferred_logo_url or "").strip() or None

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            source = conn.execute(
                """
                SELECT id, tvg_id
                FROM channels
                WHERE id = ?
                  AND missing = 0
                """,
                (channel_id,),
            ).fetchone()

            if not source:
                conn.commit()
                return {"updated": 0, "channel_id": channel_id}

            tvg_id_key = normalise_tvg_id(source["tvg_id"])
            before = conn.total_changes
            if tvg_id_key:
                channel_rows = conn.execute(
                    """
                    SELECT id, tvg_id
                    FROM channels
                    WHERE missing = 0
                    """,
                ).fetchall()
                target_channel_ids = [
                    row["id"]
                    for row in channel_rows
                    if normalise_tvg_id(row["tvg_id"]) == tvg_id_key
                ]
            else:
                target_channel_ids = [channel_id]

            if target_channel_ids:
                placeholders = ",".join("?" for _ in target_channel_ids)
                conn.execute(
                    f"""
                    UPDATE channels
                    SET preferred_logo_url = ?
                    WHERE id IN ({placeholders})
                      AND missing = 0
                    """,
                    (cleaned, *target_channel_ids),
                )

            row = conn.execute(
                """
                SELECT
                    id AS channel_id,
                    tvg_id,
                    logo_url AS default_logo_url,
                    preferred_logo_url,
                    COALESCE(NULLIF(preferred_logo_url, ''), logo_url) AS effective_logo_url
                FROM channels
                WHERE id = ?
                  AND missing = 0
                """,
                (channel_id,),
            ).fetchone()
            updated = conn.total_changes - before
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    if not row:
        return {"updated": 0, "channel_id": channel_id}

    result = dict(row)
    result["updated"] = int(updated)
    return result


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
                channels.logo_url AS default_logo_url,
                channels.preferred_logo_url,
                COALESCE(NULLIF(channels.preferred_logo_url, ''), channels.logo_url) AS logo_url,
                COALESCE(NULLIF(channels.preferred_logo_url, ''), channels.logo_url) AS effective_logo_url,
                channels.stream_url,
                channels.extinf,
                groups.provider_order AS group_provider_order,
                groups.user_order AS group_user_order,
                channels.provider_order,
                channels.user_order
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

    return apply_inherited_preferred_logos([dict(r) for r in rows])

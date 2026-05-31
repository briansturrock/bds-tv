from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .settings import DB_PATH, ensure_runtime_dirs


SCHEMA: tuple[str, ...] = (
    '''
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''',
    '''
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
    ''',
    '''
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
    ''',
    '''
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
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_channels_group_order
    ON channels(group_id, selected DESC, user_order, provider_order)
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_channels_selected
    ON channels(selected)
    ''',
    '''
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
    ''',
    '''
    CREATE TABLE IF NOT EXISTS epg_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES epg_sources(id) ON DELETE CASCADE,
        xmltv_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_id, xmltv_id)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS epg_mappings (
        channel_id TEXT PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
        source_id INTEGER REFERENCES epg_sources(id) ON DELETE SET NULL,
        xmltv_id TEXT,
        mapping_type TEXT NOT NULL DEFAULT 'auto',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''',
    '''
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
    ''',
)


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_runtime_dirs()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (1,),
        )
        conn.commit()


def get_status() -> dict:
    with connect() as conn:
        source = conn.execute("SELECT channel_count, group_count, indexed_at, last_error FROM m3u_sources WHERE id = 1").fetchone()
        selected = conn.execute("SELECT COUNT(*) AS c FROM channels WHERE selected = 1 AND missing = 0").fetchone()["c"]
        groups_with_selected = conn.execute("SELECT COUNT(*) AS c FROM groups WHERE selected_count > 0 AND missing = 0").fetchone()["c"]

    return {
        "channel_count": int(source["channel_count"]) if source else 0,
        "group_count": int(source["group_count"]) if source else 0,
        "selected_count": int(selected),
        "groups_with_selected": int(groups_with_selected),
        "indexed_at": source["indexed_at"] if source else None,
        "last_error": source["last_error"] if source else None,
    }

from __future__ import annotations

import gzip
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests

from .db import connect, update_job


EPGSHARE_BASE_URL = "https://epgshare01.online/epgshare01"
EPGSHARE_ALL_SOURCES_URL = f"{EPGSHARE_BASE_URL}/epg_ripper_ALL_SOURCES1.txt"

SECTION_RE = re.compile(r"^\s*--\s*(epg_ripper_[A-Za-z0-9_]+)\s*--\s*$")

COUNTRY_ALIASES = {
    # Small generic alias layer only. This is country normalisation, not
    # source-specific matching logic.
    "GB": "UK",
    "GBR": "UK",
    "USA": "US",
    "CAN": "CA",
    "FRA": "FR",
}

COUNTRY_DISPLAY_WORDS = {
    # Optional display-word noise. These are not source-specific mappings.
    # The important country handling is generic code/suffix parsing below.
    "UK": {"uk", "gb", "britain", "unitedkingdom"},
    "US": {"us", "usa", "america", "unitedstates"},
    "CA": {"ca", "canada", "canadian"},
    "FR": {"fr", "france", "french"},
}

NOISE_TOKENS = {
    "hd", "fhd", "uhd", "sd", "hevc", "4k", "raw", "60fps", "vip",
    "channel", "tv", "live", "backup", "plus", "fhdhd",
}

NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


@dataclass(frozen=True)
class EpgshareEntry:
    source_key: str
    xmltv_id: str


def normalize_xmltv_id(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "", value)
    return value


def canonical_group_country(group_name: str | None) -> str | None:
    if not group_name or "|" not in group_name:
        return None
    raw = group_name.split("|", 1)[0].strip().upper()
    raw = re.sub(r"[^A-Z]", "", raw)
    return COUNTRY_ALIASES.get(raw, raw) if raw else None


def country_token_variants(country: str | None) -> set[str]:
    """Return generic country code token variants for suffix stripping.

    This handles cases like .ca, .ca2, .us2, .fr without hardcoding source names.
    """
    if not country:
        return set()

    country = COUNTRY_ALIASES.get(country.upper(), country.upper())
    variants = {country.lower()}

    # Alias variants are still generic country normalisation.
    for raw, canonical in COUNTRY_ALIASES.items():
        if canonical == country:
            variants.add(raw.lower())

    variants.update(COUNTRY_DISPLAY_WORDS.get(country, set()))
    return variants


def strip_country_suffix_token(token: str, country: str | None) -> str:
    """Remove a country suffix from a token when it matches the selected country.

    Examples:
    ca2 -> ''
    us2 -> ''
    fr  -> ''

    This is driven by the channel's selected group country, not by hardcoded
    source-specific country lists.
    """
    token = token.lower()
    variants = country_token_variants(country)

    for variant in variants:
        if token == variant:
            return ""
        if re.fullmatch(rf"{re.escape(variant)}\d+", token):
            return ""

    return token


def source_key_country(source_key: str | None) -> str | None:
    if not source_key:
        return None

    # Generic EPGShare convention:
    # epg_ripper_ + country/source letters + optional trailing source number.
    #
    # Do this in two explicit steps rather than relying on a regex capture,
    # because non-greedy regexes can be easy to misread and this must be
    # globally reliable for any country/source code.
    prefix = "EPG_RIPPER_"
    value = source_key.strip().upper()

    if not value.startswith(prefix):
        return None

    raw = value[len(prefix):]
    raw = re.sub(r"\d+$", "", raw)
    raw = re.sub(r"[^A-Z]", "", raw)

    if not raw:
        return None

    return COUNTRY_ALIASES.get(raw, raw)


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS epgshare_mappings (
                    channel_id TEXT PRIMARY KEY,
                    xmltv_id TEXT,
                    source_key TEXT,
                    mapping_type TEXT NOT NULL DEFAULT 'manual',
                    confidence REAL,
                    ignored INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_epgshare_mappings_source
                ON epgshare_mappings(source_key)
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
                channels.logo_url AS default_logo_url,
                channels.preferred_logo_url,
                COALESCE(NULLIF(channels.preferred_logo_url, ''), channels.logo_url) AS logo_url,
                COALESCE(NULLIF(channels.preferred_logo_url, ''), channels.logo_url) AS effective_logo_url,
                channels.user_order AS channel_user_order,
                channels.provider_order AS channel_provider_order,
                groups.id AS group_id,
                groups.name AS group_name,
                groups.user_order AS group_user_order,
                groups.provider_order AS group_provider_order
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


def tokenize_epg_id(value: str | None) -> list[str]:
    value = (value or "").lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    raw_tokens = [t for t in value.split() if t]

    tokens: list[str] = []
    for token in raw_tokens:
        token = NUMBER_WORDS.get(token, token)
        tokens.append(token)

    return tokens


def compact_core(value: str | None, country: str | None = None) -> str:
    tokens = tokenize_epg_id(value)

    kept: list[str] = []
    for token in tokens:
        token = strip_country_suffix_token(token, country)
        if not token:
            continue

        token_without_digits = re.sub(r"\d+$", "", token)

        if token in NOISE_TOKENS or token_without_digits in NOISE_TOKENS:
            continue

        # Number words are already normalised by tokenize_epg_id.
        kept.append(token)

    return "".join(kept)


def positive_match_score(channel_core: str, epg_core: str, country_match: bool) -> tuple[float, str]:
    """Score by positive evidence only.

    No negative assumptions are made about tokens like R1/R2. Better matches
    simply receive stronger positive scores.
    """
    if not channel_core or not epg_core:
        return 0.0, "no useful similarity"

    boost = 0.04 if country_match else 0.0

    if channel_core == epg_core:
        return min(0.97, 0.93 + boost), "compact id match"

    # Strong directional evidence. This should let BBC1 rank BBC.One... above
    # weaker fuzzy lookalikes after number-word normalisation.
    if epg_core.startswith(channel_core):
        return min(0.95, 0.91 + boost), "compact prefix match"

    if channel_core.startswith(epg_core) and len(epg_core) >= 3:
        return min(0.90, 0.86 + boost), "reverse compact prefix match"

    if len(channel_core) >= 3 and channel_core in epg_core:
        return min(0.90, 0.86 + boost), "compact containment"

    if len(epg_core) >= 3 and epg_core in channel_core:
        return min(0.84, 0.80 + boost), "reverse compact containment"

    ratio = SequenceMatcher(None, channel_core, epg_core).ratio()
    return min(0.89, ratio + boost), "fuzzy compact id"


def country_source_patterns(country: str | None) -> list[str]:
    if not country:
        return []
    country = COUNTRY_ALIASES.get(country.upper(), country.upper())
    candidates = [country]
    if country == "UK":
        candidates.append("GB")
    return [f"epg_ripper_{c}%" for c in candidates]


def candidate_rows_for_channel(conn, channel: dict[str, Any], limit: int = 500) -> list[dict[str, Any]]:
    country = canonical_group_country(channel.get("group_name"))
    tvg_id = channel.get("tvg_id") or ""
    name = channel.get("name") or ""
    tvg_name = channel.get("tvg_name") or ""

    core_values = {
        compact_core(tvg_id, country),
        compact_core(name, country),
        compact_core(tvg_name, country),
    }
    core_values = {v for v in core_values if len(v) >= 2}

    source_patterns = country_source_patterns(country)
    source_clause = ""
    params: list[Any] = []

    if source_patterns:
        source_clause = "AND (" + " OR ".join(["epgshare_channel_index.source_key LIKE ?" for _ in source_patterns]) + ")"
        params.extend(source_patterns)

    # Start country-scoped. This keeps suggestions sane and avoids comparing every
    # selected channel against the entire global EPGShare index.
    rows = conn.execute(
        f"""
        SELECT
            epgshare_channel_index.xmltv_id,
            epgshare_channel_index.source_key,
            epgshare_sources.txt_url,
            epgshare_sources.xml_url
        FROM epgshare_channel_index
        JOIN epgshare_sources ON epgshare_sources.source_key = epgshare_channel_index.source_key
        WHERE 1 = 1
        {source_clause}
        ORDER BY epgshare_channel_index.source_key, epgshare_channel_index.xmltv_id
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()

    # If a group prefix is unusual or unmapped, fall back to exact normalized lookup.
    if not rows and tvg_id:
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
            LIMIT ?
            """,
            (normalize_xmltv_id(tvg_id), limit),
        ).fetchall()

    return [dict(r) for r in rows]


def score_epgshare_candidate(channel: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    country = canonical_group_country(channel.get("group_name"))
    source_country = source_key_country(candidate.get("source_key"))
    country_match = bool(country and source_country and country == source_country)

    tvg_id = channel.get("tvg_id") or ""
    xmltv_id = candidate.get("xmltv_id") or ""

    if normalize_xmltv_id(tvg_id) and normalize_xmltv_id(tvg_id) == normalize_xmltv_id(xmltv_id):
        return {
            "confidence": 1.0,
            "reason": "exact normalized tvg-id",
            "country_match": country_match,
        }

    channel_cores = [
        compact_core(tvg_id, country),
        compact_core(channel.get("name"), country),
        compact_core(channel.get("tvg_name"), country),
    ]
    channel_cores = [v for v in channel_cores if len(v) >= 2]

    epg_core = compact_core(xmltv_id, country)

    best = 0.0
    reason = "no useful similarity"

    for channel_core in channel_cores:
        score, score_reason = positive_match_score(channel_core, epg_core, country_match)
        if score > best:
            best = score
            reason = ("country-scoped " if country_match else "") + score_reason

    return {
        "confidence": round(best, 3),
        "reason": reason,
        "country_match": country_match,
    }


def best_epgshare_suggestions(conn, channel: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    candidates = candidate_rows_for_channel(conn, channel)
    scored = []

    for candidate in candidates:
        score = score_epgshare_candidate(channel, candidate)
        confidence = score["confidence"]
        if confidence < 0.65:
            continue

        scored.append({
            **candidate,
            "confidence": confidence,
            "reason": score["reason"],
            "country_match": score["country_match"],
        })

    scored.sort(key=lambda r: (-r["confidence"], r["source_key"], r["xmltv_id"]))
    return scored[:limit]


def add_required_source(required_sources: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
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


def epgshare_matches() -> dict[str, Any]:
    ensure_epgshare_tables()
    selected = selected_channels_for_epgshare()

    exact_matches = []
    suggested_matches = []
    unmatched = []

    exact_required_sources: dict[str, dict[str, Any]] = {}
    suggested_required_sources: dict[str, dict[str, Any]] = {}

    with connect() as conn:
        for channel in selected:
            tvg_id = (channel.get("tvg_id") or "").strip()
            if not tvg_id:
                unmatched.append({**channel, "reason": "missing tvg_id"})
                continue

            exact_rows = conn.execute(
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

            if exact_rows:
                row_dicts = [dict(r) for r in exact_rows]
                exact_matches.append({
                    **channel,
                    "match_type": "exact_normalized_tvg_id",
                    "epgshare_matches": row_dicts,
                })

                for row in row_dicts:
                    add_required_source(exact_required_sources, row)
                continue

            suggestions = best_epgshare_suggestions(conn, channel)
            if suggestions:
                suggested_matches.append({
                    **channel,
                    "match_type": "suggested_country_aware",
                    "suggestions": suggestions,
                })
                for row in suggestions[:1]:
                    add_required_source(suggested_required_sources, row)
                continue

            unmatched.append({**channel, "reason": "no exact or suggested EPGShare match found"})

    # Build merged required_sources without mutating exact_required_sources or
    # suggested_required_sources.  A shallow dict copy reuses nested dictionaries,
    # which made exact_required_sources appear to contain suggested matches.
    all_required_sources = {
        source_key: {
            "source_key": source["source_key"],
            "txt_url": source["txt_url"],
            "xml_url": source["xml_url"],
            "matched_channel_count": source["matched_channel_count"],
            "matched_xmltv_ids": list(source["matched_xmltv_ids"]),
        }
        for source_key, source in exact_required_sources.items()
    }

    for source_key, source in suggested_required_sources.items():
        if source_key not in all_required_sources:
            all_required_sources[source_key] = {
                "source_key": source["source_key"],
                "txt_url": source["txt_url"],
                "xml_url": source["xml_url"],
                "matched_channel_count": source["matched_channel_count"],
                "matched_xmltv_ids": list(source["matched_xmltv_ids"]),
            }
            continue

        all_required_sources[source_key]["matched_channel_count"] += source["matched_channel_count"]
        for xmltv_id in source["matched_xmltv_ids"]:
            if xmltv_id not in all_required_sources[source_key]["matched_xmltv_ids"]:
                all_required_sources[source_key]["matched_xmltv_ids"].append(xmltv_id)

    return {
        "ok": True,
        "selected_channel_count": len(selected),
        "matched_channel_count": len(exact_matches),
        "suggested_channel_count": len(suggested_matches),
        "unmatched_channel_count": len(unmatched),
        "required_source_count": len(all_required_sources),
        "required_sources": sorted(all_required_sources.values(), key=lambda r: r["source_key"]),
        "exact_required_sources": sorted(exact_required_sources.values(), key=lambda r: r["source_key"]),
        "suggested_required_sources": sorted(suggested_required_sources.values(), key=lambda r: r["source_key"]),
        "matches": exact_matches,
        "suggestions": suggested_matches,
        "unmatched": unmatched,
    }


def epgshare_saved_mappings() -> list[dict[str, Any]]:
    ensure_epgshare_tables()

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                epgshare_mappings.channel_id,
                epgshare_mappings.xmltv_id,
                epgshare_mappings.source_key,
                epgshare_mappings.mapping_type,
                epgshare_mappings.confidence,
                epgshare_mappings.ignored,
                epgshare_mappings.notes,
                epgshare_mappings.updated_at,
                channels.name,
                channels.tvg_name,
                channels.tvg_id,
                groups.name AS group_name
            FROM epgshare_mappings
            LEFT JOIN channels ON channels.id = epgshare_mappings.channel_id
            LEFT JOIN groups ON groups.id = channels.group_id
            ORDER BY groups.name, channels.name
            """
        ).fetchall()

    return [dict(r) for r in rows]


def save_epgshare_mappings(mappings: list[dict[str, Any]]) -> dict[str, Any]:
    ensure_epgshare_tables()

    saved = 0
    ignored = 0

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for item in mappings:
                channel_id = (item.get("channel_id") or "").strip()
                if not channel_id:
                    continue

                is_ignored = 1 if item.get("ignored") else 0
                xmltv_id = item.get("xmltv_id")
                source_key = item.get("source_key")
                mapping_type = item.get("mapping_type") or ("ignored" if is_ignored else "manual")
                confidence = item.get("confidence")
                notes = item.get("notes")

                if is_ignored:
                    xmltv_id = None
                    source_key = None
                    ignored += 1
                else:
                    if not xmltv_id or not source_key:
                        continue
                    saved += 1

                conn.execute(
                    """
                    INSERT INTO epgshare_mappings(
                        channel_id,
                        xmltv_id,
                        source_key,
                        mapping_type,
                        confidence,
                        ignored,
                        notes,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        xmltv_id = excluded.xmltv_id,
                        source_key = excluded.source_key,
                        mapping_type = excluded.mapping_type,
                        confidence = excluded.confidence,
                        ignored = excluded.ignored,
                        notes = excluded.notes,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        channel_id,
                        xmltv_id,
                        source_key,
                        mapping_type,
                        confidence,
                        is_ignored,
                        notes,
                    ),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "ok": True,
        "received": len(mappings),
        "saved": saved,
        "ignored": ignored,
    }


def epgshare_mapping_review() -> dict[str, Any]:
    ensure_epgshare_tables()

    matches = epgshare_matches()
    saved = {row["channel_id"]: row for row in epgshare_saved_mappings()}

    rows = []

    for item in matches["matches"]:
        channel_id = item["channel_id"]
        exact = item.get("epgshare_matches", [])
        selected = saved.get(channel_id)

        rows.append({
            "channel_id": channel_id,
            "name": item.get("name"),
            "tvg_name": item.get("tvg_name"),
            "tvg_id": item.get("tvg_id"),
            "group_name": item.get("group_name"),
            "default_logo_url": item.get("default_logo_url"),
            "preferred_logo_url": item.get("preferred_logo_url"),
            "logo_url": item.get("logo_url"),
            "effective_logo_url": item.get("effective_logo_url"),
            "group_id": item.get("group_id"),
            "group_user_order": item.get("group_user_order"),
            "group_provider_order": item.get("group_provider_order"),
            "channel_user_order": item.get("channel_user_order"),
            "channel_provider_order": item.get("channel_provider_order"),
            "status": "saved" if selected else "exact",
            "saved_mapping": selected,
            "exact_matches": exact,
            "suggestions": exact,
            "recommended": exact[0] if exact else None,
        })

    for item in matches["suggestions"]:
        channel_id = item["channel_id"]
        suggestions = item.get("suggestions", [])
        selected = saved.get(channel_id)

        rows.append({
            "channel_id": channel_id,
            "name": item.get("name"),
            "tvg_name": item.get("tvg_name"),
            "tvg_id": item.get("tvg_id"),
            "group_name": item.get("group_name"),
            "default_logo_url": item.get("default_logo_url"),
            "preferred_logo_url": item.get("preferred_logo_url"),
            "logo_url": item.get("logo_url"),
            "effective_logo_url": item.get("effective_logo_url"),
            "group_id": item.get("group_id"),
            "group_user_order": item.get("group_user_order"),
            "group_provider_order": item.get("group_provider_order"),
            "channel_user_order": item.get("channel_user_order"),
            "channel_provider_order": item.get("channel_provider_order"),
            "status": "saved" if selected else "suggested",
            "saved_mapping": selected,
            "exact_matches": [],
            "suggestions": suggestions,
            "recommended": suggestions[0] if suggestions else None,
        })

    for item in matches["unmatched"]:
        channel_id = item["channel_id"]
        selected = saved.get(channel_id)

        rows.append({
            "channel_id": channel_id,
            "name": item.get("name"),
            "tvg_name": item.get("tvg_name"),
            "tvg_id": item.get("tvg_id"),
            "group_name": item.get("group_name"),
            "default_logo_url": item.get("default_logo_url"),
            "preferred_logo_url": item.get("preferred_logo_url"),
            "logo_url": item.get("logo_url"),
            "effective_logo_url": item.get("effective_logo_url"),
            "group_id": item.get("group_id"),
            "group_user_order": item.get("group_user_order"),
            "group_provider_order": item.get("group_provider_order"),
            "channel_user_order": item.get("channel_user_order"),
            "channel_provider_order": item.get("channel_provider_order"),
            "status": "saved" if selected else "unmatched",
            "saved_mapping": selected,
            "reason": item.get("reason"),
            "exact_matches": [],
            "suggestions": [],
            "recommended": None,
        })

    return {
        "ok": True,
        "summary": {
            "selected_channel_count": matches["selected_channel_count"],
            "exact_match_count": matches["matched_channel_count"],
            "suggested_match_count": matches["suggested_channel_count"],
            "unmatched_count": matches["unmatched_channel_count"],
            "saved_mapping_count": len(saved),
            "required_source_count": matches["required_source_count"],
        },
        "required_sources": matches["required_sources"],
        "rows": rows,
    }


def epgshare_active_mappings() -> list[dict[str, Any]]:
    ensure_epgshare_tables()

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                epgshare_mappings.channel_id,
                epgshare_mappings.xmltv_id,
                epgshare_mappings.source_key,
                epgshare_mappings.mapping_type,
                epgshare_mappings.confidence,
                epgshare_mappings.updated_at,
                channels.name,
                channels.tvg_name,
                channels.tvg_id,
                groups.name AS group_name,
                epgshare_sources.xml_url,
                epgshare_sources.txt_url
            FROM epgshare_mappings
            JOIN channels ON channels.id = epgshare_mappings.channel_id
            JOIN groups ON groups.id = channels.group_id
            JOIN epgshare_sources ON epgshare_sources.source_key = epgshare_mappings.source_key
            WHERE epgshare_mappings.ignored = 0
              AND epgshare_mappings.xmltv_id IS NOT NULL
              AND epgshare_mappings.source_key IS NOT NULL
              AND channels.selected = 1
              AND channels.missing = 0
              AND groups.missing = 0
            ORDER BY epgshare_mappings.source_key, channels.name
            """
        ).fetchall()

    return [dict(r) for r in rows]


def xmltv_time_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    match = re.match(r"^(\d{14})", value.strip())
    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def programme_in_window(elem: ET.Element, window_start: datetime, window_end: datetime) -> bool:
    start = xmltv_time_to_datetime(elem.attrib.get("start"))
    stop = xmltv_time_to_datetime(elem.attrib.get("stop"))

    if start is None and stop is None:
        return True

    if stop is not None and stop < window_start:
        return False

    if start is not None and start > window_end:
        return False

    return True


def download_to_tempfile(url: str) -> Path:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; iptv_epg/0.1)",
        "Accept": "application/gzip,application/xml,text/xml,*/*",
    }

    response = requests.get(url, stream=True, timeout=(20, 300), headers=headers)
    response.raise_for_status()

    fd, path = tempfile.mkstemp(prefix="epgshare_", suffix=".xml.gz")
    temp_path = Path(path)

    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    out.write(chunk)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise

    return temp_path


def rewrite_channel_element(mapping: dict[str, Any]) -> ET.Element:
    target_id = mapping.get("tvg_id") or mapping.get("xmltv_id")
    channel = ET.Element("channel", {"id": target_id})

    display = ET.SubElement(channel, "display-name")
    display.text = mapping.get("tvg_name") or mapping.get("name") or target_id

    if mapping.get("name") and mapping.get("name") != display.text:
        alt = ET.SubElement(channel, "display-name")
        alt.text = mapping["name"]

    return channel


def serialize_element(elem: ET.Element) -> str:
    return ET.tostring(elem, encoding="unicode", short_empty_elements=True)


def generate_filtered_epgshare(job_id: str | None = None, days: int = 3) -> dict[str, Any]:
    ensure_epgshare_tables()

    days = max(1, min(int(days), 14))
    mappings = epgshare_active_mappings()

    if not mappings:
        raise RuntimeError("No saved EPGShare mappings found. Review and save mappings before generating EPG.")

    by_source: dict[str, dict[str, Any]] = {}
    for mapping in mappings:
        source_key = mapping["source_key"]
        by_source.setdefault(
            source_key,
            {
                "source_key": source_key,
                "xml_url": mapping["xml_url"],
                "mappings": [],
            },
        )
        by_source[source_key]["mappings"].append(mapping)

    # Keep output location consistent with filtered.m3u and the existing
    # browser/download route expectations.
    output_dir = Path(os.environ.get("DATA_DIR", "/data"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "filtered_epg.xml"

    window_start = datetime.now(timezone.utc) - timedelta(hours=6)
    window_end = datetime.now(timezone.utc) + timedelta(days=days)

    source_total = len(by_source)
    programme_count = 0
    channel_count = 0
    downloaded_sources = []
    missing_channel_ids: list[dict[str, Any]] = []

    if job_id:
        update_job(
            job_id,
            message=f"Generating EPGShare filtered EPG from {source_total} XML.GZ source files",
            progress_current=0,
            progress_total=source_total,
        )

    with output_path.open("w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        out.write('<tv generator-info-name="iptv_epg EPGShare filtered">\n')

        # Emit channel definitions that match the IPTV M3U tvg-id values.
        for mapping in mappings:
            out.write(serialize_element(rewrite_channel_element(mapping)))
            out.write("\n")
            channel_count += 1

        for index, source in enumerate(sorted(by_source.values(), key=lambda s: s["source_key"]), start=1):
            source_key = source["source_key"]
            xml_url = source["xml_url"]

            if job_id:
                update_job(
                    job_id,
                    message=f"Downloading/parsing EPGShare source {index}/{source_total}: {source_key}",
                    progress_current=index - 1,
                    progress_total=source_total,
                )

            source_mappings = source["mappings"]
            source_xmltv_ids = {m["xmltv_id"] for m in source_mappings}
            target_by_xmltv_id = {
                m["xmltv_id"]: (m.get("tvg_id") or m["xmltv_id"])
                for m in source_mappings
            }

            temp_path = download_to_tempfile(xml_url)
            downloaded_sources.append({
                "source_key": source_key,
                "xml_url": xml_url,
                "mapping_count": len(source_mappings),
            })

            seen_channel_ids = set()

            try:
                with gzip.open(temp_path, "rb") as gz:
                    context = ET.iterparse(gz, events=("end",))
                    for _event, elem in context:
                        if elem.tag == "channel":
                            channel_id = elem.attrib.get("id")
                            if channel_id in source_xmltv_ids:
                                seen_channel_ids.add(channel_id)
                            elem.clear()
                            continue

                        # Do not clear child elements such as <title>, <desc>,
                        # <category>, etc. before the parent <programme> has been
                        # serialized. Clearing non-programme tags here strips useful
                        # guide data and produces empty programme elements.
                        if elem.tag != "programme":
                            continue

                        source_channel_id = elem.attrib.get("channel")
                        if source_channel_id not in source_xmltv_ids:
                            elem.clear()
                            continue

                        if not programme_in_window(elem, window_start, window_end):
                            elem.clear()
                            continue

                        elem.attrib["channel"] = target_by_xmltv_id[source_channel_id]
                        out.write(serialize_element(elem))
                        out.write("\n")
                        programme_count += 1
                        elem.clear()

                for xmltv_id in source_xmltv_ids - seen_channel_ids:
                    missing_channel_ids.append({
                        "source_key": source_key,
                        "xmltv_id": xmltv_id,
                    })
            finally:
                temp_path.unlink(missing_ok=True)

            if job_id:
                update_job(
                    job_id,
                    message=f"Parsed EPGShare source {index}/{source_total}: {source_key}",
                    progress_current=index,
                    progress_total=source_total,
                )

        out.write("</tv>\n")

    return {
        "ok": True,
        "output_path": str(output_path),
        "days": days,
        "source_count": source_total,
        "channel_count": channel_count,
        "programme_count": programme_count,
        "downloaded_sources": downloaded_sources,
        "missing_channel_ids": missing_channel_ids,
    }

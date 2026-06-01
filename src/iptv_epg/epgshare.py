from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

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

    all_required_sources = dict(exact_required_sources)
    for source_key, source in suggested_required_sources.items():
        if source_key not in all_required_sources:
            all_required_sources[source_key] = source
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

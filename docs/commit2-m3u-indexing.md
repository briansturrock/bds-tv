# Commit 2: M3U source fetch + SQLite indexing

## Goal

Add the backend-only foundation for source M3U handling.

The browser should never download or parse the source M3U.

## New endpoints

```text
GET  /api/settings
POST /api/settings
POST /api/m3u/fetch
GET  /api/jobs/{job_id}
GET  /api/source
GET  /api/groups
GET  /api/channels?group_id=...&offset=0&limit=200
```

## Data flow

```text
POST /api/m3u/fetch
→ backend downloads source M3U
→ saves /data/source/source.m3u
→ calculates md5/sha256/size
→ compares SHA256 with previous source
→ if unchanged, keeps existing index
→ if changed, parses and indexes groups/channels into SQLite
```

## Preserved state

When a source changes, existing rows are updated by stable channel key where possible.

The following fields are preserved if the channel still matches:

```text
selected
user_order
epg_xmltv_id
```

## Not included yet

- channel selection endpoints
- filtered M3U generation
- EPG management
- UI pages

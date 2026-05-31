# Architecture

## Principle

The UI is a thin API client. The backend owns all heavy work.

## Durable state

Durable state lives in SQLite:

```text
/db/iptv_epg.db
```

Includes:

- settings
- M3U source metadata and hashes
- groups
- channels
- selections
- ordering fields
- EPG source definitions
- EPG channel metadata
- EPG mappings
- jobs/progress

## Transient/generated files

Files under `/data`:

```text
/data/source/source.m3u
/data/filtered.m3u
/data/filtered_epg.xml
/data/epg_cache/*
/data/hls/*
```

EPG programme data is transient and should not initially be stored in SQLite.

## Ordering model

Ordering is single-source and driven by the Channels tab.

Groups:

1. groups with selected channels first;
2. then `groups.user_order`;
3. then `groups.provider_order`.

Channels:

1. selected channels first in the UI;
2. then `channels.user_order`;
3. then `channels.provider_order`.

Filtered M3U and Guide use the same ordering model.

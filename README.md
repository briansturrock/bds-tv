# iptv_epg

Self-hosted IPTV playlist and EPG manager.

The goal is to replace hosted playlist managers such as m3u4u with a local/internal app that:

- fetches a large upstream M3U playlist;
- lets you select channel groups/channels without arbitrary limits;
- generates a smaller `filtered.m3u`;
- detects/tests XMLTV sources;
- generates a filtered `filtered_epg.xml`;
- provides a Guide view and optional browser playback;
- keeps durable state in SQLite;
- keeps generated/transient files on disk.

## Current known-good runtime baseline

The last known-good image from the prototype phase was:

```text
iptv_epg:0.7.6.1-hls-tuned
```

This repository is now the source of truth for rebuilding the app properly.

## Design principles

1. Durable state lives in SQLite at `/db/iptv_epg.db`.
2. The browser UI is a thin API client only.
3. Heavy work is done server-side.
4. Generated/transient files live under `/data`.
5. The filtered M3U keeps original provider stream URLs by default.
6. Browser playback is a convenience feature, not the main architecture.

## Volumes

```text
/config  settings/config overrides
/data    source cache, filtered.m3u, filtered_epg.xml, hls temp files
/db      SQLite database
/logs    app logs
```

## Local run

```bash
docker compose up --build
```

Open:

```text
http://localhost:8088/health
```

## Production container

Suggested host layout:

```text
/docker/iptv_epg/config
/docker/iptv_epg/data
/docker/iptv_epg/db
/docker/iptv_epg/logs
/docker/iptv_epg/releases
```

Use explicit image tags in Portainer. Avoid relying on `latest`.

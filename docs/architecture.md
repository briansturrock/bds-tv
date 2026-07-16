# Architecture

## Principle

The UI is a thin API client. The backend owns downloads, parsing, matching, XMLTV generation, stream proxying, HDHR emulation, DLNA serving, scheduling, and diagnostics.

The selected channel catalogue is the source of truth. The filtered M3U, filtered XMLTV, Guide, HDHR lineup, HDHR XMLTV, and DLNA catalogue all derive from the same selected-channel configuration.

## Durable state

Durable state lives in SQLite:

```text
/db/iptv_epg.db
```

Includes:

- app settings;
- M3U source metadata and hashes;
- groups;
- channels;
- selections;
- ordering fields;
- EPGShare channel metadata;
- EPG mappings by `tvg-id`;
- preferred logo overrides;
- jobs/progress;
- scheduler state;
- HDHR/DLNA settings;
- killswitch settings.

## Generated and Transient Files

Files under `/data`:

```text
/data/source/source.m3u
/data/filtered.m3u
/data/filtered_epg.xml
/data/hdhr.m3u
/data/epg_cache/*
```

HLS preview files are created under `/tmp/iptv_epg_hls`.

Programme data is generated into XMLTV files rather than stored permanently as individual programme rows.

## Ordering Model

Ordering is driven by the Channels tab.

Groups:

1. groups with selected channels first;
2. then `groups.user_order`;
3. then `groups.provider_order`.

Channels:

1. selected channels first in the UI;
2. then `channels.user_order`;
3. then `channels.provider_order`.

Filtered M3U, Guide, HDHR, and DLNA use the same selected-channel ordering unless a feature deliberately applies its own filter, such as HDHR group exclusions.

## Streaming Architecture

`filtered.m3u` keeps provider stream URLs and is not a proxy playlist.

Proxy streaming is handled separately:

- HDHR exposes tuner-style endpoints for Plex and similar clients.
- DLNA exposes grouped media-server folders and stream URLs for VLC/TV clients.
- Guide previews use the app as a convenience stream path.

The stream safety layer enforces:

- maximum upstream stream count;
- conflict policy;
- idle and max-age cleanup;
- scheduled stream drops;
- killswitch blocking when the app public IP geolocates to the configured home country.

## Discovery

HDHR and DLNA share the SSDP listener. Depending on enabled settings, it responds with HDHR tuner discovery, DLNA media-server discovery, or both.

Host networking is used in Docker so multicast discovery works reliably on the LAN.

## Health

`/health` is a lightweight app health endpoint used by Docker healthcheck and external monitors.

`/health/deep` reports uptime, thread names, active proxy streams, SSDP state, and stream cleanup state for troubleshooting cases where the container is running but the app is not reachable.

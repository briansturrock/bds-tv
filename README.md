# iptv-epg

`iptv-epg` is a self-hosted IPTV playlist, EPG, streaming proxy, HDHomeRun emulator, and DLNA media server.

The original aim was to replace hosted playlist managers such as m3u4u with a local service. It now goes further than that: it creates curated M3U/XMLTV outputs, schedules EPG generation, exposes a usable guide, and can proxy streams for Plex, VLC, TVs, and other clients without those clients talking directly to the IPTV provider.

The app has several tabs in the main header: Settings, Channels, EPG, Scheduler, HDHR, DLNA, Guide, and Diagnostics.

## Settings

The Settings tab is the starting point.

Enter the IPTV provider's M3U URL. The app does not currently accept Xtream Codes directly, but Xtream details usually translate into an M3U URL.

For example, Xtream details like:

```text
server url: iptv.domain.com
username: username
password: password
```

usually translate approximately to:

```text
http://iptv.domain.com/get.php?username=username&password=password&type=m3u_plus&output=ts
```

The provider may supply the exact URL.

After pasting the URL:

1. Click **Save settings**.
2. Click **Fetch M3U / rebuild index**.

This downloads the provider playlist, parses groups and channels, and stores the channel catalogue in the database.

The header also shows the app's current public IPv4 address and country flag. This is useful because the Docker host normally routes via a VPN gateway.

### Streaming Killswitch

The Settings tab also includes a streaming killswitch.

Enter the two-letter ISO country code for the home country, in uppercase, and enable the killswitch. If the app's looked-up public IP geolocation matches that country, streaming through the app is blocked.

For example:

```text
Home country ISO code: GB
Killswitch enabled: yes
```

If the app public IP geolocates to `GB`, streaming via HDHR, DLNA, the guide preview, and raw stream endpoints is disabled. If the VPN route is restored and the public IP geolocates elsewhere, streaming is allowed again.

This is designed as an app-level safety net for cases where the host's default route accidentally falls back to the ISP router instead of the VPN gateway.

The public IP lookup can be refreshed from the API:

```bash
curl "http://localhost:8088/api/public-ip?refresh=true"
```

Refreshing the UI or saving Settings also forces a fresh lookup.

## Channels

The Channels tab is the m3u4u replacement.

Provider groups appear on the left. Selecting a group shows the channels in that group. No groups are selected by default, and the original provider ordering is preserved until the user changes it.

When a channel is selected, it moves into the selected section at the top of that group, without forcing the scroll position back to the top of the full channel list. This makes it easier to select multiple channels from large groups.

Selected groups and channels can be reordered using the arrow buttons. Changes are saved on the fly.

When selection is complete, click **Generate filtered M3U** to create the curated M3U. The **Open filtered.m3u** button opens the URL that IPTV clients can use.

Important: `filtered.m3u` is not a streaming proxy playlist. It contains the original IPTV provider stream URLs. It is suitable for IPTV apps, but at home it should be used with the VPN route in place. The proxy functions are handled separately by HDHR and DLNA.

## EPG

The EPG tab maps selected IPTV channels to EPGShare channel data.

The IPTV provider may include an XMLTV guide, but the app's preferred workflow is to build a cleaner XMLTV file from EPGShare for only the channels selected in the curated playlist.

First-time workflow:

1. Generate the filtered M3U from the Channels tab.
2. Click **Import/update EPGShare index**.
3. Review each selected channel.
4. Save the suggested match where correct.
5. Search manually where no good suggestion exists.
6. Optionally override logos.
7. Click **Generate filtered EPG**.

The app matches and stores EPG configuration by `tvg-id`, not merely by the individual channel row. This means that channels from different groups with the same `tvg-id` share the same EPG mapping and logo preference.

If a selected channel has no programme data, the generated guide now includes placeholder "Unknown" entries rather than leaving empty channels. This keeps the guide, HDHR XMLTV, and DLNA/HDHR channel lists consistent.

Useful logo source:

[tv-logo/tv-logos](https://github.com/tv-logo/tv-logos)

Generated output:

```text
/filtered_epg.xml
```

The filtered M3U and XMLTV can also be exposed externally, for example through a Cloudflare tunnel. The app itself does not provide authentication, so any external exposure should be protected by the tunnel or another access-control layer.

## Scheduler

The Scheduler tab lets the app regenerate XMLTV data automatically.

It can be configured with:

- whether the scheduler is enabled;
- how many days of XMLTV data to fetch;
- the daily run time;
- manual **Run now** support.

The scheduler uses the selected channels from the curated M3U and generates the same filtered XMLTV file that the EPG tab creates manually.

## HDHR

The HDHR tab makes `iptv-epg` appear as a SiliconDust HDHomeRun-style network tuner.

This matters most for Plex, because Plex does not accept a plain IPTV M3U as a live TV source in the same way Emby and Jellyfin can. Plex can, however, add an HDHomeRun tuner.

The app provides:

- HDHomeRun discovery metadata;
- SSDP discovery;
- `discover.json`;
- `lineup.json`;
- `lineup_status.json`;
- `hdhr_epg.xml`;
- `/auto/v...` stream endpoints;
- a downloadable proxy M3U;
- configurable tuner and stream limits.

The HDHR guide uses the app's filtered XMLTV data as the source of truth, with channel IDs rewritten to match the HDHR lineup numbering.

### HDHR Streaming Modes

| Mode | Explanation |
| --- | --- |
| Direct proxy | Passes the provider stream through directly. Useful as an option, but not always reliable with Plex. |
| ffmpeg remux | Uses `ffmpeg` to remux the stream into a more compatible MPEG-TS output. This is the usual Plex-friendly mode. |
| Buffered remux | Uses the same remux path but adds a small configurable buffer. Useful for choppy streams. |

### HDHR Stream Safety

The app has several protections for one-stream provider accounts:

- maximum upstream stream count;
- conflict policy;
- idle cleanup;
- maximum stream age cleanup;
- scheduled stream drop;
- immediate release when the client disconnects.

The goal is that closing Plex, VLC, a browser tab, or a TV playback session should release the upstream provider stream promptly.

### HDHR Group Exclusions

Plex can struggle with very large channel counts. The HDHR tab includes a channel limit and a group exclusion list.

Checking a group in this list excludes it from the HDHR lineup only. The group remains selected everywhere else, including the normal filtered M3U, XMLTV, guide, and DLNA.

After changing HDHR group exclusions, the HDHR lineup and guide are regenerated from the current selected channels.

## DLNA

The DLNA tab makes `iptv-epg` appear as a DLNA media server.

This is intended for VLC, TVs, and other DLNA clients. It allows a TV to browse `iptv-epg` as a source without Plex, Jellyfin, Emby, or a dedicated IPTV app.

Unlike HDHR/Plex, DLNA exposes the full selected channel list and preserves IPTV groups as folders. This is important because hundreds of flat channels are awkward to browse on a TV.

The DLNA server provides:

- SSDP discovery as a media server;
- device description XML;
- ContentDirectory;
- ConnectionManager;
- grouped channel folders;
- channel stream URLs;
- a request log for troubleshooting TV behaviour;
- a DLNA inspector for comparing other DLNA servers, such as a real HDHomeRun or Plex.

### DLNA Streaming Modes

| Mode | Explanation |
| --- | --- |
| MPEG-TS copy | Uses the shared proxy path and keeps the stream close to source format. This is the default. |
| Buffered remux | Uses the same buffering engine as HDHR buffered mode. Useful as a fallback for rough streams. |
| TV compatible H.264/AAC | Transcodes to a more TV-friendly H.264/AAC transport stream. Use only if needed. |

The DLNA implementation was tuned against VLC, Samsung TV behaviour, Plex DLNA metadata, and the real HDHomeRun DLNA server.

## Guide

The Guide tab displays the generated XMLTV guide by group.

It supports:

- group filtering;
- day selection;
- current-time positioning;
- automatic refresh of the guide time window;
- visible "Unknown" placeholders where programme data is missing;
- stream previews for currently airing programmes.

Preview buttons use a small play-style prompt. They are intended as a convenience, not as the main streaming path.

The guide uses the generated XMLTV file and the selected channel ordering, so it should reflect the same channel choices as the filtered M3U and proxy outputs.

## Diagnostics

The Diagnostics page opens in a new tab and acts as both diagnostics and lightweight API documentation.

It includes runnable checks for app health, status, M3U, EPG, HDHR, DLNA, scheduler, and other endpoints.

Recent reliability work added:

```text
/health
/health/deep
```

`/health` is intentionally lightweight and suitable for Docker healthchecks or external monitors.

`/health/deep` includes uptime, thread names, active proxy streams, SSDP state, and stream cleanup state. It is useful when the container is running but the app does not appear reachable.

## Deployment

The repo includes a helper script for the Docker host:

```bash
bash deploy.sh
```

It runs:

```bash
cd /docker/iptv_epg/repo
git pull origin main
docker compose -p iptv_epg build
docker compose -p iptv_epg up -d --force-recreate
sleep 3
curl http://localhost:8088/health
```

Do not use `--no-cache` for normal deploys. That causes unnecessary re-downloads and rebuilds, including `ffmpeg`.

The Compose file now includes a Docker healthcheck against `/health`, so the container can report `healthy` or `unhealthy` rather than only `running`.

## Architecture Notes

Durable state lives in SQLite:

```text
/db/iptv_epg.db
```

Generated and transient files live under `/data`, including:

```text
/data/source/source.m3u
/data/filtered.m3u
/data/filtered_epg.xml
/data/hdhr.m3u
/data/epg_cache/*
```

Runtime layout:

```text
/config  settings/config overrides
/data    source cache and generated files
/db      SQLite database
/logs    app logs
```

The UI is a thin API client. Heavy work happens server-side. The filtered M3U, filtered XMLTV, guide, HDHR, and DLNA all draw from the same selected-channel configuration.

## Summary

| Scenario | Result |
| --- | --- |
| IPTV app | Uses curated `filtered.m3u` and `filtered_epg.xml`. At home, VPN routing is recommended because the M3U contains provider URLs. |
| IPTV away from home | The curated M3U/XMLTV can be exposed through a protected tunnel if required. |
| Plex live TV | Uses HDHR emulation, with `iptv-epg` acting as the proxy. Plex does not talk directly to the IPTV provider. |
| Emby/Jellyfin | Can use M3U/XMLTV directly, or consume the HDHR-style proxy where useful. |
| DLNA/VLC/TV | Uses the DLNA media server. Channels are grouped by IPTV group and streamed through `iptv-epg`. |
| VPN safety | The public IP display and killswitch help prevent streaming when the host has fallen back to the home ISP route. |

At this point, `iptv-epg` covers the original m3u4u-style playlist workflow, the XMLTV generation workflow, HDHR proxying for Plex, DLNA proxying for TVs, and safety tooling around VPN routing and stream cleanup.

Pretty nifty stuff.

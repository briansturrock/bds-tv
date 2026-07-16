# Testing Checklist

## Health

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/health/deep
curl http://127.0.0.1:8088/api/status
```

Docker should also report the service as healthy:

```bash
docker compose -p iptv_epg ps
```

## Deploy Smoke Test

On the Docker host:

```bash
cd /docker/iptv_epg/repo
bash deploy.sh
```

The helper pulls `main`, builds without `--no-cache`, recreates the container, waits briefly, and calls `/health`.

## Parser and Feature Checks

```bash
python scripts/test_m3u_parser.py
python scripts/test_epg_unknown.py
python scripts/test_hdhr_channel_limit.py
python scripts/test_hdhr_stream_safety.py
python scripts/test_hdhr_buffered_stream.py
python scripts/test_dlna_catalogue.py
```

## Manual Checks

- Settings loads, public IPv4/country flag appears, and forced refresh works.
- Channels can be selected without the list jumping back to the top.
- Filtered M3U generation produces `/filtered.m3u`.
- EPG matching saves by `tvg-id` and logo overrides apply across matching channels.
- Filtered EPG generation produces `/filtered_epg.xml`.
- Scheduler can save settings and run manually.
- Guide opens at the current time and shows "Unknown" where data is missing.
- HDHR discovery, `lineup.json`, and `hdhr_epg.xml` load.
- Plex can play an HDHR stream when the killswitch allows it.
- DLNA appears in VLC/TV clients with grouped folders.
- DLNA MPEG-TS copy and buffered remux modes play in VLC.
- Killswitch blocks streaming when the public IP country equals the configured home country.

## Image Save/Load

Usually not needed now that the repo is deployed directly, but still possible:

```bash
docker build -t iptv_epg:dev .
docker save iptv_epg:dev -o iptv_epg-dev-amd64.tar
docker load -i iptv_epg-dev-amd64.tar
```

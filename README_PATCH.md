# Patch: Generate filtered EPG from saved EPGShare mappings

Apply this on branch:

```text
epgshare-index
```

This adds filtered EPG generation from reviewed/saved EPGShare mappings only.

## New endpoint

```text
POST /api/epgshare/generate-filtered?days=3
```

## Behaviour

- Reads saved mappings from `epgshare_mappings`.
- Ignores rows marked `ignored`.
- Ignores unsaved suggestions.
- Groups mappings by `source_key`.
- Downloads only the required `epg_ripper_*.xml.gz` files.
- Parses only programmes for saved XMLTV IDs.
- Rewrites programme `channel=""` IDs to your IPTV `tvg-id` values so the EPG matches the filtered M3U.
- Writes:

```text
/data/output/filtered_epg.xml
```

- Creates a backend job visible in:

```text
GET /api/jobs
```

## Diagnostics

Adds Diagnostics row for:

```text
POST /api/epgshare/generate-filtered
```

## Review UI

Adds a button to:

```text
/dev/epgshare-matching
```

called:

```text
Generate filtered EPG
```

## Apply

```bash
unzip iptv_epg_patch_epgshare_generate_filtered.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Generate filtered EPG from EPGShare mappings"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Then use:

```text
http://192.168.0.156:8088/dev/epgshare-matching
```

or Diagnostics:

```text
POST /api/epgshare/generate-filtered?days=3
GET  /api/jobs
```

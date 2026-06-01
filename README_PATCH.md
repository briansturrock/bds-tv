# Patch: Dedupe EPGShare all-sources index import

Apply this on branch:

```text
epgshare-index
```

The import failed with:

```text
UNIQUE constraint failed: epgshare_channel_index.xmltv_id, epgshare_channel_index.source_key
```

That means `epg_ripper_ALL_SOURCES1.txt` contains duplicate XMLTV IDs inside the same source section.

## Fix

- Deduplicates `(source_key, xmltv_id)` while parsing the TXT index.
- Uses `INSERT OR IGNORE` as a defensive fallback.

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_epgshare_dedupe_index.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Dedupe EPGShare index import"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Then retry in Diagnostics:

```text
POST /api/epgshare/index
GET  /api/jobs
GET  /api/epgshare/status
GET  /api/epgshare/matches
```

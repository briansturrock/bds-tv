# Patch: EPGShare index backend

Apply this on branch:

```text
epgshare-index
```

This patch adds a backend-only EPGShare index import and matching layer.

## What this does

- Imports `epg_ripper_ALL_SOURCES1.txt` into SQLite.
- Parses section headings like:

```text
-- epg_ripper_AE1 --
1.Baghdad.ae
2M.Monde.ae
```

- Stores each XMLTV/channel ID with the source key that contains it.
- Matches currently selected IPTV channels by `tvg-id` against the imported index.
- Reports which `epg_ripper_*.xml.gz` files would be needed.
- Adds Diagnostics Console entries for all new endpoints.

## New endpoints

```text
POST /api/epgshare/index
GET  /api/epgshare/status
GET  /api/epgshare/search?q=BBC
GET  /api/epgshare/matches
```

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_epgshare_index.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add EPGShare index import and matching"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git fetch
sudo git checkout epgshare-index
sudo git pull
sudo docker compose up --build -d
sudo docker logs --tail=80 iptv_epg
curl http://127.0.0.1:8088/health
```

## Test

Open:

```text
http://192.168.0.156:8088/dev/diagnostics
```

Then run:

```text
POST /api/epgshare/index
GET  /api/jobs
GET  /api/epgshare/status
GET  /api/epgshare/matches
GET  /api/epgshare/search?q=BBC
```

First patch is index/match only. It does not download or parse XML.GZ programme data yet.

# Patch: EPGShare mapping review UI and saved mappings

Apply this on branch:

```text
epgshare-index
```

This adds a review step before filtered EPG generation.

## New backend endpoints

```text
GET  /api/epgshare/mapping-review
GET  /api/epgshare/mappings
POST /api/epgshare/mappings
```

## New review UI

```text
GET /dev/epgshare-matching
```

## What it does

- Shows selected IPTV channels.
- Shows exact and suggested EPGShare matches.
- Lets you choose a match.
- Lets you mark a channel as no EPG / ignored.
- Lets you manually search the EPGShare index.
- Saves reviewed mappings into SQLite.
- Adds Diagnostics entries for the new endpoints/page.

This does not generate filtered EPG yet. Generation should use saved mappings only.

## Apply

```bash
unzip iptv_epg_patch_epgshare_mapping_review.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add EPGShare mapping review UI"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Open:

```text
http://192.168.0.156:8088/dev/epgshare-matching
```

Also test in Diagnostics:

```text
GET  /api/epgshare/mapping-review
GET  /api/epgshare/mappings
POST /api/epgshare/mappings
```

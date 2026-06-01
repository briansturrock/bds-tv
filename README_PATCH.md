# Patch: Product EPG Management UI

Apply this on branch:

```text
epg-product-ui
```

This adds a product-style EPG management page on top of the working EPGShare backend.

## New page

```text
GET /epg
```

## Layout

- Left column: selected channels, mapping status, filter.
- Right column: selected channel details, saved mapping, suggestions, manual search, save/ignore actions.
- Top actions:
  - refresh
  - import/update EPGShare index
  - generate filtered EPG
  - links to filtered.m3u and filtered_epg.xml
  - recent EPGShare job status

## Backend

No new data endpoints are required. This page uses existing endpoints:

```text
GET  /api/epgshare/mapping-review
GET  /api/epgshare/search
POST /api/epgshare/mappings
POST /api/epgshare/index
POST /api/epgshare/generate-filtered
GET  /api/jobs
```

## Diagnostics

Adds a Diagnostics row for:

```text
GET /epg
```

## Apply

```bash
unzip iptv_epg_patch_epg_product_ui.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add product EPG management UI"
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
http://192.168.0.156:8088/epg
```

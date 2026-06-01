# Patch: Add EPGShare endpoints to Diagnostics registry

Apply this on branch:

```text
epgshare-index
```

This fixes the issue where EPGShare backend routes exist but do not appear in `/dev/diagnostics`.

## Adds Diagnostics rows for

```text
GET  /api/epgshare/status
POST /api/epgshare/index
GET  /api/epgshare/search?q=BBC&limit=50
GET  /api/epgshare/matches
```

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_epgshare_diagnostics_registry.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add EPGShare diagnostics entries"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Then reopen:

```text
http://192.168.0.156:8088/dev/diagnostics
```

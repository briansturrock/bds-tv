# Patch: Restore jobs list endpoint on Diagnostics branch

This fixes:

```text
GET /api/jobs -> 404
```

The Diagnostics Console registered `/api/jobs`, but the diagnostics branch's `main.py` was missing the jobs-list route.

## Adds

```text
GET /api/jobs
GET /api/jobs?limit=10
```

Existing route remains:

```text
GET /api/jobs/{job_id}
```

## Apply

From the repo root on branch `diagnostics-console`:

```bash
unzip iptv_epg_patch_diagnostics_jobs_endpoint.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Restore jobs list endpoint for diagnostics"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Then retest:

```text
GET /api/jobs
/dev/diagnostics
```

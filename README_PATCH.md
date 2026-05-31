# Patch: Add jobs list endpoint

This patch adds a simple endpoint for listing recent jobs:

```text
GET /api/jobs
GET /api/jobs?limit=50
```

The existing endpoint remains:

```text
GET /api/jobs/{job_id}
```

This makes it easier to find recent job IDs from Postman/browser without copying the ID immediately from the original response.

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_jobs_list_endpoint.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add jobs list endpoint"
git push
```

## Pull/build on Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
sudo docker logs --tail=80 iptv_epg
curl http://127.0.0.1:8088/health
```

## Test

```text
GET /api/jobs
GET /api/jobs?limit=10
GET /api/jobs/<job_id>
```

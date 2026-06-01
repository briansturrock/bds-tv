# Patch: Diagnostics Console

Apply this on branch:

```text
diagnostics-console
```

Adds an independent backend diagnostics console.

## New routes

```text
GET /dev/diagnostics
GET /dev/diagnostics/endpoints
GET /dev/diagnostics/coverage
```

## Design rules

- Safe GET checks auto-run when the page loads.
- Every endpoint has its own Run button.
- POST endpoints never auto-run.
- GET endpoint paths are clickable links.
- Failed GETs show errors but do not stop other checks.
- Results can be copied/exported individually.
- All results can be copied/exported as JSON.
- Coverage compares registered diagnostic endpoint definitions against actual FastAPI routes.
- A new API endpoint with no diagnostics entry is considered incomplete.

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_diagnostics_console.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add diagnostics console"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git fetch
sudo git checkout diagnostics-console
sudo git pull
sudo docker compose up --build -d
sudo docker logs --tail=80 iptv_epg
curl http://127.0.0.1:8088/health
```

Open:

```text
http://192.168.0.156:8088/dev/diagnostics
```

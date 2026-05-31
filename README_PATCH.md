# Patch: Fix SQLite locking inside M3U index transaction

This patch fixes the remaining `database is locked` failure during `POST /api/m3u/fetch`.

## Root cause

The M3U indexer held a large SQLite write transaction while also trying to update job progress from a separate SQLite connection.

That creates a self-inflicted lock:

```text
index transaction holds write lock
→ progress update opens another connection
→ second connection tries to write jobs table
→ database is locked
```

## Fix

- Do not update job progress from inside the long channel indexing transaction.
- Update status before indexing starts.
- Index everything in one transaction.
- Update final job status after the transaction commits.
- Keep download progress updates, because those occur before the index write transaction.

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_sqlite_locking_index_transaction.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Avoid job progress writes during M3U index transaction"
git push
```

## Pull/build on Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
sudo docker logs --tail=80 iptv_epg
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/status
```

## Test

```text
POST /api/m3u/fetch
GET  /api/jobs/<job_id>
GET  /api/groups
```

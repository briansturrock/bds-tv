# Patch: Fix SQLite locking during M3U indexing

This patch fixes the failed M3U fetch/index job:

```text
database is locked
```

## What changed

- SQLite connections now use a longer timeout.
- `PRAGMA busy_timeout` is set on every connection.
- Job progress updates are throttled so the indexer does not constantly open competing write connections while indexing.
- M3U indexing uses fewer job-status writes.

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_sqlite_locking.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix SQLite locking during M3U indexing"
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

## Test M3U fetch

Start the job:

```text
POST /api/m3u/fetch
```

Poll:

```text
GET /api/jobs/<job_id>
```

Then:

```text
GET /api/groups
```

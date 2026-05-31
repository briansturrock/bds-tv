# Commit 2: M3U source fetch + SQLite indexing

Copy these files into the root of your `iptv_epg` repo, overwriting existing files where prompted.

This commit adds backend-only M3U handling:

- `POST /api/settings` stores the upstream M3U URL.
- `GET /api/settings` returns settings.
- `POST /api/m3u/fetch` starts a backend job to fetch/cache/index the M3U.
- `GET /api/jobs/{job_id}` returns job progress.
- `GET /api/groups` returns group summaries from SQLite.
- `GET /api/channels?group_id=...&offset=0&limit=200` returns channels for one group only.
- `GET /api/source` returns source M3U metadata.

The browser never downloads or parses the source M3U.

## Apply

```bash
unzip iptv_epg_commit2_m3u_indexing.zip -d /tmp/iptv_epg_commit2
cp -R /tmp/iptv_epg_commit2/* /path/to/iptv_epg/
cd /path/to/iptv_epg
git add .
git commit -m "Add M3U source fetch and SQLite indexing"
git push
```

## Run locally

```bash
docker compose up --build
```

## Test

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/status
curl -X POST http://127.0.0.1:8088/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"m3u_url":"https://example.com/playlist.m3u"}'

curl -X POST http://127.0.0.1:8088/api/m3u/fetch
curl http://127.0.0.1:8088/api/groups
```

Do not commit real provider URLs or generated data.

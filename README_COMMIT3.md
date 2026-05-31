# Commit 3: Channel selection + filtered M3U generation

Copy these files into the root of your `iptv_epg` repo, overwriting existing files where prompted.

This commit adds the core playlist output flow:

- Select/unselect channels.
- Select/unselect all channels in a group.
- Query selected channels.
- Generate `/data/filtered.m3u`.
- Serve `GET /filtered.m3u`.

## New endpoints

```text
GET  /api/selected-channels
POST /api/channels/select
POST /api/groups/{group_id}/select
POST /api/m3u/generate-filtered
GET  /filtered.m3u
```

## Behaviour

- Filtered M3U keeps the original provider stream URLs.
- Output order uses the DB ordering model:
  - selected groups only;
  - `groups.user_order`;
  - `groups.provider_order`;
  - `channels.user_order`;
  - `channels.provider_order`.
- Generated output is file-based:
  - `/data/filtered.m3u`

## Apply

```bash
unzip iptv_epg_commit3_selection_filtered_m3u.zip -d /tmp/iptv_epg_commit3
cp -R /tmp/iptv_epg_commit3/* /path/to/iptv_epg/
cd /path/to/iptv_epg
git add .
git commit -m "Add channel selection and filtered M3U generation"
git push
```

## Smoke test

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/groups

# select one channel by ID
curl -X POST http://127.0.0.1:8088/api/channels/select \
  -H 'Content-Type: application/json' \
  -d '{"channel_ids":["CHANNEL_ID_HERE"],"selected":true}'

curl -X POST http://127.0.0.1:8088/api/m3u/generate-filtered
curl http://127.0.0.1:8088/filtered.m3u
```

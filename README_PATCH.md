# Commit 6: Group and channel ordering

This patch adds manual ordering for groups and channels using the existing SQLite `user_order` fields.

## Scope

- Ordering is controlled from the Channels tab.
- Groups with selected channels remain pinned at the top.
- Selected-channel groups can be moved up/down.
- Selected channels in the current group can be moved up/down.
- Filtered M3U output already follows `user_order`, so this affects output order.
- EPG/Guide work is not included in this patch.

## New endpoints

```text
POST /api/groups/order
POST /api/channels/order
```

## Apply

From the repo root:

```bash
unzip iptv_epg_commit6_group_channel_ordering.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add group and channel ordering"
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

1. Open the Channels tab.
2. Select channels in more than one group.
3. Use group up/down controls.
4. Use selected-channel up/down controls.
5. Generate filtered M3U.
6. Confirm `filtered.m3u` follows the selected order.

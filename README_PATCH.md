# Patch: Fix channel loading after ordering UI restore

Apply this on branch:

```text
epg-product-ui
```

## Problem

After restoring the group ordering buttons, clicking a group changed the heading but left the channels pane stuck on:

```text
Loading channels...
```

## Fix

This patch makes the group/channel loading path defensive:

- catches group-load errors and shows them in the channels pane
- prevents the UI from staying stuck at "Loading channels..."
- avoids reloading the channel list after every order-save
- renders the reordered channel list immediately, then saves order
- hardens `renderChannels()` against malformed/null results

## Apply

```bash
unzip iptv_epg_patch_fix_channel_load_after_order_restore.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix channel loading after ordering restore"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Test:

```text
http://192.168.0.156:8088/#channels
```

Click several groups and confirm channels load. Then test group/channel up/down arrows.

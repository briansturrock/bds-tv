# Patch: Fix EPG tab load and compact Channels rows

Apply this on branch:

```text
epg-product-ui
```

## Fix 1: EPG tab did not load selected channels

The previous app-shell integration called `init()` before the EPG tab state/functions were fully declared. Depending on load/click timing, the EPG tab could render the shell but not load `/api/epgshare/mapping-review`.

This patch moves app startup to the end of `app.js`, after the EPG tab module is declared, and adds a fallback to load the EPG review when the EPG tab is active.

## Fix 2: compact Channels tab rows

The Channels tab still wastes vertical space when reorder arrow buttons are present. This patch makes group/channel rows single-line, compact entries where the name, count, checkbox/logo and ordering controls sit on one line.

## Apply

```bash
unzip iptv_epg_patch_epg_tab_load_and_compact_channels.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix EPG tab loading and compact channel rows"
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
http://192.168.0.156:8088/#epg
http://192.168.0.156:8088/#channels
```

The EPG tab should now populate the selected channel list, and the Channels tab should use more compact single-line rows.

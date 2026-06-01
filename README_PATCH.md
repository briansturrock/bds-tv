# Patch: Channels toolbar button styling and independent scrolling

Apply this on branch:

```text
epg-product-ui
```

## Fixes

### 1. Channels toolbar button/link mismatch

The "Open filtered.m3u" control was a plain link while the other controls were buttons. This patch makes it use the same button styling and aligns all toolbar controls.

### 2. Channels page scrolling

The Channels page was scrolling as one full page. This patch makes the Groups pane and Channels pane independently scrollable while the overall Channels tab stays fixed-height.

When you select a group, the channels list resets to the top.

## Apply

```bash
unzip iptv_epg_patch_channels_toolbar_and_independent_scroll.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix channels toolbar and independent scrolling"
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

Confirm:

- `Open filtered.m3u` looks like a button.
- The Groups list scrolls independently.
- The Channels list scrolls independently.
- Selecting a new group resets the channel list to the top.

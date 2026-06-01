# Patch: Tighten EPG product UI layout

Apply this on branch:

```text
epg-product-ui
```

This fixes the first-pass EPG Management UI issues:

- Adds an EPG link to the main app header.
- Makes `/epg` feel like part of the app, not a separate tool.
- Removes the "App" external-style link from the EPG page.
- Shrinks the top header/summary/job area.
- Shows only the latest EPGShare job line instead of a large job history block.
- Makes the channel rows much more compact.
- Gives the left channel list enough usable height and its own scrollbar.
- Keeps the right detail pane scrollable only when it has real content.

## Apply

```bash
unzip iptv_epg_patch_epg_product_ui_layout_fix.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Tighten EPG product UI layout"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Open:

```text
http://192.168.0.156:8088/
http://192.168.0.156:8088/epg
```

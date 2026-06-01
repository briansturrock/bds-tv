# Patch: Restore ordering UI and keep compact rows

Apply this on branch:

```text
epg-product-ui
```

## What this fixes

The backend ordering endpoints still existed, but the frontend ordering controls had been lost from `static/app.js`.

This patch restores:

- group up/down buttons
- channel up/down buttons
- save calls to:
  - `POST /api/groups/order`
  - `POST /api/channels/order`
- compact single-line group rows
- compact single-line channel rows
- button/link alignment CSS for the Channels toolbar

It also keeps the EPG app-shell load-order fix by starting the app after the EPG tab code is declared.

## Apply

```bash
unzip iptv_epg_patch_restore_ordering_ui.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Restore ordering UI controls"
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
http://192.168.0.156:8088/#epg
```

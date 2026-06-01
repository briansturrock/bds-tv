# Patch: Integrate EPG into the main app shell

Apply this on branch:

```text
epg-product-ui
```

This is not a cosmetic navigation patch. It moves the EPG UI into the same root app shell as Settings and Channels.

## Result

The root app now has equal top-level sections:

```text
Settings | Channels | EPG | Diagnostics
```

Core pages live in the root app:

```text
/          Settings, Channels, EPG
/dev/...   Developer tools only
```

## What this patch does

- Adds an `EPG` tab inside `src/iptv_epg/static/index.html`.
- Moves the EPG Management UI into that root tab.
- Adds EPG styles to `app.css`.
- Adds EPG behaviour to `app.js`.
- Removes the `/epg` product route wiring from `main.py`.
- Removes the `/epg` diagnostics row.
- Keeps `/dev/epgshare-matching` as a dev page for now.

## Cleanup required

After applying the patch, remove the obsolete standalone EPG product page files:

```bash
git rm -f src/iptv_epg/epg_product_routes.py
git rm -f src/iptv_epg/static/epg.html
git rm -f src/iptv_epg/static/epg.css
git rm -f src/iptv_epg/static/epg.js
```

## Apply

```bash
unzip iptv_epg_patch_integrate_epg_into_app_shell.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git rm -f src/iptv_epg/epg_product_routes.py
git rm -f src/iptv_epg/static/epg.html
git rm -f src/iptv_epg/static/epg.css
git rm -f src/iptv_epg/static/epg.js
git status --short
git add .
git commit -m "Integrate EPG into main app shell"
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
http://192.168.0.156:8088/
http://192.168.0.156:8088/#settings
http://192.168.0.156:8088/#channels
http://192.168.0.156:8088/#epg
http://192.168.0.156:8088/dev/diagnostics
```

`/epg` should no longer be the product route. The product EPG UI is now the EPG tab inside `/`.

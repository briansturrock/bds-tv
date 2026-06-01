# Patch: Restore select-shown checkbox helpers

Apply this on branch:

```text
epg-product-ui
```

## Problem

After restoring ordering controls, clicking a group failed with:

```text
resetSelectShownCheckbox is not defined
```

That prevented the Channels page from loading channel rows.

## Fix

Adds back the missing helper functions:

```text
resetSelectShownCheckbox()
updateSelectShownCheckbox()
```

These keep the "Select shown channels" checkbox state in sync.

## Apply

```bash
unzip iptv_epg_patch_restore_select_shown_helpers.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Restore select shown checkbox helpers"
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

Click groups and confirm channels load.

# Patch: Make channel auto-save clearer and add select-all checkbox

This patch improves the Channels UI.

## Changes

- Adds clear text: `Selections save automatically.`
- Replaces the separate `Select visible` / `Unselect visible` buttons with one normal select-all checkbox above the channel list.
- The select-all checkbox applies to the currently shown page of channels only.
- The checkbox shows an indeterminate state when only some shown channels are selected.
- Individual channel checkbox changes still auto-save immediately.

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_channel_autosave_select_all_ui.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Clarify channel auto-save and add select all checkbox"
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

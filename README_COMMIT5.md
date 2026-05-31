# Commit 5: Thin UI for Settings + Channels + filtered M3U

Copy these files into the root of your `iptv_epg` repo, overwriting existing files where prompted.

This commit adds the first source-controlled UI.

## Scope

UI pages included:

- Settings
  - view/set M3U URL
  - fetch/index source M3U
  - poll job progress
  - show status
- Channels
  - load group summaries only
  - click a group to load only that group's channels
  - paginate channels
  - select/unselect channels
  - select/unselect all channels in the current group
  - generate filtered M3U
  - show filtered M3U output link

## Important design rule

The UI is a thin API client.

It does not:

- parse the M3U;
- parse XMLTV;
- preload all channels;
- preload EPG data;
- render the guide.

## New served routes

```text
GET /
GET /static/app.css
GET /static/app.js
```

Existing API endpoints are unchanged.

## Apply

From the repo root:

```bash
unzip iptv_epg_commit5_thin_ui_settings_channels.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add thin UI for settings channels and filtered M3U"
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

Then open:

```text
http://192.168.0.156:8088/
```

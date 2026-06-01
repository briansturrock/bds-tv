# Patch: Guide page phase 1

Apply this on branch:

```text
guide-page
```

## Scope

Adds a Guide tab inside the main app shell:

```text
Settings | Channels | EPG | Guide | Diagnostics
```

This is phase 1 only. No streaming yet.

## Behaviour

The Guide shows only:

- groups that have selected channels
- selected channels inside those groups

It uses:

```text
/data/filtered_epg.xml
```

and selected channel state from SQLite.

## New endpoints

```text
GET /api/guide/groups
GET /api/guide?group_id=<group_id>
```

## UI

- Groups on the left.
- Guide window on the right.
- Channels in the selected group.
- Channel icons/logos where available.
- Current airing highlighted.
- Programme hover tooltip shows title/time/description.
- Programmes are loaded from the generated filtered EPG.

## Apply

```bash
unzip iptv_epg_patch_guide_page_phase1.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add guide page phase 1"
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
http://192.168.0.156:8088/#guide
http://192.168.0.156:8088/dev/diagnostics
```

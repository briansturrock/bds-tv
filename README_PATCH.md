# Patch: Guide timeline grid

Apply this on branch:

```text
guide-page
```

This replaces the card-row guide with a proper time-aligned grid.

## What changes

- Timeline header across the top.
- Channels down the left.
- Programme blocks positioned by start/stop time.
- Timeline starts at the previous half-hour mark.
- One shared horizontal scroll for the whole guide.
- Channel names/logos remain sticky on the left.
- Current programme is highlighted.
- Current time line appears when inside the visible window.
- Date picker plus previous/today/next controls.
- Still only shows groups with selected channels and selected channels inside those groups.

## Backend

`GET /api/guide` now accepts:

```text
group_id
date=YYYY-MM-DD
start=<ISO datetime>
hours=8
```

## Apply

```bash
unzip iptv_epg_patch_guide_timeline_grid.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add guide timeline grid"
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
```

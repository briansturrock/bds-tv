# Patch: Guide timeline row polish

Apply this on branch:

```text
guide-page
```

This is the corrected polish patch: it makes guide rows shorter, not the channel column narrower.

## Fixes

### 1. Programme block widths

The BBC3/CBBC example had correct programme times but the visual block was too short.

Cause: an older `.guide-programme { max-width: ... }` rule was still capping programme block width.

Fix: remove that visual cap with a timeline-specific override.

### 2. Shorter channel rows

Rows are reduced in height so more channels fit vertically.

The channel/logo column width is kept sensible.

### 3. Date selector in the grid corner

The toolbar date input is removed.

The date area in the timeline grid corner becomes a dropdown, with options based on dates available in `filtered_epg.xml` for selected channels.

Labels are:

```text
Today
Tomorrow
Wednesday
Thursday
...
```

depending on available EPG dates.

## New endpoint

```text
GET /api/guide/dates
```

## Apply

```bash
unzip iptv_epg_patch_guide_timeline_row_polish.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Polish guide timeline rows"
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

# Patch: Guide date window and shared horizontal scroll

Apply this on branch:

```text
guide-page
```

## Fixes

### 1. Date/window logic

The Guide now uses a selected date window:

```text
selected date 00:00 -> next day 00:00
```

and includes programmes that overlap that date window.

That means:

- programmes already ended before the selected date are excluded
- programmes starting after the selected date are excluded
- long programmes that started before the window but are still airing inside it are included
- current airing still gets highlighted

### 2. Shared horizontal scrolling

The guide no longer gives each channel its own horizontal scrollbar.

Instead:

- the whole guide window scrolls horizontally
- channel rows stay aligned
- channel names/logos stay sticky on the left
- programme cards share one horizontal timeline area

## UI

Adds a date picker to the Guide tab.

## Endpoint change

```text
GET /api/guide?group_id=<id>&date=YYYY-MM-DD
```

## Backlog noted

EPG generation should allow choosing:

```text
3, 5, 7, 14 days
```

## Apply

```bash
unzip iptv_epg_patch_guide_date_window_shared_scroll.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add guide date window and shared scroll"
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

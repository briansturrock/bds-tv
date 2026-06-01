# Patch: Fix EPGShare country_match boolean

Apply this on branch:

```text
epgshare-index
```

This fixes `country_match: false` for clearly country-scoped EPGShare matches.

## Why

The previous source-key country parser used a regex capture for:

```text
epg_ripper_<letters><optional digits>
```

This patch makes the parsing explicit:

```text
strip "epg_ripper_"
strip trailing digits
strip non-letters
apply generic country aliases
```

So source keys like these are parsed generically:

```text
epg_ripper_CA2 -> CA
epg_ripper_US2 -> US
epg_ripper_UK1 -> UK
epg_ripper_FR1 -> FR
```

These are examples only; there is no hardcoded country list.

## Apply

```bash
unzip iptv_epg_patch_epgshare_country_match_bool.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix EPGShare country match detection"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Then rerun:

```text
GET /api/epgshare/matches
```

Expected: country_match should now be true for suggestions whose selected-channel group country matches the EPGShare source key.

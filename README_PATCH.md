# Patch: EPGShare generic country normalisation and positive ranking

Apply this on branch:

```text
epgshare-index
```

This replaces the earlier radio-penalty idea. Do **not** hardcode R1/radio behaviour.

## What this does

- Parses EPGShare source country generically:

```text
epg_ripper_<letters><optional digits>
```

Examples only:

```text
epg_ripper_CA2 -> CA
epg_ripper_US2 -> US
epg_ripper_FR1 -> FR
epg_ripper_AE1 -> AE
```

- Normalises country suffix tokens generically using the selected channel group country:

```text
.ca, .ca2, .us2, .fr
```

- Normalises number words:

```text
one -> 1
two -> 2
three -> 3
```

- Uses positive ranking only:
  - compact exact
  - compact prefix
  - compact containment
  - fuzzy fallback

## Apply

```bash
unzip iptv_epg_patch_epgshare_positive_ranking.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Improve EPGShare positive match ranking"
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

Expected: country_match should be true for correctly scoped source files, and BBC1-style matches should prefer positive number-word/prefix matches over weaker fuzzy lookalikes.

# Patch: EPGShare country-aware match suggestions

Apply this on branch:

```text
epgshare-index
```

This improves:

```text
GET /api/epgshare/matches
```

## Why

Exact matching works, but real IDs differ, for example:

```text
IPTV tvg-id: AandE.ca
EPGShare:    A.and.E.Canada.HD.ca2
```

## What changes

The endpoint now returns:

```text
matches                  exact normalized tvg-id matches
suggestions              country-aware suggested matches
unmatched                no useful exact/suggested match
required_sources         XML.GZ files needed from exact + top suggestions
exact_required_sources
suggested_required_sources
```

It uses:

```text
- selected channel group prefix, e.g. CA|, US|, UK|, FR|
- EPGShare source key country, e.g. epg_ripper_CA2
- compact ID comparison
- noise stripping: HD, FHD, UHD, Canada, US, UK, France, etc.
- number-word handling: BBC One -> BBC1
```

No fuzzy matches are auto-accepted yet. They are suggestions only.

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_epgshare_country_suggestions.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add EPGShare country-aware match suggestions"
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

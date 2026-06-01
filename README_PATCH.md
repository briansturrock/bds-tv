# Patch: Fix EPGShare required source merge mutation

Apply this on branch:

```text
epgshare-index
```

## Bug

`exact_required_sources` was being contaminated by suggested matches.

Example symptom:

```text
matches only contains BLAZE.uk as exact
exact_required_sources also contains CBBC.HD.uk and BBC.One.CI.HD.uk
```

## Cause

`all_required_sources = dict(exact_required_sources)` made a shallow copy. The nested source dictionaries were shared, so merging suggestions into `required_sources` mutated `exact_required_sources`.

## Fix

Build `required_sources` using copied nested dictionaries/lists.

## Apply

```bash
unzip iptv_epg_patch_epgshare_required_sources_copy.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix EPGShare required source summary mutation"
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

Expected:

```text
exact_required_sources should contain only exact matches.
suggested_required_sources should contain only suggested matches.
required_sources should contain the merged view.
```

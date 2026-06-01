# Patch: Preserve Guide programme titles/descriptions

Apply this on branch:

```text
guide-page
```

## Problem

The Guide tab showed every airing as:

```text
Untitled
```

with no description, even though `filtered_epg.xml` contains programme metadata.

## Cause

The Guide backend uses `ElementTree.iterparse()`. It was clearing child nodes like:

```xml
<title>
<desc>
<category>
```

before the parent `<programme>` element was processed.

## Fix

Only clear elements once the parent `<programme>` has been processed/skipped.

## Apply

```bash
unzip iptv_epg_patch_guide_preserve_programme_metadata.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Preserve guide programme metadata"
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

You should now see real programme titles and hover descriptions where they exist in the XML.

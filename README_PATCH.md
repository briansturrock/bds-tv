# Patch: Fix EPGShare output path and empty programme metadata

Apply this on branch:

```text
epgshare-index
```

## Fix 1: output location

The EPGShare generator wrote:

```text
/data/output/filtered_epg.xml
```

but the app/browser route expects the same style as filtered M3U output, i.e.:

```text
/data/filtered_epg.xml
```

This patch changes EPGShare filtered EPG generation to write:

```text
/data/filtered_epg.xml
```

## Fix 2: empty programme metadata

The generated XML had programme rows but empty child elements:

```xml
<title /><desc />
```

Cause: the streaming XML parser cleared child elements like `<title>` and `<desc>` before serializing the parent `<programme>`.

This patch stops clearing non-programme child nodes before the programme is written.

## Apply

```bash
unzip iptv_epg_patch_epgshare_output_and_titles.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix EPGShare output path and programme metadata"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

Then regenerate:

```text
POST /api/epgshare/generate-filtered?days=3
GET  /api/jobs
```

Verify:

```bash
sudo ls -lh /docker/iptv_epg/data/filtered_epg.xml
sudo grep -m 5 "<title" /docker/iptv_epg/data/filtered_epg.xml
```

Then test browser:

```text
http://192.168.0.156:8088/filtered_epg.xml
```

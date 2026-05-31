# Patch: Add missing EPG module

This patch fixes the container startup crash:

```text
ModuleNotFoundError: No module named 'iptv_epg.epg'
```

It adds:

```text
src/iptv_epg/epg.py
```

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_missing_epg_module.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Add missing EPG module"
git push
```

## Pull/build on Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo docker compose up --build -d
sudo docker logs --tail=80 iptv_epg
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/status
```

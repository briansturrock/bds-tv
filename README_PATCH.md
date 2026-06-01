# Fixed patch: EPGShare Diagnostics registry entries

The previous registry-only patch was a no-op due to a marker mismatch. This fixed patch overwrites `src/iptv_epg/diagnostics_registry.py` with EPGShare entries included.

Apply on branch `epgshare-index`.

## Expected change after unzip

```bash
git status --short
```

should show:

```text
 M src/iptv_epg/diagnostics_registry.py
```

## Apply

```bash
unzip iptv_epg_patch_epgshare_diagnostics_registry_fixed.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git status --short
git add .
git commit -m "Add EPGShare diagnostics entries"
git push
```

## Ubuntu

```bash
cd /docker/iptv_epg/repo
sudo git pull
sudo grep -n "EPGShare" src/iptv_epg/diagnostics_registry.py
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
```

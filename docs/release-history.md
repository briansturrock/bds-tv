# Release History Notes

This project began as opaque Docker image tar builds and was then rebuilt as a source-controlled repository.

## Prototype Baseline

- `0.7.6.1-hls-tuned`: last known-good image-only prototype baseline.
- `0.8*` image-only attempts: not trusted; moved to source-controlled rebuild.

## Current Source-Controlled Line

Recent source-controlled milestones:

- `0.9.0`: scheduler introduction.
- `0.9.1` - `0.9.5`: guide streaming, Docker/version fixes, QoL improvements, EPG matching fixes.
- `0.10.x`: HDHR emulation, XMLTV guide support, parser hardening, unknown EPG placeholders, channel limits, stream safety, buffered remux, HDHR group exclusions.
- `0.11.x`: DLNA media server, DLNA compatibility work, favicon, public IP header, VPN streaming killswitch, DLNA buffered remux, health diagnostics.

The current release line is source-controlled and deployed from `main` using `deploy.sh`.

Normal deploy:

```bash
cd /docker/iptv_epg/repo
bash deploy.sh
```

Avoid `docker compose build --no-cache` unless deliberately testing a clean dependency rebuild.

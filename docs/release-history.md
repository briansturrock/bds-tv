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
- `0.12.x`: rename/rebrand to `bds-tv`, including Docker identity and canonical `bds-tv.m3u` / `bds-tv.xml` outputs.
- `0.12.1`: moves the provider stream limit to the main Settings page and improves Guide navigation for future days.
- `0.13.0`: starts the Tizen/TV-app work with a hosted `/tv` interface that browses groups, shows guide data, and plays streams through bds-tv.
- `0.13.1`: improves Tizen compatibility for `/tv` startup and adds Back-to-exit confirmation.
- `0.13.2`: adds the TV App management tab for Samsung TV discovery, signing certificate storage, and future WGT deployment plumbing.
- `0.13.3`: packages the Tizen shell from bds-tv, exposes WGT download, and adds direct install plumbing for runtimes with SDB available.
- `0.13.4`: downloads the same Linux TizenSDB wrapper used by Apps2Samsung and uses it for WGT signing and TV installation.
- `0.13.5`: keeps the native Tizen shell alive around the hosted TV guide, adds shell version display, and routes hosted exit requests through the shell.
- `0.13.6`: shows the TV shell version in the hosted guide and forwards Samsung Back key events between the shell and `/tv`.
- `0.13.7`: moves the TV guide into the packaged Tizen app, removes the iframe wrapper, and captures Samsung Back key events in the top-level app.
- `0.13.8`: refreshes the TV App package status immediately after WGT build or install actions and hardens the Tizen Back-to-close path.
- `0.13.9`: makes the Tizen close confirmation dialog render with conservative absolute positioning for Samsung TV compatibility.
- `0.13.10`: pins TV app scrolling inside the group and guide panes so the header and active guide area remain visible.
- `0.13.11`: fixes top-edge TV app focus scrolling so the first groups/channels remain visible when navigating back up.
- `0.13.12`: gives TV app panes explicit viewport heights and uses rendered row geometry for focus scrolling.
- `0.13.13`: adds 2-hour TV guide windows, programme-level focus, and left/right time navigation to the TV app.
- `0.13.14`: makes Back return from the programme grid to the active group before prompting to close the TV app.
- `0.13.15`: resets the TV guide window to today/now when selecting a channel group.
- `0.13.29`: adds programme icon URLs to the shared `/api/guide` payload.
- `0.13.28`: deduplicates upstream XMLTV programme entries during BDS-TV XMLTV generation to avoid stacked guide cards.
- `0.13.27`: separates the TV guide time row from the scrollable channel list so programmes cannot scroll underneath it.
- `0.13.26`: pins the TV guide time row while scrolling channels and resets guide scroll on group changes.
- `0.13.25`: adds Settings-page M3U upload/import as a safe manual recovery path.
- `0.13.24`: protects M3U refreshes by validating downloaded playlists before replacing the last known-good source.
- `0.13.23`: applies the TV-safe inset focus highlight to the programme context menu.
- `0.13.22`: fixes Samsung TV exit confirmation focus rendering by using an inset highlight.
- `0.13.21`: adds the documented Samsung AVPlay object surface and fixed TV-safe context/exit dialog positioning.
- `0.13.20`: fixes TV context-menu placement and switches Samsung AVPlay startup into full-screen playback mode.
- `0.13.19`: adds a TV programme context menu and Samsung AVPlay-based stream startup through bds-tv stream endpoints.
- `0.13.18`: fixes TV guide day switching so it preserves the current guide time instead of jumping to midnight.
- `0.13.17`: improves TV guide day-selector navigation so focus can move from programmes to days and return to the active channel group.
- `0.13.16`: adds configurable TV guide day count and a remote-accessible day selector to the TV app.
The current release line is source-controlled and deployed from `main` using `deploy.sh`.

Normal deploy:

```bash
cd /docker/bds-tv/repo
bash deploy.sh
```

Avoid `docker compose build --no-cache` unless deliberately testing a clean dependency rebuild.

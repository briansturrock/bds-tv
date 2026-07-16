# Roadmap

## Current Milestone

The app is approaching a `1.0.0` milestone.

Core features now implemented:

- SQLite-backed state;
- provider M3U fetch/index;
- channel/group selection and ordering;
- filtered M3U generation;
- EPGShare import and matching;
- filtered XMLTV generation;
- scheduled XMLTV generation;
- Guide page with stream preview;
- HDHR emulation for Plex;
- DLNA media server for VLC/TV clients;
- stream cleanup and buffering options;
- public IP display and streaming killswitch;
- health and deep-health diagnostics.

## Before 1.0.0

- Investigate the overnight issue where the container remains running but the app becomes unreachable.
- Use Docker healthcheck and `/health/deep` output to identify whether the issue is Uvicorn, a background thread, stream cleanup, scheduler work, or host/network state.
- Decide whether to add an automatic recovery mechanism after the cause is understood.

## Later Candidates

- More polished operational status page.
- Backup/restore workflow for the SQLite database and generated config.
- More explicit stream history/audit log.
- Better guide/search filtering.
- Optional additional DLNA compatibility profiles if a specific TV needs them.
- More complete user-facing documentation screenshots once the UI settles.

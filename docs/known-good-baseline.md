# Known-Good Baseline

## Prototype Baseline

Last known-good image-only prototype:

```text
iptv_epg:0.7.6.1-hls-tuned
```

That baseline included:

- M3U fetch/index;
- channel group/channel selection;
- filtered M3U generation;
- EPG source detection/testing;
- filtered EPG generation;
- Guide page;
- browser playback via container-side HLS/ffmpeg.

Prototype limitations:

- opaque image-only release process;
- fragile file-based state;
- browser/UI performance regressions from heavy client-side work;
- incomplete ordering model.

## Current Baseline

The source-controlled app now supersedes the prototype baseline.

Current known-good line:

```text
0.11.x
```

Current major capabilities:

- SQLite durable state;
- filtered M3U/XMLTV generation;
- EPGShare matching by `tvg-id`;
- scheduler;
- Guide with preview;
- HDHR emulation;
- DLNA media server;
- stream cleanup and buffered modes;
- public IP display and streaming killswitch;
- Docker healthcheck and `/health/deep`.

Remaining reliability item before calling `1.0.0`:

- investigate the overnight condition where Docker reports the container running but the app is not reachable.

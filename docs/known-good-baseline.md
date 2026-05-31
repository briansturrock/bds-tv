# Known-good baseline

Last known-good prototype image:

```text
iptv_epg:0.7.6.1-hls-tuned
```

Working features from prototype phase:

- M3U fetch/index
- channel group/channel selection
- filtered M3U generation
- EPG source detection/testing
- filtered EPG generation
- Guide page
- browser playback via container-side HLS/ffmpeg

Known problems in prototype phase:

- browser/UI performance regressions due to heavy client-side work
- opaque image-only release process
- fragile state handling in file-based JSON
- group ordering not safely implemented

This repository exists to rebuild the app from a stable, inspectable source tree.

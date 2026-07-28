# bds-tv Tizen App

This is the Samsung/Tizen TV app for bds-tv.

The app is intentionally server-backed:

- it uses `icon.png` as the TV launcher icon;
- it loads groups and guide data from bds-tv;
- it streams channels through bds-tv, never directly from the IPTV provider;
- it handles Samsung remote navigation and exit confirmation inside the top-level Tizen app.

The default server URL is set in `main.js`.

Version `0.1.6` moves the guide out of the iframe wrapper so Samsung Back key handling can run in the packaged app itself.

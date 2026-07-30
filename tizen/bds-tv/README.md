# bds-tv Tizen App

This is the Samsung/Tizen TV app for bds-tv.

The app is intentionally server-backed:

- it uses `icon.png` as the TV launcher icon;
- it loads groups and guide data from bds-tv;
- it streams channels through bds-tv, never directly from the IPTV provider;
- it handles Samsung remote navigation and exit confirmation inside the top-level Tizen app.

The default server URL is set in `main.js`.

Version `1.0.0` is the first stable TV shell baseline, with remote navigation, guide browsing, programme information, and bds-tv proxied playback.

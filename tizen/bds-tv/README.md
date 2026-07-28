# bds-tv Tizen App

This is the Samsung/Tizen TV app for bds-tv.

The app is intentionally server-backed:

- it uses `icon.png` as the TV launcher icon;
- it loads groups and guide data from bds-tv;
- it streams channels through bds-tv, never directly from the IPTV provider;
- it handles Samsung remote navigation and exit confirmation inside the top-level Tizen app.

The default server URL is set in `main.js`.

Version `0.1.7` makes Back handling more visible and robust by only treating real streams as open playback and forcing the close confirmation overlay visible from the top-level app.

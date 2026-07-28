# bds-tv Tizen Shell

This is the first Samsung/Tizen TV shell for bds-tv.

The shell is intentionally small:

- it uses `icon.png` as the TV launcher icon;
- it checks that bds-tv is reachable;
- it then opens the hosted TV interface at `http://192.168.0.185:8088/tv`;
- future guide and playback behaviour should mostly update server-side.

The default server URL is set in `main.js`.

Version `0.1.4` keeps a native Tizen shell around the hosted guide, displays the shell version during startup, and lets the hosted `/tv` page ask the shell to close the app.

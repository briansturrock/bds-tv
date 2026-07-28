# bds-tv Tizen Shell

This is the first Samsung/Tizen TV shell for bds-tv.

The shell is intentionally small:

- it uses `icon.png` as the TV launcher icon;
- it checks that bds-tv is reachable;
- it then opens the hosted TV interface at `http://192.168.0.185:8088/tv`;
- future guide and playback behaviour should mostly update server-side.

The default server URL is set in `main.js`.

Version `0.1.3` keeps the same hosted URL and is packaged by bds-tv for download or direct developer-mode installation when an SDB installer is available.

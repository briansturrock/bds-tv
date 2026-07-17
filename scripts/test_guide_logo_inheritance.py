from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.modules.setdefault("requests", types.SimpleNamespace())


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        os.environ["CONFIG_DIR"] = str(tmp_path / "config")
        os.environ["DATA_DIR"] = str(tmp_path / "data")
        os.environ["DB_DIR"] = str(tmp_path / "db")
        os.environ["LOG_DIR"] = str(tmp_path / "logs")
        os.environ["DB_PATH"] = str(tmp_path / "db" / "iptv_epg.db")

        from iptv_epg.db import apply_inherited_preferred_logos, connect, init_db
        from iptv_epg.epgshare import ensure_epgshare_tables

        init_db()
        ensure_epgshare_tables()

        with connect() as conn:
            conn.execute("INSERT INTO groups(id, name, provider_order) VALUES ('sports', 'Sports', 1)")
            conn.executemany(
                """
                INSERT INTO channels(id, stable_key, group_id, name, tvg_id, logo_url, preferred_logo_url, stream_url, extinf, selected, provider_order)
                VALUES (?, ?, 'sports', ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                [
                    ("hevc", "hevc", "TNT Sports 4 HEVC", "", "provider-hevc.png", None, "http://example.test/hevc", "#EXTINF:-1,TNT Sports 4 HEVC", 1),
                    ("sd", "sd", "TNT Sports 4", "TNT.Sports.4.HD.uk", "provider-sd.png", "shared-guide-logo.png", "http://example.test/sd", "#EXTINF:-1,TNT Sports 4", 2),
                    ("override", "override", "TNT Sports 4 Alt", "alt.TNT.4.uk", "provider-alt.png", "channel-override.png", "http://example.test/override", "#EXTINF:-1,TNT Sports 4 Alt", 3),
                ],
            )
            conn.executemany(
                """
                INSERT INTO epgshare_mappings(channel_id, xmltv_id, source_key, mapping_type, ignored, updated_at)
                VALUES (?, 'TNT.Sports.4.HD.uk', 'epg_ripper_UK1', 'manual', 0, CURRENT_TIMESTAMP)
                """,
                [("hevc",), ("sd",), ("override",)],
            )
            conn.commit()

        rows = [
            {
                "id": "hevc",
                "tvg_id": "",
                "logo_url": "provider-hevc.png",
                "effective_logo_url": "provider-hevc.png",
                "preferred_logo_url": None,
            },
            {
                "id": "override",
                "tvg_id": "alt.TNT.4.uk",
                "logo_url": "channel-override.png",
                "effective_logo_url": "channel-override.png",
                "preferred_logo_url": "channel-override.png",
            },
        ]

        inherited = {row["id"]: row for row in apply_inherited_preferred_logos(rows)}

        check(inherited["hevc"]["effective_logo_url"] == "shared-guide-logo.png", "guide logo was not inherited")
        check(inherited["hevc"]["preferred_logo_url"] == "shared-guide-logo.png", "preferred logo not set from guide")
        check(inherited["override"]["effective_logo_url"] == "channel-override.png", "explicit override was replaced")


if __name__ == "__main__":
    main()

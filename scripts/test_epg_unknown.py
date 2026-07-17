from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.modules.setdefault("requests", types.SimpleNamespace())

from iptv_epg.epgshare import output_channel_ids_by_guide_id, unknown_programmes_for_xmltv_id, xmltv_time  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    timestamp = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)
    check(xmltv_time(timestamp) == "20260714123000 +0000", "XMLTV timestamp formatting failed")

    start = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)
    programmes = unknown_programmes_for_xmltv_id("SkyArts.uk", start, end)

    check(len(programmes) == 2, "expected two six-hour Unknown blocks for eight hours")
    check(all(item.get("channel") == "SkyArts.uk" for item in programmes), "channel ID not preserved")
    check(all(item.findtext("title") == "Unknown" for item in programmes), "Unknown title missing")
    check(programmes[0].get("stop") == programmes[1].get("start"), "Unknown blocks are not contiguous")
    check(programmes[-1].get("stop") == "20260714200000 +0000", "last stop time wrong")

    targets = output_channel_ids_by_guide_id([
        {"xmltv_id": "SkySp.PL.HD.uk", "tvg_id": "uk.Sky Sports Premier League"},
        {"xmltv_id": "SkySp.PL.HD.uk", "tvg_id": "SkySportsPremiereLeague.uk"},
        {"xmltv_id": "SkySp.PL.HD.uk", "tvg_id": "SkySportsPremiereLeague.uk"},
        {"xmltv_id": "TNT.Sports.4.HD.uk", "tvg_id": "", "channel_id": "internal-tnt-sports-4-hevc"},
        {"xmltv_id": "SkySportsMainEvent.uk", "tvg_id": "SkySportsMainEvent.uk"},
    ])
    check(
        targets["SkySp.PL.HD.uk"] == ["uk.Sky Sports Premier League", "SkySportsPremiereLeague.uk"],
        "same guide id should fan out to multiple selected tvg-ids without duplicates",
    )
    check(
        targets["TNT.Sports.4.HD.uk"] == ["internal-tnt-sports-4-hevc"],
        "blank tvg-id should fall back to the selected channel id",
    )
    check(targets["SkySportsMainEvent.uk"] == ["SkySportsMainEvent.uk"], "single guide target mapping failed")


if __name__ == "__main__":
    main()

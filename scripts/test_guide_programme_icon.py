from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.modules.setdefault("requests", types.SimpleNamespace())
sys.modules.setdefault(
    "fastapi",
    types.SimpleNamespace(
        APIRouter=lambda *args, **kwargs: types.SimpleNamespace(get=lambda *a, **k: lambda fn: fn),
        Query=lambda default=None, **kwargs: default,
    ),
)

from iptv_epg import guide_routes  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        epg_path = Path(tmp) / "bds-tv.xml"
        epg_path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <programme channel="BBC1.uk" start="20260730120000 +0000" stop="20260730130000 +0000">
    <title lang="en">Programme With Icon</title>
    <icon src="http://example.test/programme.jpg?w=960&amp;h=540" />
  </programme>
  <programme channel="BBC1.uk" start="20260730130000 +0000" stop="20260730140000 +0000">
    <title lang="en">Programme Without Icon</title>
  </programme>
</tv>
""",
            encoding="utf-8",
        )

        window_start = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)

        with patch.object(guide_routes, "filtered_epg_path", return_value=epg_path):
            programmes = guide_routes.programmes_for_tvg_ids({"BBC1.uk"}, window_start, window_end)

    items = programmes["BBC1.uk"]
    check(len(items) == 2, "expected both programmes in the guide window")
    check(
        items[0]["icon"] == "http://example.test/programme.jpg?w=960&h=540",
        "programme icon URL was not included in the guide payload",
    )
    check(items[1]["icon"] == "", "missing programme icon should be an empty string")


if __name__ == "__main__":
    main()

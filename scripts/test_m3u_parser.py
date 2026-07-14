from __future__ import annotations

from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.modules.setdefault("requests", types.SimpleNamespace())

from iptv_epg.m3u import display_name_from_extinf, extinf_with_logo, parse_attrs, split_extinf_name  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    normal = '#EXTINF:-1 tvg-id="CTV.ca" tvg-name="CA| CTV HD" group-title="CA| ENTERTAINMENT",CTV HD'
    metadata, name = split_extinf_name(normal)
    check(metadata.endswith('group-title="CA| ENTERTAINMENT"'), "normal metadata split failed")
    check(name == "CTV HD", "normal display name split failed")
    check(display_name_from_extinf(normal, parse_attrs(normal)) == "CTV HD", "normal display name failed")

    quoted_comma = '#EXTINF:-1 tvg-id="ABC.us" tvg-name="US| ABC, 13 ANCHORAGE" group-title="US| LOCAL",ABC 13'
    metadata, name = split_extinf_name(quoted_comma)
    check('US| ABC, 13 ANCHORAGE' in metadata, "quoted comma metadata split failed")
    check(name == "ABC 13", "quoted comma display name split failed")

    polluted_name = '#EXTINF:-1 tvg-id="CTV.ca",ON HD" tvg-name="CA| CTV HD" tvg-logo="http://example/logo.png"'
    check(
        display_name_from_extinf(polluted_name, parse_attrs(polluted_name)) == "CA| CTV HD",
        "polluted name did not fall back to a stable attribute",
    )

    logo_added = extinf_with_logo(quoted_comma, "http://example/new,logo.png")
    check('tvg-logo="http://example/new,logo.png"' in logo_added, "logo injection missing")
    check(logo_added.endswith(",ABC 13"), "logo injection moved display name")


if __name__ == "__main__":
    main()
